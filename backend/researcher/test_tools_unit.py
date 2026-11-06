import unittest

from backend.researcher.tools import (
    _find_text_matches,
    _is_public_web_url,
    _parse_browser_search_results,
    browser_find,
    browser_search,
)


class BrowserSearchToolTests(unittest.TestCase):
    def test_browser_search_is_registered_with_expected_name(self):
        self.assertEqual(browser_search.name, "browser_search")

    def test_browser_find_is_registered_with_expected_name(self):
        self.assertEqual(browser_find.name, "browser_find")

    def test_find_text_matches_returns_compact_case_insensitive_excerpts(self):
        matches = _find_text_matches(
            "Revenue increased year over year. REVENUE growth remained durable.",
            "revenue",
        )

        self.assertEqual(len(matches), 1)
        self.assertIn("revenue", matches[0].casefold())

    def test_browser_find_rejects_private_and_non_web_urls(self):
        self.assertFalse(_is_public_web_url("http://169.254.169.254/latest/meta-data"))
        self.assertFalse(_is_public_web_url("file:///etc/passwd"))
        self.assertTrue(_is_public_web_url("https://www.sec.gov/filings"))

    def test_parse_results_strips_markup_and_honors_limit(self):
        payload = """<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>First result</title>
            <link>https://example.com/first</link>
            <description>&lt;b&gt;Current&lt;/b&gt; market details</description>
          </item>
          <item>
            <title>Second result</title>
            <link>https://example.com/second</link>
            <description>More details</description>
          </item>
        </channel></rss>
        """

        self.assertEqual(
            _parse_browser_search_results(payload, max_results=1),
            [
                {
                    "title": "First result",
                    "url": "https://example.com/first",
                    "snippet": "Current market details",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
