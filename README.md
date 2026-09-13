# GitPathDemo

Simple Python dashboard that scrapes the latest ATP Tour singles rankings and displays them in a local web page.

## Run

From the repository root:

```bash
python atp_dashboard.py --port 8000
```

Then open `http://127.0.0.1:8000` in your browser.

## JSON API

```bash
curl "http://127.0.0.1:8000/api/rankings"
curl "http://127.0.0.1:8000/api/rankings?limit=10&search=Alcaraz"
```

## Tests

Run the automated unit test suite with:

```bash
python -m unittest discover tests
```
