FROM python:3.12-slim as builder
RUN pip install poetry
WORKDIR /app
COPY pyproject.toml poetry.lock* /app/
RUN poetry install --no-interaction --no-root --only main
COPY ./prisma /app/prisma
RUN poetry run prisma generate --schema=/app/prisma/schema.prisma
RUN find / -name "prisma-query-engine*" > /app/engine-paths.txt

FROM python:3.12-slim
COPY --from=builder /app/engine-paths.txt /engine-paths.txt
CMD ["cat", "/engine-paths.txt"]
