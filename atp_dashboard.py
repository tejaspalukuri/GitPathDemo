#!/usr/bin/env python3
"""Simple ATP rankings dashboard served over HTTP."""

from __future__ import annotations

import argparse
import html
import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from urllib.parse import parse_qs, urlparse

ATP_RANKINGS_URL = "https://www.atptour.com/en/rankings/singles"
CACHE_TTL_SECONDS = 300  # 5 minutes
STALE_CACHE_WARNING = "Upstream ATP site unreachable; showing cached data"

_rankings_html_cache: str | None = None
_rankings_cache_expires_at: float = 0.0
_cache_lock = threading.Lock()


@dataclass
class RankingEntry:
    rank: int
    player: str
    country: str
    points: str


@dataclass
class RankingsResult:
    rankings: List[RankingEntry]
    warning: str | None = None


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
    with _cache_lock:
        _rankings_html_cache = None
        _rankings_cache_expires_at = 0.0


def _fetch_rankings_html() -> str:
    request = Request(
        ATP_RANKINGS_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
    )
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="ignore")


def get_rankings_html(force_refresh: bool = False) -> tuple[str, str | None]:
    """Return ATP rankings HTML and an optional stale-cache warning."""
    global _rankings_html_cache, _rankings_cache_expires_at

    with _cache_lock:
        now = time.monotonic()
        if (
            not force_refresh
            and _rankings_html_cache is not None
            and now < _rankings_cache_expires_at
        ):
            return _rankings_html_cache, None

        cached_html = _rankings_html_cache

    try:
        body = _fetch_rankings_html()
    except (URLError, HTTPError):
        if cached_html is not None:
            return cached_html, STALE_CACHE_WARNING
        raise

    with _cache_lock:
        _rankings_html_cache = body
        _rankings_cache_expires_at = time.monotonic() + CACHE_TTL_SECONDS
    return body, None


def fetch_rankings(limit: int = 20, force_refresh: bool = False) -> RankingsResult:
    body, warning = get_rankings_html(force_refresh=force_refresh)
    return RankingsResult(rankings=parse_rankings(body, limit=limit), warning=warning)


def render_dashboard(
    rankings: List[RankingEntry],
    error_message: str | None = None,
    search_query: str | None = None,
    warning_message: str | None = None,
) -> str:
    rows = "\n".join(
        f"<tr><td>{entry.rank}</td><td>{html.escape(entry.player)}</td>"
        f"<td>{html.escape(entry.country)}</td><td>{html.escape(entry.points)}</td></tr>"
        for entry in rankings
    )
    error_html = f"<p class='error'>{html.escape(error_message)}</p>" if error_message else ""
    warning_html = (
        f"<p class='warning'>{html.escape(warning_message)}</p>" if warning_message else ""
    )
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
    .warning {{ color: #92400e; background: #fef3c7; padding: 0.5rem 0.75rem; border-radius: 4px; }}
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
    {warning_html}
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


def rankings_to_json(rankings: List[RankingEntry]) -> list[dict]:
    return [asdict(entry) for entry in rankings]


class DashboardHandler(BaseHTTPRequestHandler):
    limit = 20

    def _send_json(
        self, status: int, payload: object, extra_headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, page: str) -> None:
        payload = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",
        )
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _load_rankings(
        self, limit: int, search_query: str | None, force_refresh: bool
    ) -> RankingsResult:
        result = fetch_rankings(limit=limit, force_refresh=force_refresh)
        rankings = result.rankings
        if search_query:
            rankings = [r for r in rankings if search_query.lower() in r.player.lower()]
        return RankingsResult(rankings=rankings, warning=result.warning)

    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)

        raw_limit = query_params["limit"][0] if "limit" in query_params else None
        limit = parse_limit_param(raw_limit, self.limit)
        search_query = query_params.get("search", [None])[0]
        force_refresh = query_params.get("refresh", [""])[0] == "1"

        if parsed_url.path == "/api/rankings":
            try:
                result = self._load_rankings(limit, search_query, force_refresh)
            except (URLError, HTTPError) as exc:
                reason = getattr(exc, "reason", str(exc))
                self._send_json(503, {"error": f"Could not fetch ATP rankings: {reason}"})
                return
            extra = {"X-ATP-Warning": result.warning} if result.warning else None
            self._send_json(200, rankings_to_json(result.rankings), extra_headers=extra)
            return

        rankings: List[RankingEntry] = []
        error_message = None
        warning_message = None
        try:
            result = self._load_rankings(limit, search_query, force_refresh)
            rankings = result.rankings
            warning_message = result.warning
            if not rankings:
                error_message = "No rankings found matching criteria."
        except (URLError, HTTPError) as exc:
            reason = getattr(exc, "reason", str(exc))
            error_message = f"Could not fetch ATP rankings: {reason}"

        page = render_dashboard(
            rankings,
            error_message=error_message,
            search_query=search_query,
            warning_message=warning_message,
        )
        self._send_html(200, page)


def run_server(host: str, port: int, limit: int) -> None:
    DashboardHandler.limit = limit
    server = ThreadingHTTPServer((host, port), DashboardHandler)
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
