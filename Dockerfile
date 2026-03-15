FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev

# Copy application code
COPY src/ src/

EXPOSE 8091

CMD ["uv", "run", "uvicorn", "mtm_gateway.main:app", \
     "--host", "0.0.0.0", "--port", "8091"]
