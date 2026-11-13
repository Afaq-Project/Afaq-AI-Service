# Local synthetic HTTP fixture server for browser crawler integration tests.
# Protects ARCH-007, TEST-09, and UC-02 without external network calls.

import logging
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Self

logger = logging.getLogger(__name__)


class SyntheticFixtureHandler(BaseHTTPRequestHandler):
    """Serves controlled synthetic HTML payloads for browser crawler integration tests."""

    def log_message(self, format: str, *args: object) -> None:
        """Suppresses default stderr logging during test runs."""
        logger.debug("FixtureServer request: " + format, *args)

    def do_HEAD(self) -> None:
        """Handles HEAD requests for redirect discovery and link validation."""
        self._dispatch_route(is_head=True)

    def do_GET(self) -> None:
        """Handles GET requests for full HTML DOM navigation."""
        self._dispatch_route(is_head=False)

    def _send_html_response(
        self,
        html: str,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        is_head: bool = False,
    ) -> None:
        body = html.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for key, val in headers.items():
                self.send_header(key, val)
        self.end_headers()
        if not is_head:
            self.wfile.write(body)

    def _dispatch_route(self, is_head: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. JS-rendered dynamic content endpoint
        if path == "/js-rendered":
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>JS Rendered Catalog</title>
</head>
<body>
  <div id="catalog-container">
    <h1>Scholarships Catalog</h1>
    <div id="dynamic-listings">
      <p id="loading-indicator">Loading opportunities...</p>
    </div>
  </div>
  <script>
    document.addEventListener("DOMContentLoaded", () => {
      const container = document.getElementById("dynamic-listings");
      const loading = document.getElementById("loading-indicator");
      if (loading) loading.remove();

      const item = document.createElement("div");
      item.className = "scholarship-card";
      item.setAttribute("data-id", "sch-2026-001");
      item.innerHTML = "<h3>Future Leaders Technology Scholarship</h3>" +
                       "<p class='award-amount'>Award Amount: $15,000</p>" +
                       "<span class='deadline'>Deadline: 2026-12-31</span>";
      container.appendChild(item);
    });
  </script>
</body>
</html>"""
            self._send_html_response(html, is_head=is_head)
            return

        # 2. Multi-page pagination variants (?page=X or /pagination/X)
        if path == "/pagination" or path.startswith("/pagination/"):
            page = 1
            if path.startswith("/pagination/"):
                try:
                    page = int(path.split("/")[-1])
                except ValueError:
                    page = 1
            elif "page" in query:
                try:
                    page = int(query["page"][0])
                except ValueError:
                    page = 1

            next_link_tag = ""
            if page < 6:
                next_link_tag = f'<p><a class="next" href="/pagination?page={page + 1}">Next Page</a></p>'

            html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Scholarship Guide - Page {page}</title>
</head>
<body>
  <article class="grant-detail">
    <h1>Comprehensive Grant Guide - Part {page}</h1>
    <p class="article-text">Detailed criteria and funding specifications for Section {page}.</p>
    {next_link_tag}
  </article>
</body>
</html>"""
            self._send_html_response(html, is_head=is_head)
            return

        # 3. Repeated / stagnant loop page
        if path == "/stagnant-page":
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Stagnant Loop Page</title>
</head>
<body>
  <article class="grant-detail">
    <h1>Stagnant Listing Page</h1>
    <p class="article-text">This page links back to itself to test pagination loop termination.</p>
    <a class="next" href="/stagnant-page">Next Page</a>
  </article>
</body>
</html>"""
            self._send_html_response(html, is_head=is_head)
            return

        # 4. 404 error page
        if path == "/not-found":
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Page Not Found</title>
</head>
<body>
  <h1>404 Not Found</h1>
  <p>The requested scholarship or article resource was not found on this server.</p>
</body>
</html>"""
            self._send_html_response(html, status_code=404, is_head=is_head)
            return

        # 5. Hidden tab contents & collapsible sections
        if path == "/hidden-tabs":
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Tabbed Opportunity Details</title>
</head>
<body>
  <div class="tabs-container">
    <div role="tablist">
      <button role="tab" id="tab-btn-1">Overview</button>
      <button role="tab" id="tab-btn-2">Eligibility</button>
      <button role="tab" id="tab-btn-3">Benefits</button>
    </div>
    <div class="tab-content">
      <div id="tab-panel-overview" role="tabpanel" class="tab-pane active" style="display: block;">
        <h3>Program Overview</h3>
        <p>Visible general overview content of the opportunity.</p>
      </div>
      <div id="tab-panel-eligibility" role="tabpanel" class="tab-pane" aria-hidden="true" hidden style="display: none;">
        <h3>Eligibility Requirements</h3>
        <p>Hidden eligibility requirements and GPA thresholds.</p>
      </div>
      <div id="tab-panel-benefits" role="tabpanel" class="tab-pane" aria-hidden="true" hidden style="display: none;">
        <h3>Award Benefits</h3>
        <p>Hidden monetary and housing allowance details.</p>
      </div>
      <div id="accordion-selection" class="accordion-collapse collapse" style="display: none; visibility: hidden;">
        <h3>Selection Protocol</h3>
        <p>Hidden panel covering interview dates and evaluation matrices.</p>
      </div>
    </div>
  </div>
</body>
</html>"""
            self._send_html_response(html, is_head=is_head)
            return

        # 6. Redirect chain (302 redirect to /redirect-target)
        if path == "/redirect-start":
            self.send_response(302)
            self.send_header("Location", "/redirect-target")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path == "/redirect-target":
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Final Redirect Target</title>
</head>
<body>
  <main>
    <h1>Redirect Target Reached</h1>
    <p>Successfully landed on the canonical scholarship announcement page.</p>
  </main>
</body>
</html>"""
            self._send_html_response(html, is_head=is_head)
            return

        # 7. Rate-limit response (HTTP 429 with Retry-After header)
        if path == "/rate-limit":
            retry_seconds = query.get("seconds", ["360"])[0]
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>429 Too Many Requests</title>
</head>
<body>
  <h1>Too Many Requests</h1>
  <p>Rate limit exceeded. Please retry after cooldown period.</p>
</body>
</html>"""
            self._send_html_response(
                html,
                status_code=429,
                headers={"Retry-After": retry_seconds},
                is_head=is_head,
            )
            return

        # 8. Bot challenge simulation page
        if path == "/bot-challenge":
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Just a Moment...</title>
</head>
<body>
  <div class="cf-challenge">
    <div id="challenge-running">Checking your browser before accessing scholarships portal...</div>
    <div class="cf-turnstile"></div>
  </div>
</body>
</html>"""
            self._send_html_response(html, is_head=is_head)
            return

        # Default root / index page
        index_html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Fixture Server Root</title>
</head>
<body>
  <h1>Synthetic Browser Crawl Fixtures</h1>
  <ul>
    <li><a href="/js-rendered">JS Rendered Listings</a></li>
    <li><a href="/pagination?page=1">Multi-Page Pagination</a></li>
    <li><a href="/stagnant-page">Stagnant Page</a></li>
    <li><a href="/hidden-tabs">Hidden Tabs</a></li>
    <li><a href="/redirect-start">Redirect Chain</a></li>
    <li><a href="/rate-limit">Rate Limit (429)</a></li>
    <li><a href="/bot-challenge">Bot Challenge</a></li>
  </ul>
</body>
</html>"""
        self._send_html_response(index_html, is_head=is_head)


class LocalFixtureServer:
    """Manages lifecycle of the local synthetic HTTP test server on an ephemeral port."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self._server = ThreadingHTTPServer((host, port), SyntheticFixtureHandler)
        self.port: int = self._server.server_port
        self._thread: threading.Thread | None = None
        self._is_running = False

    @property
    def base_url(self) -> str:
        """Returns the full HTTP base URL for this local fixture server."""
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        """Starts the HTTP server on a background daemon thread."""
        if self._is_running:
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name=f"FixtureServer-{self.port}",
        )
        self._thread.start()
        self._is_running = True
        logger.info("LocalFixtureServer started at %s", self.base_url)

    def stop(self) -> None:
        """Shuts down the HTTP server and joins the background thread."""
        if not self._is_running:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._is_running = False
        logger.info("LocalFixtureServer stopped on port %d", self.port)

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()


if __name__ == "__main__":
    import sys
    import time

    cli_port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    server = LocalFixtureServer(port=cli_port)
    server.start()
    print(f"Fixture server running at {server.base_url} (Ctrl+C to stop)...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        print("Stopped.")
