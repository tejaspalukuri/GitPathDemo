import os
import sys
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from atp_dashboard import (
    ATPRankingsParser,
    DashboardHandler,
    RankingEntry,
    _parse_country,
    _parse_points,
    _parse_rank,
    parse_limit_param,
    parse_rankings,
    render_dashboard,
)


SAMPLE_TABLE_HTML = """
<table>
  <tr><th>Rank</th><th>Player</th><th>Country</th><th>Points</th></tr>
  <tr><td>1</td><td>Jannik Sinner</td><td>ITA</td><td>11,830</td></tr>
  <tr><td>2</td><td>Carlos Alcaraz</td><td>ESP</td><td>8,920</td></tr>
  <tr><td>T-10</td><td>Tied Player</td><td>USA</td><td>1,200</td></tr>
  <tr><td>T1</td><td>Also Tied</td><td>FRA</td><td>1,100</td></tr>
  <tr></tr>
  <tr><td></td><td></td></tr>
  <tr><td colspan="4">Divider</td></tr>
</table>
"""


class TestATPRankingsParser(unittest.TestCase):
    def test_extracts_standard_rows(self):
        parser = ATPRankingsParser()
        parser.feed(
            "<table><tr><td>1</td><td>Jannik Sinner</td><td>ITA</td><td>11,830</td></tr></table>"
        )
        self.assertEqual(parser.rows, [["1", "Jannik Sinner", "ITA", "11,830"]])

    def test_skips_empty_rows(self):
        parser = ATPRankingsParser()
        parser.feed("<table><tr></tr><tr><td></td></tr><tr><td>3</td><td>Player</td></tr></table>")
        self.assertEqual(parser.rows, [["3", "Player"]])


class TestParseHelpers(unittest.TestCase):
    def test_parse_rank_standard_and_tied(self):
        self.assertEqual(_parse_rank("10"), 10)
        self.assertEqual(_parse_rank("T-10"), 10)
        self.assertEqual(_parse_rank("T1"), 1)
        self.assertEqual(_parse_rank("10="), 10)
        self.assertEqual(_parse_rank("5↑"), 5)
        self.assertIsNone(_parse_rank("Rank"))
        self.assertIsNone(_parse_rank(""))

    def test_parse_points(self):
        self.assertEqual(_parse_points(["Player", "USA", "1,250"]), "1,250")
        self.assertEqual(_parse_points(["Player", "USA"]), "N/A")

    def test_parse_country(self):
        self.assertEqual(_parse_country(["Carlos Alcaraz", "ESP", "8,920"], "Carlos Alcaraz"), "ESP")
        self.assertEqual(_parse_country(["Unknown Player", "8,920"], "Unknown Player"), "N/A")


class TestParseRankings(unittest.TestCase):
    def test_standard_and_tied_ranks(self):
        rankings = parse_rankings(SAMPLE_TABLE_HTML, limit=10)
        self.assertEqual(
            [(entry.rank, entry.player, entry.country, entry.points) for entry in rankings],
            [
                (1, "Jannik Sinner", "ITA", "11,830"),
                (2, "Carlos Alcaraz", "ESP", "8,920"),
                (10, "Tied Player", "USA", "1,200"),
                (1, "Also Tied", "FRA", "1,100"),
            ],
        )

    def test_empty_and_unexpected_rows_do_not_crash(self):
        rankings = parse_rankings(SAMPLE_TABLE_HTML, limit=10)
        self.assertTrue(all(isinstance(entry, RankingEntry) for entry in rankings))
        self.assertGreaterEqual(len(rankings), 2)

    def test_limit_is_respected(self):
        rankings = parse_rankings(SAMPLE_TABLE_HTML, limit=2)
        self.assertEqual(len(rankings), 2)


class TestRenderDashboard(unittest.TestCase):
    def test_search_query_is_escaped(self):
        payload = "<script>alert('xss')</script>"
        html_out = render_dashboard([], search_query=payload)
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", html_out)

    def test_search_query_is_escaped_in_input_value(self):
        payload = '"><script>alert(1)</script>'
        html_out = render_dashboard([], search_query=payload)
        self.assertNotIn('value=""><script>', html_out)
        self.assertIn("&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;", html_out)

    def test_player_attributes_are_escaped(self):
        rankings = [
            RankingEntry(
                rank=1,
                player="<b>Hacker</b>",
                country='U"S',
                points="1<script>",
            )
        ]
        html_out = render_dashboard(rankings)
        self.assertNotIn("<b>Hacker</b>", html_out)
        self.assertIn("&lt;b&gt;Hacker&lt;/b&gt;", html_out)
        self.assertIn("U&quot;S", html_out)
        self.assertIn("1&lt;script&gt;", html_out)

    def test_error_message_is_escaped(self):
        html_out = render_dashboard([], error_message="<em>boom</em>")
        self.assertIn("&lt;em&gt;boom&lt;/em&gt;", html_out)
        self.assertNotIn("<em>boom</em>", html_out)


class TestParseLimitParam(unittest.TestCase):
    def test_valid_limit(self):
        self.assertEqual(parse_limit_param("15", 20), 15)

    def test_invalid_limit_falls_back(self):
        self.assertEqual(parse_limit_param("abc", 20), 20)
        self.assertEqual(parse_limit_param(None, 20), 20)

    def test_limit_is_clamped(self):
        self.assertEqual(parse_limit_param("-5", 20), 1)
        self.assertEqual(parse_limit_param("1000", 20), 100)


class TestDashboardHandler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        DashboardHandler.limit = 20
        cls.server = HTTPServer(("127.0.0.1", 0), DashboardHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.sample = [
            RankingEntry(rank=1, player="Jannik Sinner", country="ITA", points="11,830"),
            RankingEntry(rank=2, player="Carlos Alcaraz", country="ESP", points="8,920"),
        ]

    def _get(self, path: str):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            body = response.read().decode("utf-8")
            return response.status, body
        finally:
            conn.close()

    def test_default_request_returns_200(self):
        with patch("atp_dashboard.fetch_rankings", return_value=self.sample) as mocked:
            status, body = self._get("/")
        self.assertEqual(status, 200)
        mocked.assert_called_once_with(limit=20, force_refresh=False)
        self.assertIn("Jannik Sinner", body)

    def test_limit_query_param_is_parsed(self):
        with patch("atp_dashboard.fetch_rankings", return_value=self.sample) as mocked:
            status, _ = self._get("/?limit=5")
        self.assertEqual(status, 200)
        mocked.assert_called_once_with(limit=5, force_refresh=False)

    def test_invalid_limit_falls_back_to_default(self):
        with patch("atp_dashboard.fetch_rankings", return_value=self.sample) as mocked:
            status, _ = self._get("/?limit=abc")
        self.assertEqual(status, 200)
        mocked.assert_called_once_with(limit=20, force_refresh=False)

    def test_search_query_filters_results(self):
        with patch("atp_dashboard.fetch_rankings", return_value=self.sample):
            status, body = self._get("/?search=Alcaraz")
        self.assertEqual(status, 200)
        self.assertIn("Carlos Alcaraz", body)
        self.assertNotIn("Jannik Sinner", body)
        self.assertIn("Results matching:", body)

    def test_refresh_query_forces_refresh(self):
        with patch("atp_dashboard.fetch_rankings", return_value=self.sample) as mocked:
            status, _ = self._get("/?refresh=1")
        self.assertEqual(status, 200)
        mocked.assert_called_once_with(limit=20, force_refresh=True)

    def test_country_filter_returns_matching_players(self):
        with patch("atp_dashboard.fetch_rankings", return_value=self.sample):
            status, body = self._get("/?country=ESP")
        self.assertEqual(status, 200)
        self.assertIn("Carlos Alcaraz", body)
        self.assertNotIn("Jannik Sinner", body)
        self.assertIn('value="ESP" selected', body)

    def test_country_filter_is_case_insensitive(self):
        with patch("atp_dashboard.fetch_rankings", return_value=self.sample):
            status, body = self._get("/?country=ita")
        self.assertEqual(status, 200)
        self.assertIn("Jannik Sinner", body)
        self.assertNotIn("Carlos Alcaraz", body)

    def test_country_and_search_filters_combine(self):
        with patch("atp_dashboard.fetch_rankings", return_value=self.sample):
            status, body = self._get("/?country=ESP&search=Sinner")
        self.assertEqual(status, 200)
        self.assertIn("No rankings found matching criteria.", body)

    def test_unknown_country_returns_empty_state(self):
        with patch("atp_dashboard.fetch_rankings", return_value=self.sample):
            status, body = self._get("/?country=ZZZ")
        self.assertEqual(status, 200)
        self.assertIn("No rankings found matching criteria.", body)


class TestCountryFilterRender(unittest.TestCase):
    def test_dashboard_includes_country_dropdown(self):
        rankings = [
            RankingEntry(rank=1, player="Jannik Sinner", country="ITA", points="11,830"),
            RankingEntry(rank=2, player="Carlos Alcaraz", country="ESP", points="8,920"),
        ]
        html_out = render_dashboard(
            rankings,
            country_filter="ESP",
            available_countries=["ESP", "ITA"],
        )
        self.assertIn('<select name="country">', html_out)
        self.assertIn('value="ESP" selected', html_out)
        self.assertIn('value="ITA"', html_out)


class TestRunServerShutdown(unittest.TestCase):
    def test_keyboard_interrupt_closes_server_cleanly(self):
        from atp_dashboard import run_server
        from io import StringIO
        from unittest.mock import MagicMock

        server = MagicMock()
        server.serve_forever.side_effect = KeyboardInterrupt

        with patch("atp_dashboard.HTTPServer", return_value=server), patch(
            "sys.stdout", new_callable=StringIO
        ) as stdout:
            run_server("127.0.0.1", 8000, 20)

        server.server_close.assert_called_once()
        self.assertIn("Server stopped.", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
