import unittest

from atp_dashboard import RankingEntry, _parse_rank, parse_rankings, render_dashboard


class TestParseRank(unittest.TestCase):
    def test_plain_rank(self):
        self.assertEqual(_parse_rank("10"), 10)

    def test_tied_ranks(self):
        self.assertEqual(_parse_rank("T-10"), 10)
        self.assertEqual(_parse_rank("T1"), 1)
        self.assertEqual(_parse_rank("10="), 10)

    def test_rank_with_movement_marker(self):
        self.assertEqual(_parse_rank("5↑"), 5)

    def test_non_rank_returns_none(self):
        self.assertIsNone(_parse_rank("Rank"))
        self.assertIsNone(_parse_rank(""))


class TestParseRankings(unittest.TestCase):
    def test_empty_rows_are_skipped(self):
        html = """
        <table>
          <tr></tr>
          <tr><td></td></tr>
          <tr><td>T-2</td><td>Test Player</td><td>USA</td><td>1,000</td></tr>
        </table>
        """
        rankings = parse_rankings(html, limit=10)
        self.assertEqual(len(rankings), 1)
        self.assertEqual(rankings[0].rank, 2)
        self.assertEqual(rankings[0].player, "Test Player")

    def test_tied_rank_players_are_kept(self):
        html = """
        <table>
          <tr><td>1</td><td>Top Player</td><td>ESP</td><td>9,000</td></tr>
          <tr><td>T-10</td><td>Tied Player</td><td>USA</td><td>800</td></tr>
        </table>
        """
        rankings = parse_rankings(html, limit=10)
        self.assertEqual([entry.rank for entry in rankings], [1, 10])


class TestRenderDashboardXSS(unittest.TestCase):
    def test_search_query_is_escaped_in_banner(self):
        payload = "<script>alert('xss')</script>"
        html_out = render_dashboard([], search_query=payload)

        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", html_out)

    def test_search_query_is_escaped_in_input_value(self):
        payload = '"><script>alert(1)</script>'
        html_out = render_dashboard([], search_query=payload)

        self.assertNotIn('value=""><script>', html_out)
        self.assertIn("&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;", html_out)

    def test_normal_search_query(self):
        html_out = render_dashboard([], search_query="Alcaraz")
        self.assertIn("Results matching: <strong>Alcaraz</strong>", html_out)
        self.assertIn('value="Alcaraz"', html_out)


if __name__ == "__main__":
    unittest.main()
