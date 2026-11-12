# API Endpoints & Webhook Contracts: Scraping & Extraction Pipeline

**Feature**: `002-scraping-extraction-pipeline`  
**Created**: 2026-11-05  
**Status**: Ready for Review  

---

## 1. Authentication & Global Headers

All scraping control endpoints require administrative authentication via API key:
* **Header**: `X-API-Key: <secret_key>`
* **Error Response on Auth Failure**: `401 Unauthorized` with `{"detail": "Invalid or missing API key"}`.

---

## 2. Endpoint Contracts

### 2.1. Trigger Scrape Operation (`POST /api/v1/scrape/run`)

Initiates an asynchronous multi-source scraping job. Returns immediately with tracking metadata while execution proceeds in background tasks.

* **Method**: `POST`
* **Path**: `/api/v1/scrape/run`
* **Headers**:
  * `X-API-Key`: Required.
  * `Idempotency-Key`: Optional (`UUID`). Deduplicates requests submitted within a 15-minute sliding window.

#### Request Body
```json
{
  "source_ids": [
    "3fa85f64-5717-4562-b3fc-2c963f66afa6"
  ]
}
```
* `source_ids`: Optional array of source UUIDs. If provided, treats these sources as high-priority manual overrides ("Scrape Now"). If omitted, the engine queries all active sources and executes them in dynamic priority score order.
* Note: Ad-hoc `max_pages` overrides are omitted; crawl depth is strictly read from `source_configs.max_pages_per_run`.

#### Response: `202 Accepted` (Standard Async Initiation)
```json
{
  "status": "accepted",
  "operation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "sources_queued": 1,
  "sources_skipped_locked": 0,
  "message": "Scrape operation started in background; a webhook notification will be dispatched on completion."
}
```

#### Response: `200 OK` (Idempotency Cache Hit)
Returned when an identical `Idempotency-Key` was submitted within the last 15 minutes:
```json
{
  "status": "accepted",
  "operation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "sources_queued": 1,
  "sources_skipped_locked": 0,
  "message": "Operation already running or completed for this idempotency key."
}
```

#### Error Catalog
| Status Code | Reason | Example Response Body |
| :--- | :--- | :--- |
| `401 Unauthorized` | Missing or invalid `X-API-Key` | `{"detail": "Invalid or missing API key"}` |
| `409 Conflict` | All requested sources are currently locked by active crawls | `{"detail": "All target sources are currently locked by active operations"}` |
| `422 Unprocessable` | Malformed UUID or JSON payload syntax | `{"detail": [{"loc": ["body", "source_ids", 0], "msg": "value is not a valid uuid"}]}` |

---

### 2.2. List Operations Log (`GET /api/v1/scrape/operations`)

Retrieves a paginated list of past and ongoing scraping operations with summary counts and status.

* **Method**: `GET`
* **Path**: `/api/v1/scrape/operations`
* **Query Parameters**:
  * `status`: Optional `string` filter (`"running"`, `"completed"`, `"failed"`, `"partial"`, `"timed_out"`, `"aborted"`).
  * `limit`: `int` (1–100, default: 20).
  * `offset`: `int` (default: 0).

#### Response: `200 OK`
```json
{
  "status": "success",
  "data": {
    "total_count": 45,
    "limit": 20,
    "offset": 0,
    "operations": [
      {
        "operation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "status": "completed",
        "triggered_by": "admin_api",
        "sources_count": 3,
        "total_listings_found": 36,
        "total_details_extracted": 36,
        "total_files_downloaded": 8,
        "started_at": "2026-11-05T12:00:00Z",
        "completed_at": "2026-11-05T12:05:30Z"
      }
    ]
  },
  "message": "Operations log retrieved successfully."
}
```

---

### 2.3. Get Current or Latest Operation (`GET /api/v1/scrape/operations/latest`)

Retrieves the currently running operation if active, or the most recently executed operation if the crawler is idle, without requiring the caller to supply an ID.

* **Method**: `GET`
* **Path**: `/api/v1/scrape/operations/latest`

#### Response: `200 OK` (Active or Most Recent Operation Found)
```json
{
  "status": "success",
  "data": {
    "operation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "status": "running",
    "is_currently_active": true,
    "triggered_by": "admin_api",
    "sources_attempted": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    "sources_succeeded": [],
    "sources_failed": [],
    "total_listings_found": 15,
    "total_details_extracted": 8,
    "total_files_downloaded": 2,
    "started_at": "2026-11-05T14:30:00Z",
    "completed_at": null
  },
  "message": "Latest operation status retrieved successfully."
}
```

#### Response: `200 OK` (No Operations Yet)
```json
{
  "status": "success",
  "data": null,
  "message": "No scraping operations have been executed yet."
}
```

---

### 2.4. Get Operation Status & Telemetry (`GET /api/v1/scrape/operations/{operation_id}`)

Retrieves operational progress, counts, source outcomes, and failure error summaries for a specific operation.

* **Method**: `GET`
* **Path**: `/api/v1/scrape/operations/{operation_id}`
* **Path Parameter**: `operation_id: UUID`

#### Response: `200 OK`
```json
{
  "status": "success",
  "data": {
    "operation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "status": "completed",
    "triggered_by": "admin_api",
    "sources_attempted": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    "sources_succeeded": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    "sources_failed": [],
    "total_listings_found": 24,
    "total_details_extracted": 24,
    "total_files_downloaded": 5,
    "error_summary": {},
    "started_at": "2026-11-05T12:00:00Z",
    "completed_at": "2026-11-05T12:04:15Z"
  },
  "message": "Operation details retrieved successfully."
}
```

#### Error Catalog
| Status Code | Reason | Example Response Body |
| :--- | :--- | :--- |
| `404 Not Found` | Operation ID does not exist in `scrape_operations` | `{"detail": "Scrape operation '7c9e6679-...' not found"}` |

---

### 2.5. Abort Entire Operation (`POST /api/v1/scrape/operations/{operation_id}/abort`)

Gracefully stops an in-progress scraping operation, cancels running browser tasks, releases all acquired source locks, and sets the operation status to `aborted`.

* **Method**: `POST`
* **Path**: `/api/v1/scrape/operations/{operation_id}/abort`
* **Path Parameter**: `operation_id: UUID`

#### Response: `200 OK`
```json
{
  "status": "success",
  "data": {
    "operation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "status": "aborted",
    "aborted_at": "2026-11-05T14:35:10Z",
    "sources_released": 2,
    "message": "Scrape operation aborted successfully. All acquired source locks have been released."
  },
  "message": "Operation aborted."
}
```

#### Error Catalog
| Status Code | Reason | Example Response Body |
| :--- | :--- | :--- |
| `400 Bad Request` | Operation is already in a terminal state (`completed`, `failed`, `aborted`) | `{"detail": "Operation '7c9e6679-...' is not currently running (status: completed)"}` |
| `404 Not Found` | Operation ID does not exist | `{"detail": "Scrape operation '7c9e6679-...' not found"}` |

---

### 2.6. Halt Specific Source (`POST /api/v1/scrape/sources/{source_id}/abort`)

Selectively halts an active crawl for a specific source, cancels its browser task, and releases its lock (`is_locked = false`), allowing the remainder of the batch operation to proceed uninterrupted.

* **Method**: `POST`
* **Path**: `/api/v1/scrape/sources/{source_id}/abort`
* **Path Parameter**: `source_id: UUID`

#### Response: `200 OK`
```json
{
  "status": "success",
  "data": {
    "source_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "is_locked": false,
    "status": "aborted",
    "message": "Source crawl halted successfully. Lock released."
  },
  "message": "Source halted."
}
```

#### Error Catalog
| Status Code | Reason | Example Response Body |
| :--- | :--- | :--- |
| `400 Bad Request` | Source is not currently locked or running | `{"detail": "Source '3fa85f64-...' is not currently being scraped"}` |
| `404 Not Found` | Source ID does not exist | `{"detail": "Source '3fa85f64-...' not found"}` |

---

### 2.7. Stage 0 Source Onboarding Discovery (`POST /api/v1/scrape/sources/onboard`)

Triggers autonomous Stage 0 discovery for a newly registered or existing source URL: conducts network pre-flight health checks, DOM skeletonization, relevance validation, and populates `source_configs`.

* **Method**: `POST`
* **Path**: `/api/v1/scrape/sources/onboard`

#### Request Body
```json
{
  "url": "https://almin7.com/scholarships/",
  "name": "Almin7 Scholarships Portal"
}
```

#### Response: `200 OK`
```json
{
  "status": "success",
  "data": {
    "source_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "domain": "almin7.com",
    "site_name": "Almin7 Opportunities",
    "supported_languages": ["ar", "en"],
    "pagination_type": "url_param",
    "pagination_config": {
      "param": "page",
      "step": 1
    },
    "ordering_strategy": "chronological_descending",
    "rate_limit_delay_sec": 1.0,
    "is_active": true
  },
  "message": "Source onboarded and technical configuration populated successfully."
}
```

#### Error Catalog
| Status Code | Reason | Example Response Body |
| :--- | :--- | :--- |
| `400 Bad Request` | Domain is unreachable, parking domain, or not an opportunity portal | `{"detail": "ERR_NOT_OPPORTUNITY_PORTAL: Target website does not contain educational opportunities"}` |
| `422 Unprocessable`| URL failed security inspection (SSRF target or bad syntax) | `{"detail": "ERR_SSRF_ATTEMPT_BLOCKED: Access to private or link-local address rejected"}` |

---

### 2.8. Dead Letter Queue Audit (`GET /api/v1/scrape/dead-letter`)

Allows administrators to inspect records that permanently failed after exceeding maximum retry attempts (`max_retries = 3`).

* **Method**: `GET`
* **Path**: `/api/v1/scrape/dead-letter`
* **Query Parameters**:
  * `entity_type`: `string` (`"listings"` or `"details"`, default: `"listings"`).
  * `limit`: `int` (1–100, default: 50).
  * `offset`: `int` (default: 0).

#### Response: `200 OK`
```json
{
  "status": "success",
  "data": {
    "total_count": 2,
    "entity_type": "listings",
    "items": [
      {
        "id": "e3b0c442-98fc-1c14-9afb-4c8996fb9242",
        "source_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "discovered_url": "https://example.edu/expired-grant-2024",
        "card_title_preview": "Expired Grant 2024",
        "retry_count": 3,
        "max_retries": 3,
        "status": "failed_permanently",
        "extraction_errors": {
          "last_error": "HTTP 404: Not Found",
          "attempts": ["Timeout 30s", "Timeout 30s", "HTTP 404"]
        },
        "scraped_at": "2026-11-05T10:00:00Z"
      }
    ]
  },
  "message": "Dead letter items retrieved successfully."
}
```

---

## 3. Asynchronous Webhook Notification Contract

Upon completion of every scraping operation (status = `completed`, `partial`, or `timed_out`), the pipeline dispatches an HTTP `POST` notification payload to the configured consumer webhook endpoint (`AFAQ_WEBHOOK_URL`).

### Webhook Payload Schema
```json
{
  "event": "scrape.operation.completed",
  "timestamp": "2026-11-05T12:04:15Z",
  "payload": {
    "operation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "status": "completed",
    "triggered_by": "admin_api",
    "total_listings_found": 24,
    "total_details_extracted": 24,
    "total_files_downloaded": 5,
    "sources_succeeded": [
      "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    ],
    "sources_failed": [],
    "error_summary": {}
  }
}
```
* **Retry Policy**: 3 attempts with exponential backoff ($5s, 15s, 45s$) on non-200 responses.
