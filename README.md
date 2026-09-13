# GitPathDemo

Simple Python dashboard that scrapes the latest ATP Tour singles rankings and displays them in a local web page.

## Run

```bash
python atp_dashboard.py --port 8000
```

Then open `http://127.0.0.1:8000` in your browser.

## JSON API

Fetch rankings as JSON:

```bash
curl "http://127.0.0.1:8000/api/rankings"
curl "http://127.0.0.1:8000/api/rankings?limit=10&search=Alcaraz"
```

Query parameters:
- `limit` — number of results (default 20, clamped to 1–100)
- `search` — case-insensitive player name filter

## Tests

Run the automated unit test suite with:

```bash
python -m unittest discover tests
```
