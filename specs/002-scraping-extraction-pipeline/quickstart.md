# Quickstart & Runnable Validation Guide: Scraping & Extraction Pipeline

**Feature**: `002-scraping-extraction-pipeline`  
**Created**: 2026-11-05  
**Status**: Ready for Review  

---

## 1. Prerequisites & Environment Setup

Before running scraping validation commands, ensure the local environment is configured:

1. **Python Virtual Environment**:
   ```bash
   uv sync
   ```
2. **Database Container Running**:
   Ensure PostgreSQL is running locally with schema migrated:
   ```bash
   npx prisma migrate dev
   ```
3. **Playwright / Crawl4AI Browser Binaries**:
   Ensure Chromium browser binaries are installed:
   ```bash
   uv run playwright install --with-deps chromium
   ```
4. **Environment Variables**:
   Verify the following keys exist in `.env`:
   ```bash
   DATABASE_URL="postgresql://user:pass@localhost:5432/afaq_dev"
   GEMINI_API_KEY="your-gemini-key"
   AFAQ_ATTACHMENTS_S3_BUCKET="afaq-attachments-dev"
   AWS_REGION="us-east-1"
   AFAQ_ADMIN_API_KEY="test-admin-key"
   ```

---

## 2. Running Automated Test Suites

### 2.1. Fast In-Memory Unit Tests
Execute the unit test suites for scraping services, prioritization, pagination, and language classification:
```bash
uv run pytest tests/unit/modules/scraping/ -v
```
* **Expected Outcome**: All unit tests pass deterministically in $<5$ seconds with zero external network or database calls.

### 2.2. End-to-End Integration Tests
Execute the integration test suites verifying multi-stage batch scraping and Stage 0 discovery flows:
```bash
uv run pytest tests/integration/modules/scraping/ -v
```
* **Expected Outcome**: All integration workflows pass using mocked network transports and in-memory test database sessions.

---

## 3. End-to-End Runnable Verification Flow (Manual API Probes)

### Step 1: Onboard a New Source (Stage 0 Discovery)
Submit a scholarship portal URL to trigger automated Stage 0 mapping:
```bash
curl -X POST http://localhost:8000/api/v1/scrape/sources/onboard \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-admin-key" \
  -d '{
    "url": "https://almin7.com/scholarships/",
    "name": "Almin7 Scholarships"
  }'
```
* **Expected Response (`200 OK`)**:
  ```json
  {
    "status": "success",
    "data": {
      "source_id": "...",
      "domain": "almin7.com",
      "site_name": "Almin7 Opportunities",
      "supported_languages": ["ar", "en"],
      "pagination_type": "url_param",
      "is_active": true
    }
  }
  ```

---

### Step 2: Trigger Batch Scraping Operation
Trigger an asynchronous scraping run with an idempotency key:
```bash
curl -X POST http://localhost:8000/api/v1/scrape/run \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-admin-key" \
  -H "Idempotency-Key: e3b0c442-98fc-1c14-9afb-4c8996fb9242" \
  -d '{
    "source_ids": ["<source_id_from_step_1>"]
  }'
```
* **Expected Response (`202 Accepted`)**:
  ```json
  {
    "status": "accepted",
    "operation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "sources_queued": 1,
    "sources_skipped_locked": 0,
    "message": "Scrape operation started in background..."
  }
  ```

---

### Step 3: Poll Operation Status & Telemetry
Inspect operation progress using the returned `operation_id`:
```bash
curl -X GET http://localhost:8000/api/v1/scrape/operations/7c9e6679-7425-40de-944b-e07fc1f90ae7 \
  -H "X-API-Key: test-admin-key"
```
* **Expected Response (`200 OK`)**:
  ```json
  {
    "status": "success",
    "data": {
      "operation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "status": "completed",
      "total_listings_found": 20,
      "total_details_extracted": 20,
      "total_files_downloaded": 4,
      "sources_succeeded": ["<source_id>"]
    }
  }
  ```

---

### Step 4: Query Operations History & Latest Operation
Retrieve past operation logs or query the current running/most recent operation without needing an ID:
```bash
# 1. List operations log (paginated)
curl -X GET "http://localhost:8000/api/v1/scrape/operations?limit=5" \
  -H "X-API-Key: test-admin-key"

# 2. Get current or most recent operation
curl -X GET "http://localhost:8000/api/v1/scrape/operations/latest" \
  -H "X-API-Key: test-admin-key"
```

---

### Step 5: Gracefully Abort an Operation or Halt a Specific Source
Stop an ongoing batch operation or selectively halt a single source:
```bash
# 1. Abort an entire operation (cancels tasks and releases all locks)
curl -X POST "http://localhost:8000/api/v1/scrape/operations/7c9e6679-7425-40de-944b-e07fc1f90ae7/abort" \
  -H "X-API-Key: test-admin-key"

# 2. Halt a specific source only (releases its lock; remaining batch continues)
curl -X POST "http://localhost:8000/api/v1/scrape/sources/3fa85f64-5717-4562-b3fc-2c963f66afa6/abort" \
  -H "X-API-Key: test-admin-key"
```

---

### Step 6: Verify Database Ingestion
Verify that raw records were populated in PostgreSQL:
```bash
npx prisma studio
```
Inspect:
1. `raw_listings`: 20 records with `status = "details_extracted"`.
2. `raw_grant_details`: 20 records with `status = "pending"` containing raw uncleaned JSON payloads and detected language codes.
3. `scraping_templates`: Template schemas stored with `hit_count` incremented.
4. `scrape_operations`: Operation record with status, counts, and completion times.
