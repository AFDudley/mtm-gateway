"""QEMU VM fixture for MTM E2E tests.

Boots a Packer-built QCOW2 image with Docker + laconic-so pre-installed.
Deploys the full MTM fixturenet stack inside the VM. The VM process is
killed on teardown — all state vanishes.

Uses copy-on-write snapshots so the base image stays clean across runs.
"""

from __future__ import annotations

import logging
import os
import platform
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from solders.keypair import Keypair

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]  # gateway/tests/e2e/vm_fixture.py -> mtm/

# Default QCOW2 image path — override with MTM_VM_IMAGE env var
DEFAULT_IMAGE = REPO_ROOT / "packer" / "output" / "mtm-fixturenet.qcow2"
SSH_KEY = REPO_ROOT / "packer" / "e2e-ssh-key"

# Ports the stack exposes (must match compose port declarations)
PORTS = {
    "solana_rpc": 8899,
    "x402_facilitator": 4402,
    "laconicd_gql": 9473,
    "registry_writer": 3001,
    "backtest": 8000,
    "gateway": 8091,
}

VM_SSH_PORT = 2222
VM_MEMORY = os.environ.get("MTM_VM_MEMORY", "4096")
VM_CPUS = os.environ.get("MTM_VM_CPUS", "2")


@dataclass
class StackInfo:
    """Connection details for a running MTM fixturenet stack."""

    gateway_url: str
    solana_rpc: str
    solana_network: str
    laconicd_gql: str
    test_wallet_key: str  # base58 client keypair


def _keypair_to_base58(kp: Keypair) -> str:
    """Convert a solders Keypair to base58 string (64-byte keypair)."""
    chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    b = bytes(kp)
    n = int.from_bytes(b, "big")
    result = ""
    while n > 0:
        n, r = divmod(n, 58)
        result = chars[r] + result
    for byte in b:
        if byte == 0:
            result = "1" + result
        else:
            break
    return result


def _detect_qemu() -> tuple[str, str, list[str]]:
    """Detect QEMU binary, accelerator, and extra args for the current platform.

    Returns (binary, accel, extra_args).
    """
    import struct

    is_arm = struct.calcsize("P") == 8 and platform.machine() in ("arm64", "aarch64")
    system = platform.system()

    if is_arm and system == "Darwin":
        # macOS Apple Silicon — ARM64 VM with HVF
        return (
            "qemu-system-aarch64",
            "hvf",
            ["-M", "virt", "-cpu", "host",
             "-bios", "/opt/local/share/qemu/edk2-aarch64-code.fd"],
        )
    elif system == "Linux" and Path("/dev/kvm").exists():
        return ("qemu-system-x86_64", "kvm", ["-cpu", "host"])
    else:
        return ("qemu-system-x86_64", "tcg", [])


def _wait_for_ssh(port: int, timeout: int = 120) -> None:
    """Wait for SSH to become available on localhost:port."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["ssh", "-p", str(port), "-i", str(SSH_KEY),
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
                 "mtm@localhost", "true"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(3)
    raise TimeoutError(f"SSH not available on port {port} after {timeout}s")


def _ssh_run(port: int, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command in the VM via SSH."""
    return subprocess.run(
        ["ssh", "-p", str(port), "-i", str(SSH_KEY),
         "-o", "StrictHostKeyChecking=no",
         "-o", "BatchMode=yes", "mtm@localhost", cmd],
        capture_output=True, text=True, timeout=300, check=check,
    )


def _scp_to(port: int, local_path: str, remote_path: str) -> None:
    """Copy a file into the VM."""
    subprocess.run(
        ["scp", "-P", str(port), "-i", str(SSH_KEY),
         "-o", "StrictHostKeyChecking=no",
         local_path, f"mtm@localhost:{remote_path}"],
        check=True, capture_output=True, timeout=30,
    )


def _wait_for_health(url: str, timeout: int = 120) -> None:
    """Poll a URL until it returns 200."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code == 200:
                return
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        time.sleep(3)
    raise TimeoutError(f"{url} not healthy after {timeout}s")


def start_stack() -> tuple[subprocess.Popen, StackInfo]:
    """Boot a QEMU VM and deploy the MTM fixturenet stack inside it.

    Returns the QEMU process (for teardown) and connection details.
    """
    image_path = Path(os.environ.get("MTM_VM_IMAGE", str(DEFAULT_IMAGE)))
    if not image_path.exists():
        raise FileNotFoundError(
            f"VM image not found: {image_path}\n"
            "Build it with: cd packer && packer build mtm-fixturenet.pkr.hcl"
        )

    # Create a copy-on-write snapshot so the base image stays clean
    tmpdir = Path(tempfile.mkdtemp(prefix="mtm-e2e-vm-"))
    snapshot = tmpdir / "disk.qcow2"
    subprocess.run(
        ["qemu-img", "create", "-f", "qcow2", "-b", str(image_path),
         "-F", "qcow2", str(snapshot)],
        check=True, capture_output=True,
    )

    # Build port forwarding args
    hostfwd = [f"hostfwd=tcp::{VM_SSH_PORT}-:22"]
    for name, port in PORTS.items():
        hostfwd.append(f"hostfwd=tcp::{port}-:{port}")
    netdev = f"user,id=net0,{','.join(hostfwd)}"

    qemu_bin, accel, extra_args = _detect_qemu()
    logger.info("Starting QEMU (bin=%s, accel=%s, image=%s)", qemu_bin, accel, image_path)

    qemu_cmd = [
        qemu_bin,
        "-accel", accel,
        *extra_args,
        "-m", VM_MEMORY,
        "-smp", VM_CPUS,
        "-drive", f"file={snapshot},format=qcow2",
        "-netdev", netdev,
        "-device", "virtio-net-pci,netdev=net0",
        "-nographic",
    ]

    qemu_proc = subprocess.Popen(
        qemu_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        # Wait for SSH
        logger.info("Waiting for VM SSH...")
        _wait_for_ssh(VM_SSH_PORT)

        # Generate keypairs
        facilitator_kp = Keypair()
        server_kp = Keypair()
        client_kp = Keypair()
        gateway_kp = Keypair()
        network = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"

        # Write config.env to a temp file and SCP it into the VM
        config_file = tmpdir / "config.env"
        config_file.write_text(
            f"FACILITATOR_PRIVATE_KEY={_keypair_to_base58(facilitator_kp)}\n"
            f"FACILITATOR_PUBKEY={facilitator_kp.pubkey()}\n"
            f"SERVER_PUBKEY={server_kp.pubkey()}\n"
            f"CLIENT_PUBKEY={client_kp.pubkey()}\n"
            f"GATEWAY_PUBKEY={gateway_kp.pubkey()}\n"
            f"GATEWAY_PRIVATE_KEY={_keypair_to_base58(gateway_kp)}\n"
            f"SOLANA_NETWORK={network}\n"
            f"MINT_DECIMALS=6\n"
            f"MINT_AMOUNT=1000000000\n"
            f"M2M_MINT_DECIMALS=6\n"
            f"M2M_MINT_AMOUNT=1000000000\n"
            f"ENCRYPTION_KEY={secrets.token_hex(32)}\n"
            f"FCM_DRY_RUN=true\n"
            f"TEST_AUCTION_ENABLED=false\n"
            f"TEST_REGISTRY_EXPIRY=false\n"
            f"ONBOARDING_ENABLED=false\n"
        )
        _scp_to(VM_SSH_PORT, str(config_file), "/tmp/config.env")

        # Deploy the stack
        logger.info("Deploying stack in VM...")
        result = _ssh_run(VM_SSH_PORT, "/home/mtm/start-stack.sh /tmp/config.env")
        if result.returncode != 0:
            raise RuntimeError(f"Stack deployment failed:\n{result.stderr}")

        # Wait for services
        gateway_url = f"http://localhost:{PORTS['gateway']}"
        solana_rpc = f"http://localhost:{PORTS['solana_rpc']}"

        logger.info("Waiting for services...")
        _wait_for_health(f"{gateway_url}/health", timeout=180)

        info = StackInfo(
            gateway_url=gateway_url,
            solana_rpc=solana_rpc,
            solana_network=network,
            laconicd_gql=f"http://localhost:{PORTS['laconicd_gql']}/api",
            test_wallet_key=_keypair_to_base58(client_kp),
        )

        logger.info("MTM stack ready: %s", info.gateway_url)
        return qemu_proc, info

    except Exception:
        qemu_proc.send_signal(signal.SIGTERM)
        qemu_proc.wait(timeout=10)
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
