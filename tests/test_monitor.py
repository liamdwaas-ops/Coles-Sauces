import unittest

from coles_monitor.changes import compare, visible_products
from coles_monitor.matcher import is_allowed_product, is_wanted_name, keyword_group, split_name_size
from coles_monitor.reporting import render_baseline_html, write_workbook
from openpyxl import load_workbook
from pathlib import Path
from tempfile import TemporaryDirectory
from coles_monitor.scraper import ColesScraper
from coles_monitor.woolworths import WoolworthsScraper


class MatcherTests(unittest.TestCase):
    def test_exact_rules(self):
        self.assertTrue(is_wanted_name("Brand Pasta Bake Sauce"))
        self.assertTrue(is_wanted_name("Brand Tomato Paste"))
        self.assertTrue(is_wanted_name("Brand Passata"))
        self.assertFalse(is_wanted_name("Brand Pesto Genovese"))
        self.assertFalse(is_wanted_name("Tomato Sauce"))
        self.assertFalse(is_wanted_name("Pasta Penne"))

    def test_title_and_brand_exclusions(self):
        self.assertFalse(is_allowed_product("Fresh Tomato Pasta Sauce", "Example"))
        self.assertFalse(is_allowed_product("Tomato Pasta Sauce", "Continental"))
        self.assertFalse(is_allowed_product("Tomato Paste", "Sirena"))
        self.assertTrue(is_allowed_product("Tomato Paste", "Leggo's"))

    def test_name_size(self):
        self.assertEqual(split_name_size("Brand Pesto | 190g"), ("Brand Pesto", "190g"))

    def test_exclusive_keyword_group_priority(self):
        self.assertEqual(keyword_group("Tomato Paste Passata"), "Tomato Paste")
        self.assertEqual(keyword_group("Passata Pasta Sauce"), "Pasta Sauce")
        self.assertIsNone(keyword_group("Tomato Sauce"))


class ReportingTests(unittest.TestCase):
    def test_retailer_and_keyword_sections_do_not_duplicate_skus(self):
        current = {
            "coles:1": {"retailer": "Coles", "brand": "A", "name": "Tomato Paste Passata",
                        "price": 2.0, "size": "100g", "image_url": "", "product_url": "https://example/1"},
            "woolworths:2": {"retailer": "Woolworths", "brand": "B", "name": "Pasta Sauce",
                             "price": 3.0, "size": "500g", "image_url": "", "product_url": "https://example/2"},
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            write_workbook(path, [], current)
            workbook = load_workbook(path)
            self.assertEqual(workbook.sheetnames, ["Coles", "Woolworths", "Change History"])
            ids = []
            for sheet_name in ("Coles", "Woolworths"):
                ids.extend(cell.value for cell in workbook[sheet_name]["A"]
                           if isinstance(cell.value, str) and ":" in cell.value)
            self.assertCountEqual(ids, current.keys())
        html = render_baseline_html(current)
        self.assertIn("<h2>Coles</h2>", html)
        self.assertIn("<h2>Woolworths</h2>", html)
        self.assertEqual(html.count(">Tomato Paste Passata</a>"), 1)


class LocationTests(unittest.TestCase):
    def test_cheltenham_location_is_retained(self):
        location = {"suburb": "Cheltenham", "postcode": "3192", "state": "VIC",
                    "context_mode": "delivery"}
        scraper = ColesScraper(location=location)
        self.assertEqual(scraper.location, location)


class WoolworthsTests(unittest.TestCase):
    def test_nested_search_response_mapping(self):
        payload = {"Products": [{"Products": [{
            "Stockcode": 502381,
            "Name": "Woolworths Passata 680g",
            "PackageSize": "680g",
            "Price": 2.25,
            "MediumImageFile": "https://cdn.example.test/502381.jpg",
            "UrlFriendlyName": "woolworths-passata"
        }]}]}
        products = WoolworthsScraper._find_products(payload)
        self.assertEqual(len(products), 1)
        product_id, product = WoolworthsScraper._product(products[0])
        self.assertEqual(product_id, "woolworths:502381")
        self.assertEqual(product["retailer"], "Woolworths")
        self.assertEqual(product["name"], "Woolworths Passata")
        self.assertEqual(product["size"], "680g")
        self.assertEqual(product["price"], 2.25)
        self.assertFalse(product["online_only"])

    def test_woolworths_online_only_flag(self):
        _, product = WoolworthsScraper._product({
            "Stockcode": 99, "Name": "Example Pesto 190g", "PackageSize": "190g",
            "Price": 4.0, "IsOnlineOnly": True
        })
        self.assertTrue(product["online_only"])

    def test_woolworths_promotion_fields_require_explicit_promo(self):
        _, promo = WoolworthsScraper._product({
            "Stockcode": 1, "Name": "Example Passata 700g", "PackageSize": "700g",
            "Brand": "Example", "Price": 3.0, "WasPrice": 4.0, "IsOnSpecial": True,
            "IsAvailable": True, "IsInStock": True
        })
        self.assertEqual(promo["original_price"], 4.0)
        self.assertEqual(promo["promotional_price"], 3.0)
        self.assertEqual(promo["discount_percent"], 0.25)
        _, not_promo = WoolworthsScraper._product({
            "Stockcode": 2, "Name": "Example Passata 700g", "PackageSize": "700g",
            "Brand": "Example", "Price": 3.0, "WasPrice": 4.0, "IsOnSpecial": False
        })
        self.assertIsNone(not_promo["original_price"])

    def test_woolworths_availability_mapping(self):
        _, temporary = WoolworthsScraper._product({
            "Stockcode": 3, "Name": "Example Passata 700g",
            "IsAvailable": False, "IsInStock": False
        })
        self.assertEqual(temporary["availability_state"], "temporary_unavailable")
        _, out = WoolworthsScraper._product({
            "Stockcode": 4, "Name": "Example Passata 700g",
            "IsAvailable": True, "IsInStock": False
        })
        self.assertEqual(out["availability_state"], "out_of_stock")


class OnlineOnlyChangeTests(unittest.TestCase):
    def test_status_change_is_reported(self):
        old = {"coles:1": {"name": "A Pesto", "price": 2.0, "size": "100g",
                           "image_url": "a", "online_only": False}}
        new = {"coles:1": {"retailer": "Coles", "name": "A Pesto", "price": 2.0,
                           "size": "100g", "image_url": "a", "online_only": True,
                           "product_url": "u"}}
        events = compare(old, new, "2026-01-01T00:00:00+00:00")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["change_type"], "Online Only status changed")
        self.assertTrue(events[0]["online_only"])


class AvailabilityLifecycleTests(unittest.TestCase):
    def test_temporary_unavailable_once_then_back_in_stock(self):
        temporary = {"1": {"retailer": "Woolworths", "name": "A Passata",
                            "availability_state": "temporary_unavailable",
                            "availability_label": "Temporarily unavailable",
                            "product_url": "u"}}
        first = compare({}, temporary, "now")
        self.assertEqual(first[0]["change_type"], "Temporarily unavailable")
        self.assertEqual(compare(temporary, temporary, "later"), [])
        self.assertEqual(visible_products({}, temporary), temporary)
        self.assertEqual(visible_products(temporary, temporary), {})
        available = {"1": {**temporary["1"], "availability_state": "in_stock",
                           "availability_label": "Available"}}
        back = compare(temporary, available, "later")
        self.assertEqual(back[0]["change_type"], "Back in stock")
        self.assertEqual(visible_products(temporary, available), available)

    def test_out_of_stock_is_hidden(self):
        out = {"1": {"name": "A Passata", "availability_state": "out_of_stock"}}
        self.assertEqual(compare({}, out, "now"), [])
        self.assertEqual(visible_products({}, out), {})


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
