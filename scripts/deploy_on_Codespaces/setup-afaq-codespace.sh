#!/usr/bin/env bash
set -Eeuo pipefail

DB_CONTAINER="afaq-scraper-postgres"
DB_NAME="afaq_scraper"
DB_USER="scraper"
DB_PASSWORD="afaq_scraper_local_pw"
DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}"

if [[ -f "$PWD/prisma/schema.prisma" ]]; then
  PROJECT_ROOT="$PWD"
else
  SCHEMA_PATH="$(find /workspaces -maxdepth 4 -type f -path '*/prisma/schema.prisma' -print -quit 2>/dev/null || true)"
  if [[ -z "$SCHEMA_PATH" ]]; then
    echo "Could not find the Afaq project Prisma schema under /workspaces." >&2
    exit 1
  fi
  PROJECT_ROOT="$(dirname "$(dirname "$SCHEMA_PATH")")"
fi
cd "$PROJECT_ROOT"

for tool in docker uv python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Required command is missing: $tool" >&2
    exit 1
  fi
done

if ! git check-ignore -q .env; then
  echo "Refusing to store test credentials: .env is not ignored by Git." >&2
  exit 1
fi

if ! docker container inspect "$DB_CONTAINER" >/dev/null 2>&1; then
  docker run -d \
    --name "$DB_CONTAINER" \
    --restart unless-stopped \
    -e "POSTGRES_USER=$DB_USER" \
    -e "POSTGRES_PASSWORD=$DB_PASSWORD" \
    -e "POSTGRES_DB=$DB_NAME" \
    -p 5432:5432 \
    --health-cmd "pg_isready -U $DB_USER -d $DB_NAME" \
    --health-interval 5s \
    --health-timeout 3s \
    --health-retries 12 \
    postgres:16
else
  docker start "$DB_CONTAINER" >/dev/null 2>&1 || true
fi

ready=0
for attempt in $(seq 1 60); do
  if docker exec "$DB_CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" -ne 1 ]]; then
  echo "PostgreSQL did not become ready within 120 seconds." >&2
  exit 1
fi

export DATABASE_URL
export DIRECT_URL="$DATABASE_URL"
uv sync --frozen
uv run prisma generate
# Build the Codespace database from the committed Prisma schema. This avoids
# relying on migrations that may lag behind that schema; no data-loss override is used.
uv run prisma db push
sudo uv run playwright install-deps chromium
uv run playwright install chromium

export AFAQ_SETUP_DATABASE_URL="$DATABASE_URL"
uv run python - <<'PY'
import asyncio
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values

from_file = Path(".env")
old_lines = from_file.read_text(encoding="utf-8").splitlines() if from_file.exists() else []
old_values = {key: value for key, value in dotenv_values(from_file).items() if value is not None} if from_file.exists() else {}

updates = {
    "DATABASE_URL": os.environ["AFAQ_SETUP_DATABASE_URL"],
    "DIRECT_URL": os.environ["AFAQ_SETUP_DATABASE_URL"],
    "ENVIRONMENT": "development",
    "LOG_LEVEL": old_values.get("LOG_LEVEL", "INFO"),
}
for key in ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
    if os.environ.get(key):
        updates[key] = os.environ[key]
    elif old_values.get(key):
        updates[key] = old_values[key]

api_key = old_values.get("SCRAPE_TEST_API_KEY") or f"lv_{secrets.token_urlsafe(32)}"
updates["SCRAPE_TEST_API_KEY"] = api_key

output_lines = []
written = set()
for line in old_lines:
    key, separator, _ = line.partition("=")
    if separator and key in updates:
        if key not in written:
            output_lines.append(f"{key}={updates[key]}")
            written.add(key)
    else:
        output_lines.append(line)
for key, value in updates.items():
    if key not in written:
        output_lines.append(f"{key}={value}")

from_file.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")
from_file.chmod(0o600)
os.environ.update(updates)
os.environ["DATABASE_URL"] = updates["DATABASE_URL"]
os.environ["DIRECT_URL"] = updates["DIRECT_URL"]

from prisma import Prisma
from src.modules.core.auth.api_key_auth import hash_key

async def ensure_test_api_key() -> None:
    db = Prisma()
    await db.connect()
    try:
        hashed = hash_key(api_key)
        existing = await db.apikey.find_unique(where={"key": hashed})
        if existing is None:
            await db.apikey.create(
                data={
                    "key": hashed,
                    "name": "Codespace scraper validation",
                    "is_active": True,
                }
            )
    finally:
        await db.disconnect()

asyncio.run(ensure_test_api_key())
print("Environment settings and API-key record are ready; the raw key is stored only in the ignored .env file.")
PY

cat <<'EOF'

Codespace scraping setup is ready.
Start the API when needed with:
  uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
The test API key is stored as SCRAPE_TEST_API_KEY in .env. Set GOOGLE_API_KEY or ANTHROPIC_API_KEY in .env before onboarding a new source.
EOF
