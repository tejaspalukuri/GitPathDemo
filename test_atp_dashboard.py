import unittest
from atp_dashboard import RankingEntry, render_dashboard


class TestRenderDashboardXSS(unittest.TestCase):
    def test_search_query_is_escaped_in_banner(self):
        payload = "<script>alert('xss')</script>"
        html_out = render_dashboard([], search_query=payload)

        # Raw payload should NOT be in the output
        self.assertNotIn("<script>", html_out)
        # Escaped string should be in the output
        self.assertIn("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", html_out)

    def test_search_query_is_escaped_in_input_value(self):
        payload = '"><script>alert(1)</script>'
        html_out = render_dashboard([], search_query=payload)

        # Ensure double quote is escaped so attribute cannot be broken out of
        self.assertNotIn('value=""><script>', html_out)
        self.assertIn('&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;', html_out)

    def test_normal_search_query(self):
        html_out = render_dashboard([], search_query="Alcaraz")
        self.assertIn("Results matching: <strong>Alcaraz</strong>", html_out)
        self.assertIn('value="Alcaraz"', html_out)


if __name__ == "__main__":
    unittest.main()
