# Stage 1: Builder
FROM python:3.12-slim as builder

# Install build dependencies
# build-essential is often needed for compiling some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir poetry

# Configure poetry to create the virtual environment inside the project directory
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app

# Copy dependency definition files
COPY pyproject.toml poetry.lock ./

# Install dependencies (only main, no dev dependencies)
RUN poetry install --only main --no-root && rm -rf $POETRY_CACHE_DIR

# Copy prisma schema and generate the client
# Prisma downloads the query engine binary during the generate step
ENV PRISMA_BINARY_CACHE_DIR=/app/prisma-engines
COPY prisma/ prisma/
RUN poetry run prisma generate

# Stage 2: Runtime
FROM python:3.12-slim

# Set environment variables for Python and the virtual environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    MALLOC_ARENA_MAX=2 \
    WEB_CONCURRENCY=1 \
    PRISMA_BINARY_CACHE_DIR=/app/prisma-engines

# Install runtime dependencies
# Prisma requires OpenSSL to run the query engine
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
