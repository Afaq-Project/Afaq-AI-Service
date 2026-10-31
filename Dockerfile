# Stage 1: Builder
FROM python:3.12-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv from official binary image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Configure uv for containerized builds
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Copy dependency definition files
COPY pyproject.toml uv.lock ./

# Install dependencies without installing root project
RUN uv sync --frozen --no-dev --no-install-project

# Copy prisma schema and generate the client
ENV PRISMA_BINARY_CACHE_DIR=/app/prisma-engines
COPY prisma/ prisma/
RUN uv run prisma generate

# Stage 2: Runtime
FROM python:3.12-slim

# Set environment variables for Python and the virtual environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    MALLOC_ARENA_MAX=2 \
    WEB_CONCURRENCY=1 \
    PRISMA_BINARY_CACHE_DIR=/app/prisma-engines

# Install runtime dependencies (OpenSSL is required by Prisma query engine)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy the virtual environment and Prisma engines from the builder stage
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appgroup /app/prisma-engines /app/prisma-engines

# Copy the application code and necessary directories
COPY --chown=appuser:appgroup src/ src/
COPY --chown=appuser:appgroup scripts/ scripts/
COPY --chown=appuser:appgroup prisma/ prisma/

# Switch to the non-root user
USER appuser

# Expose the API port
EXPOSE 8000

# Start the application using Uvicorn
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
