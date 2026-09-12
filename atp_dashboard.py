#!/usr/bin/env python3
"""Simple ATP rankings dashboard served over HTTP."""

from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import List
from urllib.error import URLError
from urllib.request import Request, urlopen

ATP_RANKINGS_URL = "https://www.atptour.com/en/rankings/singles"


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
    match = re.search(r"\d+", value.replace(",", ""))
    if not match:
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


def fetch_rankings(limit: int = 20) -> List[RankingEntry]:
    request = Request(
        ATP_RANKINGS_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
    )
    with urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="ignore")
    return parse_rankings(body, limit=limit)


def render_dashboard(rankings: List[RankingEntry], error_message: str | None = None) -> str:
    rows = "\n".join(
        f"<tr><td>{entry.rank}</td><td>{html.escape(entry.player)}</td>"
        f"<td>{html.escape(entry.country)}</td><td>{html.escape(entry.points)}</td></tr>"
        for entry in rankings
    )
    error_html = f"<p class='error'>{html.escape(error_message)}</p>" if error_message else ""

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
    a.button {{ display: inline-block; margin-top: 1rem; padding: 0.4rem 0.8rem; text-decoration: none; background: #2563eb; color: #fff; border-radius: 6px; }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>ATP Tour Rankings</h1>
    <p>Source: <a href=\"{ATP_RANKINGS_URL}\">ATP Tour</a></p>
    {error_html}
    <table>
      <thead><tr><th>Rank</th><th>Player</th><th>Country</th><th>Points</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <a class=\"button\" href=\"/\">Refresh</a>
  </div>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    limit = 20

    def do_GET(self) -> None:  # noqa: N802
        rankings: List[RankingEntry] = []
        error_message = None
        try:
            rankings = fetch_rankings(limit=self.limit)
            if not rankings:
                error_message = "No rankings could be parsed from ATP response."
        except URLError as exc:
            error_message = f"Could not fetch ATP rankings: {exc.reason}"

        page = render_dashboard(rankings, error_message=error_message)
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
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a simple ATP Tour rankings dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--limit", type=int, default=20, help="Number of ranked players to display")
    args = parser.parse_args()

    run_server(args.host, args.port, args.limit)


if __name__ == "__main__":
    main()
