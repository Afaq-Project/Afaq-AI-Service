# Technical Research & Architecture Decisions: Security & Validation Module

**Feature**: `001-security-validation-module`  
**Created**: 2026-11-01  
**Status**: Completed & Approved  

---

## 1. Anti-SSRF Defense & Chromium DNS Pinning

### Decision
Implement pre-request DNS resolution using Python's native `asyncio.get_event_loop().getaddrinfo()` and parse all returned IPv4/IPv6 addresses against standard `ipaddress.ip_network` CIDR blocks. Generate Chromium-compatible host resolver rules (`--host-resolver-rules="MAP <host> <verified-ip>"`) to pass to Playwright / Crawl4AI.

### Rationale
* **Cloud Security:** Directly querying URLs without DNS pre-screening allows SSRF attacks targeting AWS IMDS (`169.254.169.254`) or VPC internal services (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
* **TOCTOU Elimination:** Time-of-Check to Time-of-Use DNS rebinding allows an attacker to resolve a public IP during pre-screening but return `127.0.0.1` during the actual HTTP fetch. Chromium's native `--host-resolver-rules` forces the browser process to connect strictly to the IP address verified by the application, eliminating the vulnerability without proxy overhead.

### Alternatives Considered
* **HTTP Forward Proxy with DNS filtering (e.g. Squid/Privoxy):** Rejected due to operational complexity, container RAM footprint, and unnecessary network hops in a lightweight modular monolith.
* **Socket-level IP hooks in Python:** Works for standard HTTP clients (e.g. `httpx`), but does not protect the separate Chromium/Playwright browser process. Chromium command-line pinning protects both.

---

## 2. Safe Rich-Text HTML Sanitization Engine

### Decision
Adopt Mozilla's Rust-backed `ammonia` engine via Python bindings `nh3` (`nh3.clean()`), configuring an explicit whitelist of structural educational tags (`p`, `br`, `strong`, `em`, `ul`, `ol`, `li`, `h3`-`h5`, `table`, `tr`, `td`), allowed attributes (`dir`, `lang`, `colspan`, `rowspan`), and link attributes (`rel="noopener noreferrer nofollow"`).

### Rationale
* **Memory Safety & Performance:** `nh3` executes in native Rust and is $\sim 20\times$ faster than legacy Python HTML sanitizers, maintaining $<20$ms execution times.
* **Fail-Secure XSS Prevention:** Permanently strips `script`, `style`, `iframe`, `object`, `svg`, inline event handlers (`onload=`, `onclick=`), and URI schemes other than `http`, `https`, `mailto`.

### Alternatives Considered
* **`bleach` (Python/html5lib):** Officially deprecated by Mozilla, slow parsing speed, and susceptible to performance regressions on large DOM fragments.
* **Custom Regex Replacement:** Strongly rejected. HTML cannot be safely parsed or sanitized via regular expressions and is vulnerable to parser-mutation XSS.

---

## 3. CSS Selector ReDoS (Regular Expression Denial of Service) & Backtracking Defense

### Decision
A 4-tier validation pipeline:
1. Syntax pre-compilation via `soupsieve.compile(selector)`.
2. Static AST / complexity bounds: length $\le 300$ chars, nesting depth of `:has()` $\le 1$, structural combinators (`>`, `+`, `~`, `:has`, `:not`) $\le 5$, no universal root `*`.
3. Execution timeout gate: evaluate candidate selectors against sample HTML within a strict 200ms `asyncio.wait_for` timeout.
4. Granular micro-repair prompt trigger upon individual selector failure.

### Rationale
AI models synthesizing extraction templates often generate deeply nested `:has()` pseudo-classes or combinator trees that cause catastrophic backtracking in CSS parsers. The 200ms dry-run timeout ensures crawler workers never freeze or block worker event loops.

### Alternatives Considered
* **Unrestricted CSS selectors with worker kill timers:** Rejected because hard worker kills abort entire crawl batches and leak orphaned browser processes.
* **Regex-only extraction:** Rejected because modern educational websites require DOM tree traversal for complex hierarchical tables and scholarship cards.

---

## 4. File Attachment Magic-Byte Verification & Zip-Bomb Guard

### Decision
* **Magic-Byte Slicing:** Pure-Python byte inspection of leading headers using fixed hex signatures (`%PDF-` for PDF, `PK\x03\x04` for DOCX/XLSX, `\xFF\xD8\xFF` for JPEG, `\x89PNG` for PNG, `RIFF...WEBP` for WEBP). Disallowed executable headers (`4D 5A` MZ, `7F 45 4C 46` ELF, `#!` scripts) are rejected immediately.
* **Zip-Bomb Decompression Guard:** Inspect ZIP central directory table (`zipfile.ZipFile(stream).infolist()`) without full decompression. Reject archives exceeding 50 MB total uncompressed size or a 100:1 compression ratio.
* **S3 Key Derivation:** Sanitize `Content-Disposition` filename; fall back to `{sha256[:16]}.{detected_ext}`.

### Rationale
* **Zero System Dependencies:** Eliminates reliance on `libmagic` C shared libraries, ensuring portability across Linux distributions and Docker images.
* **Resource Exhaustion Defense:** Malicious archives can compress gigabytes of zeroes into a few kilobytes. Inspecting metadata headers without decompression neutralizes the attack before allocating worker memory.

### Alternatives Considered
* **`python-magic` (`libmagic`):** Requires system C libraries (`libmagic-dev`), which can lead to deployment inconsistencies across environments.
* **Full streaming decompression into temporary files:** Vulnerable to disk-space exhaustion (Zip Bomb).

---

## 5. Prompt & Command Injection Defense Delegation

### Decision
All prompt injection, command injection handling, XML sandbox packaging (`<untrusted_web_content>`), and delimiter escaping are **strictly delegated to the downstream Scraping & Extraction Module (`src/modules/scraping/`)**. The Security Module contains zero prompt inspection heuristics, zero text redacting, and zero delimiter manipulation.

### Rationale
* **Zero Content Mutation:** A security gatekeeper must not alter text or intervene in prompt phrasing. Mutating text risks false positives on legitimate grant descriptions and breaks single-responsibility boundaries.
* **Context-Aware Defenses in Scraping:** The scraping engine constructs LLM prompts directly and employs strict system instructions (priming models to treat scraped DOM blocks as passive data), where delimiter escaping and prompt packaging naturally belong.
* **Microsecond Gatekeeper Latency:** Without regex text scanning or prompt heuristics, `LinkValidator`, `FileValidator`, and `SchemaValidator` execute purely deterministic, microsecond-fast checks.

