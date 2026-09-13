#!/usr/bin/env python3
"""Simple ATP rankings dashboard served over HTTP."""

from __future__ import annotations

import argparse
import html
import logging
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from urllib.parse import parse_qs, urlparse

ATP_RANKINGS_URL = "https://www.atptour.com/en/rankings/singles"
CACHE_TTL_SECONDS = 300  # 5 minutes

_rankings_html_cache: str | None = None
_rankings_cache_expires_at: float = 0.0

logger = logging.getLogger(__name__)
MAX_FETCH_ATTEMPTS = 3
RETRY_INITIAL_DELAY_SECONDS = 0.5


@dataclass
class RankingEntry:
    rank: int
    player: str
    country: str
    points: str


class ATPRankingsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_row = False
        self._in_cell = False
        self._current_cell: List[str] = []
        self._cells: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._in_row = True
            self._cells = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            text = " ".join("".join(self._current_cell).split())
            self._cells.append(text)
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            cleaned = [value for value in self._cells if value]
            if cleaned:
                self.rows.append(cleaned)
            self._in_row = False


def _parse_rank(value: str) -> int | None:
    """Extract an integer rank, including tied ranks like T-10, T1, or 10=."""
    match = re.search(r"\d+", value.replace(",", ""))
    if match is None:
        return None
    return int(match.group(0))


def _parse_points(cells: List[str]) -> str:
    for cell in reversed(cells):
        if re.fullmatch(r"[\d,]+", cell):
            return cell
    return "N/A"


def _parse_country(cells: List[str], player: str) -> str:
    for cell in cells:
        if cell == player:
            continue
        if re.fullmatch(r"[A-Z]{3}", cell):
            return cell
    return "N/A"


def parse_rankings(page_html: str, limit: int) -> List[RankingEntry]:
    parser = ATPRankingsParser()
    parser.feed(page_html)

    rankings: List[RankingEntry] = []
    for cells in parser.rows:
        if not cells:
            continue
        rank = _parse_rank(cells[0])
        if rank is None:
            continue

        player = next((cell for cell in cells[1:] if re.search(r"[A-Za-z]", cell)), "Unknown")
        country = _parse_country(cells[1:], player)
        points = _parse_points(cells[1:])

        rankings.append(RankingEntry(rank=rank, player=player, country=country, points=points))
        if len(rankings) >= limit:
            break

    return rankings


def clear_rankings_cache() -> None:
    global _rankings_html_cache, _rankings_cache_expires_at
    _rankings_html_cache = None
    _rankings_cache_expires_at = 0.0


def _is_retryable_http_error(exc: HTTPError) -> bool:
    return exc.code in {408, 425, 429, 500, 502, 503, 504}


def _fetch_rankings_html() -> str:
    request = Request(
        ATP_RANKINGS_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
    )
    delay = RETRY_INITIAL_DELAY_SECONDS
    last_error: Exception | None = None

    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            last_error = exc
            if not _is_retryable_http_error(exc) or attempt == MAX_FETCH_ATTEMPTS:
                raise
            logger.warning(
                "Transient HTTP %s fetching ATP rankings (attempt %s/%s); retrying in %.1fs",
                exc.code,
                attempt,
                MAX_FETCH_ATTEMPTS,
                delay,
            )
        except URLError as exc:
            last_error = exc
            if attempt == MAX_FETCH_ATTEMPTS:
                raise
            logger.warning(
                "Transient network error fetching ATP rankings (attempt %s/%s): %s; retrying in %.1fs",
                attempt,
                MAX_FETCH_ATTEMPTS,
                exc.reason,
                delay,
            )

        time.sleep(delay)
        delay *= 2

    assert last_error is not None
    raise last_error


def get_rankings_html(force_refresh: bool = False) -> str:
    """Return ATP rankings HTML, using an in-memory TTL cache when fresh."""
    global _rankings_html_cache, _rankings_cache_expires_at

    now = time.monotonic()
    if (
        not force_refresh
        and _rankings_html_cache is not None
        and now < _rankings_cache_expires_at
    ):
        return _rankings_html_cache

    body = _fetch_rankings_html()
    _rankings_html_cache = body
    _rankings_cache_expires_at = now + CACHE_TTL_SECONDS
    return body


def fetch_rankings(limit: int = 20, force_refresh: bool = False) -> List[RankingEntry]:
    body = get_rankings_html(force_refresh=force_refresh)
    return parse_rankings(body, limit=limit)


def render_dashboard(
    rankings: List[RankingEntry],
    error_message: str | None = None,
    search_query: str | None = None,
) -> str:
    rows = "\n".join(
        f"<tr><td>{entry.rank}</td><td>{html.escape(entry.player)}</td>"
        f"<td>{html.escape(entry.country)}</td><td>{html.escape(entry.points)}</td></tr>"
        for entry in rankings
    )
    error_html = f"<p class='error'>{html.escape(error_message)}</p>" if error_message else ""
    escaped_query = html.escape(search_query or "", quote=True)
    search_html = (
        f"<p class='search-status'>Results matching: <strong>{escaped_query}</strong></p>"
        if search_query
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>ATP Rankings Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; background: #f4f6f8; color: #222; }}
    h1 {{ margin-bottom: 0.5rem; }}
    .card {{ background: #fff; border-radius: 8px; padding: 1rem 1.25rem; box-shadow: 0 2px 8px rgba(0,0,0,0.08); max-width: 800px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
    th, td {{ padding: 0.6rem; border-bottom: 1px solid #e5e7eb; text-align: left; }}
    th {{ background: #f9fafb; }}
    .error {{ color: #b91c1c; font-weight: bold; }}
    .search-status {{ margin-top: 0.5rem; color: #4b5563; }}
    .search-form {{ margin-top: 1rem; display: flex; gap: 0.5rem; }}
    .search-form input {{ padding: 0.4rem 0.6rem; border: 1px solid #d1d5db; border-radius: 4px; flex-grow: 1; }}
    .search-form button {{ padding: 0.4rem 0.8rem; background: #2563eb; color: #fff; border: none; border-radius: 4px; cursor: pointer; }}
    a.button {{ display: inline-block; margin-top: 1rem; padding: 0.4rem 0.8rem; text-decoration: none; background: #2563eb; color: #fff; border-radius: 6px; }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>ATP Tour Rankings</h1>
    <p>Source: <a href=\"{ATP_RANKINGS_URL}\">ATP Tour</a></p>
    <form class=\"search-form\" method=\"GET\" action=\"/\">
      <input type=\"text\" name=\"search\" placeholder=\"Search player by name...\" value=\"{escaped_query}\" />
      <button type=\"submit\">Search</button>
    </form>
    {search_html}
    {error_html}
    <table>
      <thead><tr><th>Rank</th><th>Player</th><th>Country</th><th>Points</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <a class=\"button\" href=\"/?refresh=1\">Reset / Refresh</a>
  </div>
</body>
</html>"""


MIN_LIMIT = 1
MAX_LIMIT = 100


def parse_limit_param(raw_value: str | None, default: int) -> int:
    """Parse and clamp a limit query value; fall back to default when invalid."""
    if raw_value is None:
        return default
    try:
        limit = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(MIN_LIMIT, min(limit, MAX_LIMIT))


class DashboardHandler(BaseHTTPRequestHandler):
    limit = 20

    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)

        raw_limit = query_params["limit"][0] if "limit" in query_params else None
        limit = parse_limit_param(raw_limit, self.limit)

        search_query = query_params.get("search", [None])[0]
        force_refresh = query_params.get("refresh", [""])[0] == "1"

        rankings: List[RankingEntry] = []
        error_message = None
        try:
            rankings = fetch_rankings(limit=limit, force_refresh=force_refresh)
            if search_query:
                rankings = [r for r in rankings if search_query.lower() in r.player.lower()]
            if not rankings:
                error_message = "No rankings found matching criteria."
        except URLError as exc:
            error_message = f"Could not fetch ATP rankings: {exc.reason}"

        page = render_dashboard(rankings, error_message=error_message, search_query=search_query)
        payload = page.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run_server(host: str, port: int, limit: int) -> None:
    DashboardHandler.limit = limit
    server = HTTPServer((host, port), DashboardHandler)
    print(f"Serving ATP dashboard on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a simple ATP Tour rankings dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--limit", type=int, default=20, help="Number of ranked players to display")
    args = parser.parse_args()

    run_server(args.host, args.port, args.limit)


if __name__ == "__main__":
    main()
