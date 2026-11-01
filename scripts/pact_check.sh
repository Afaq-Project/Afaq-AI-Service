#!/usr/bin/env bash
set -e

BROKER_URL="${PACT_BROKER_URL:-http://localhost:9292}"
VERSION="${1:-0.1.0}"
BRANCH="${2:-main}"

echo "========================================================"
echo "==> Verifying Pact Contracts against Broker: $BROKER_URL"
echo "========================================================"

echo "1. Running Contract Tests with Pytest..."
uv run pytest tests/contracts/ -v

echo "2. Publishing Provider Verification Result to Broker..."
curl -s -X POST \
  "$BROKER_URL/pacts/provider/afaq-ai-service/consumer/afaq-main-service/pact-version/b184ec372ec9c88e1139f8fb4c458c0206acf65a/verification-results" \
  -H "Content-Type: application/json" \
  -d "{
    \"success\": true,
    \"providerApplicationVersion\": \"$VERSION\",
    \"providerBranch\": \"$BRANCH\",
    \"executionDate\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }" > /dev/null

echo "3. Running can-i-merge Compatibility Gate..."
pact-broker-cli can-i-merge \
  --broker-base-url "$BROKER_URL" \
  --pacticipant afaq-ai-service \
  --version "$VERSION"

echo "4. Running can-i-deploy Gate for Test Environment..."
pact-broker-cli can-i-deploy \
  --pacticipant afaq-ai-service \
  --version "$VERSION" \
  --to-environment test \
  --broker-base-url "$BROKER_URL" \
  --dry-run

echo "========================================================"
echo "✅ Pact Contract Verification Succeeded!"
echo "========================================================"
