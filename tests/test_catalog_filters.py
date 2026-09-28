import os
import unittest
from collections import Counter, defaultdict
from html.parser import HTMLParser


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
CATALOG_PATH = os.path.join(ROOT_DIR, "docs", "index.html")


class CatalogParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.article_count = 0
        self.tagged_articles = 0
        self.tbody_depth = 0
        self.file_row_count = 0
        self.tagged_file_rows = 0
        self.items = []
        self.filters = defaultdict(set)
        self.local_references = []
        self.filter_section_count = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "tbody":
            self.tbody_depth += 1
        if tag == "article":
            self.article_count += 1
            if "data-catalog-item" in values:
                self.tagged_articles += 1
        if tag == "tr" and self.tbody_depth:
            self.file_row_count += 1
            if "data-catalog-item" in values:
                self.tagged_file_rows += 1
        if "data-catalog-item" in values:
            self.items.append((tag, values))
        if "data-filter-section" in values:
            self.filter_section_count += 1
        classes = set((values.get("class") or "").split())
        if "filter-button" in classes:
            self.filters[values.get("data-filter-group")].add(
                values.get("data-filter-value")
            )
        for key in ("href", "src"):
            reference = values.get(key)
            if reference and not reference.startswith(
                ("http:", "https:", "#", "mailto:", "data:")
            ):
                self.local_references.append(reference)

    def handle_endtag(self, tag):
        if tag == "tbody":
            self.tbody_depth -= 1


class CatalogFilterContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CATALOG_PATH, "r", encoding="utf-8") as handle:
            cls.html = handle.read()
        cls.parser = CatalogParser()
        cls.parser.feed(cls.html)

    def test_every_card_and_printable_file_row_has_filter_metadata(self):
        self.assertEqual(33, self.parser.article_count)
        self.assertEqual(self.parser.article_count, self.parser.tagged_articles)
        self.assertEqual(29, self.parser.file_row_count)
        self.assertEqual(self.parser.file_row_count, self.parser.tagged_file_rows)
        self.assertEqual(5, self.parser.filter_section_count)

        allowed_platforms = {"h2d", "x1c"}
        allowed_categories = {"challenge", "platform", "walls"}
        for tag, values in self.parser.items:
            platforms = set((values.get("data-platform") or "").split())
            categories = set((values.get("data-category") or "").split())
            self.assertTrue(platforms, "%s item has no platform metadata" % tag)
            self.assertTrue(categories, "%s item has no category metadata" % tag)
            self.assertLessEqual(platforms, allowed_platforms)
            self.assertLessEqual(categories, allowed_categories)

    def test_filter_controls_are_complete_and_accessible(self):
        self.assertEqual({"all", "h2d", "x1c"}, self.parser.filters["platform"])
        self.assertEqual(
            {"all", "challenge", "platform", "walls"},
            self.parser.filters["category"],
        )
        required_ids = {
            "catalog-search",
            "catalog-reset",
            "catalog-result-count",
            "catalog-no-results",
            "catalog-filter-help",
        }
        self.assertLessEqual(required_ids, set(self.parser.ids))
        self.assertIn("aria-live=\"polite\"", self.html)
        self.assertIn("aria-pressed=\"true\"", self.html)

    def test_ids_are_unique_and_local_assets_resolve(self):
        duplicate_ids = [
            value for value, count in Counter(self.parser.ids).items() if count > 1
        ]
        self.assertEqual([], duplicate_ids)
        catalog_dir = os.path.dirname(CATALOG_PATH)
        missing = []
        for reference in self.parser.local_references:
            path = os.path.abspath(os.path.join(catalog_dir, reference))
            if not os.path.exists(path):
                missing.append(reference)
        self.assertEqual([], missing)

    def test_no_javascript_fallback_keeps_the_catalog_visible(self):
        self.assertIn(".catalog-controls {\n      display: none;", self.html)
        self.assertIn(".js .catalog-controls { display: block; }", self.html)
        self.assertIn("document.documentElement.classList.add('js')", self.html)


if __name__ == "__main__":
    unittest.main()
