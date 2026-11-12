#!/usr/bin/env bash
set -e

BROKER_URL="${PACT_BROKER_URL:-http://localhost:9292}"
VERSION="${1:-${GITHUB_SHA:-$(git rev-parse --short HEAD)}}"
BRANCH="${2:-${GITHUB_REF_NAME:-$(git branch --show-current)}}"
CONSUMER="afaq-ai-service-contract-guard"
PROVIDER="afaq-ai-service"
PACT_FILE="pacts/afaq-ai-service-contract-guard-afaq-ai-service.json"

echo "========================================================"
echo "==> Verifying Pact Contracts against Broker: $BROKER_URL"
echo "========================================================"

echo "1. Running Contract Tests with Pytest..."
uv run pytest tests/contracts/ -v

echo "2. Publishing the verified internal contract to the Pact Broker..."
pact-broker-cli publish \
  --broker-base-url "$BROKER_URL" \
  --consumer-app-version "$VERSION" \
  --branch "$BRANCH" \
  --validate \
  --strict \
  "$PACT_FILE"

echo "3. Recording the provider verification against this pact version..."
PACT_VERSION_URL="$BROKER_URL/pacts/provider/$PROVIDER/consumer/$CONSUMER/version/$VERSION"
VERIFICATION_URL="$(curl -fsS -H 'Accept: application/hal+json' "$PACT_VERSION_URL" \
  | jq -r '._links["pb:publish-verification-results"].href')"
test -n "$VERIFICATION_URL" && test "$VERIFICATION_URL" != "null"
curl -fsS -X POST \
  "$VERIFICATION_URL" \
  -H "Content-Type: application/json" \
  -d "{
    \"success\": true,
    \"providerApplicationVersion\": \"$VERSION\",
    \"providerBranch\": \"$BRANCH\",
    \"executionDate\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }" > /dev/null

echo "4. Running can-i-merge Compatibility Gate..."
pact-broker-cli can-i-merge \
  --broker-base-url "$BROKER_URL" \
  --pacticipant "$PROVIDER" \
  --version "$VERSION"

echo "5. Running can-i-deploy Gate for Test Environment..."
pact-broker-cli can-i-deploy \
  --pacticipant "$PROVIDER" \
  --version "$VERSION" \
  --to-environment test \
  --broker-base-url "$BROKER_URL" \
  --dry-run

echo "========================================================"
echo "✅ Pact Contract Verification Succeeded!"
echo "========================================================"
