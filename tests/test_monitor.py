import unittest

from coles_monitor.changes import compare
from coles_monitor.matcher import is_wanted_name, split_name_size
from coles_monitor.scraper import ColesScraper


class MatcherTests(unittest.TestCase):
    def test_exact_rules(self):
        self.assertTrue(is_wanted_name("Brand Pasta Bake Sauce"))
        self.assertTrue(is_wanted_name("Brand Tomato Paste"))
        self.assertTrue(is_wanted_name("Brand Pesto Genovese"))
        self.assertTrue(is_wanted_name("Brand Passata"))
        self.assertFalse(is_wanted_name("Tomato Sauce"))
        self.assertFalse(is_wanted_name("Pasta Penne"))

    def test_name_size(self):
        self.assertEqual(split_name_size("Brand Pesto | 190g"), ("Brand Pesto", "190g"))


class LocationTests(unittest.TestCase):
    def test_cheltenham_location_is_retained(self):
        location = {"suburb": "Cheltenham", "postcode": "3192", "state": "VIC",
                    "context_mode": "delivery"}
        scraper = ColesScraper(location=location)
        self.assertEqual(scraper.location, location)


class ChangeTests(unittest.TestCase):
    def test_changed_fields_new_products_and_deduplication(self):
        old = {"1": {"name": "A Pesto", "price": 2.0, "size": "100g", "image_url": "a"}}
        new = {
            "1": {"name": "A Pesto", "price": 2.5, "size": "100g", "image_url": "b", "product_url": "u"},
            "2": {"name": "B Passata", "price": 3.0, "size": "700g", "image_url": "c", "product_url": "v"},
        }
        events = compare(old, new, "2026-01-01T00:00:00+00:00")
        self.assertEqual([e["change_type"] for e in events], ["Price changed", "Image changed", "New product"])
        self.assertEqual(compare(old, new, "later", [e["event_id"] for e in events]), [])


if __name__ == "__main__":
    unittest.main()
