import unittest
from unittest.mock import patch

from coles_monitor.changes import compare, consolidate_events, visible_products
from coles_monitor.availability import (apply_availability_consensus,
                                        availability_backup_required)
from coles_monitor.catalog import CombinedCategoryScraper
from coles_monitor.matcher import (category_group, is_allowed_product, is_wanted_name,
                                   keyword_group, split_name_size)
from coles_monitor.reporting import (email_visible_events, render_baseline_html,
                                     render_html, write_workbook)
from openpyxl import load_workbook
from pathlib import Path
from tempfile import TemporaryDirectory
from run_monitor import scrape_with_fallback
from coles_monitor.scraper import ColesScraper
from coles_monitor.woolworths import WoolworthsScraper


class MatcherTests(unittest.TestCase):
    def test_exact_rules(self):
        self.assertTrue(is_wanted_name("Brand Pasta Bake Sauce"))
        self.assertTrue(is_wanted_name("Brand Tomato Paste"))
        self.assertTrue(is_wanted_name("Brand Passata"))
        self.assertTrue(is_wanted_name("Brand Pesto Genovese"))
        self.assertFalse(is_wanted_name("Tomato Sauce"))
        self.assertFalse(is_wanted_name("Pasta Penne"))

    def test_title_and_brand_exclusions(self):
        self.assertFalse(is_allowed_product("Fresh Tomato Pasta Sauce", "Example"))
        self.assertFalse(is_allowed_product("Tomato Pasta Sauce", "Continental"))
        self.assertFalse(is_allowed_product("Tomato Paste", "Sirena"))
        self.assertTrue(is_allowed_product("Tomato Paste", "Leggo's"))
        self.assertFalse(is_allowed_product("Basil Pesto", "Rana"))
        self.assertFalse(is_allowed_product("Manual Food Chopper Pesto", "Example"))
        self.assertFalse(is_allowed_product("Pesto Throw Rug", "Example"))
        self.assertFalse(is_allowed_product("San Remo Tomato Paste", "Example"))
        self.assertFalse(is_allowed_product("My Muscle Chef Pasta Sauce", "Example"))

    def test_name_size(self):
        self.assertEqual(split_name_size("Brand Pesto | 190g"), ("Brand Pesto", "190g"))

    def test_exclusive_keyword_group_priority(self):
        self.assertEqual(keyword_group("Tomato Paste Passata"), "Tomato Paste")
        self.assertEqual(keyword_group("Passata Pasta Sauce"), "Pasta Sauce")
        self.assertEqual(keyword_group("Basil Pesto"), "Pesto")
        self.assertIsNone(keyword_group("Tomato Sauce"))

    def test_retailer_taxonomy_classifies_stir_through_as_pasta_sauce(self):
        name = "Leggo's Stir Through Sauce Roasted Vegetables"
        taxonomy = 'PASTA SAUCE & CHEESE ["Italian", "Pizza & Pasta Sauce"]'
        self.assertEqual(category_group(name, taxonomy), "Pasta Sauce")
        self.assertTrue(is_allowed_product(name, "Leggo's", taxonomy))


class ReportingTests(unittest.TestCase):
    def test_retailer_and_keyword_sections_do_not_duplicate_skus(self):
        current = {
            "coles:1": {"retailer": "Coles", "brand": "A", "name": "Tomato Paste Passata",
                        "price": 2.0, "size": "100g", "image_url": "", "product_url": "https://example/1"},
            "woolworths:2": {"retailer": "Woolworths", "brand": "B", "name": "Pasta Sauce",
                             "price": 3.0, "size": "500g", "image_url": "", "product_url": "https://example/2"},
            "coles:unchanged": {"retailer": "Coles", "brand": "C", "name": "Basil Pesto",
                                "price": 4.0, "size": "190g", "image_url": "",
                                "product_url": "https://example/3"},
        }
        changed = {key: value for key, value in current.items() if key != "coles:unchanged"}
        report_events = compare({}, changed, "2026-01-01T00:00:00+00:00")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            write_workbook(path, report_events, current, report_events=report_events)
            workbook = load_workbook(path)
            self.assertEqual(workbook.sheetnames, ["Coles", "Woolworths", "Change History"])
            self.assertNotIn("Image URL", [cell.value for cell in workbook["Coles"][4]])
            report_headers = [cell.value for cell in workbook["Coles"][4]]
            self.assertEqual(report_headers[2:5], ["Product", "Size", "Change Summary"])
            self.assertNotIn("Promotional Price (AUD)", report_headers)
            self.assertNotIn("Online Only", report_headers)
            history_headers = [cell.value for cell in workbook["Change History"][1]]
            self.assertNotIn("Before", history_headers)
            self.assertNotIn("After", history_headers)
            self.assertNotIn("Image URL", history_headers)
            self.assertNotIn("Promotional Price (AUD)", history_headers)
            self.assertNotIn("Online Only", history_headers)
            ids = []
            for sheet_name in ("Coles", "Woolworths"):
                ids.extend(cell.value for cell in workbook[sheet_name]["A"]
                           if isinstance(cell.value, str) and ":" in cell.value)
            self.assertCountEqual(ids, changed.keys())
            self.assertNotIn("coles:unchanged", ids)
        html = render_baseline_html(current)
        self.assertIn("<h2>Coles</h2>", html)
        self.assertIn("<h2>Woolworths</h2>", html)
        self.assertEqual(html.count(">Tomato Paste Passata</a>"), 1)
        self.assertNotIn("<th>Promotional Price</th>", html)
        self.assertNotIn("<th>Online Only</th>", html)
        self.assertIn("<th>Product</th><th>Size</th>", html)

    def test_email_orders_each_category_by_brand_and_marks_online_promotion(self):
        products = {
            "woolworths:1": {"retailer": "Woolworths", "brand": "Zulu",
                              "name": "Zulu Pasta Sauce", "size": "500g", "price": 4.0,
                              "product_url": "https://example/1", "availability_label": "Available"},
            "woolworths:2": {"retailer": "Woolworths", "brand": "Alpha",
                              "name": "Alpha Pasta Sauce", "size": "500g", "price": 3.0,
                              "original_price": 4.0, "promotional_price": 3.0,
                              "discount_percent": 0.25, "online_only": True,
                              "product_url": "https://example/2", "availability_label": "Available"},
        }
        html = render_baseline_html(products)
        self.assertLess(html.index("Alpha Pasta Sauce"), html.index("Zulu Pasta Sauce"))
        self.assertIn("$3.00 (Online only promotion)", html)

    def test_test_baseline_is_clearly_labelled(self):
        html = render_baseline_html({}, test=True)
        self.assertIn("Live test baseline", html)

    def test_retailer_specific_seafood_groups_and_email_title(self):
        groups = {
            "Coles": ("Fish & Seafood",),
            "Woolworths": ("Canned Tuna", "Canned Salmon & Seafood"),
        }
        products = {
            "coles:1": {"product_id": "coles:1", "retailer": "Coles",
                        "brand": "A", "name": "A Sardines", "size": "100g",
                        "price": 2.0, "category_group": "Fish & Seafood",
                        "product_url": "https://example/1"},
            "woolworths:2": {"product_id": "woolworths:2", "retailer": "Woolworths",
                             "brand": "B", "name": "B Tuna", "size": "95g",
                             "price": 3.0, "category_group": "Canned Tuna",
                             "product_url": "https://example/2"},
        }
        html = render_baseline_html(products, groups=groups,
                                    report_name="Shelf Seafood")
        self.assertIn("Shelf Seafood", html)
        self.assertIn("<h3>Fish &amp; Seafood</h3>", html)
        self.assertIn("<h3>Canned Tuna</h3>", html)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "seafood.xlsx"
            write_workbook(path, [], products, report_events=list(products.values()),
                           groups=groups)
            workbook = load_workbook(path)
            self.assertEqual(workbook.sheetnames,
                             ["Coles", "Woolworths", "Change History"])
            self.assertIn("ColesFishSeafoodTable", workbook["Coles"].tables)
            with patch("coles_monitor.reporting.smtplib.SMTP_SSL") as smtp:
                from coles_monitor.reporting import send_email
                send_email("from@example.com", "to@example.com", "password", [], path,
                           baseline=products, groups=groups,
                           report_name="Shelf Seafood",
                           attachment_filename="shelf-seafood.xlsx")
                message = smtp.return_value.__enter__.return_value.send_message.call_args[0][0]
                self.assertEqual(
                    message["Subject"],
                    "Coles & Woolworths Shelf Seafood product baseline - 2 products",
                )
                self.assertEqual(next(message.iter_attachments()).get_filename(),
                                 "shelf-seafood.xlsx")

    def test_failed_retailer_is_not_described_as_no_changes(self):
        html = render_html([], failures=["Coles: ScrapeError: blocked"])
        coles_section = html.split("<h2>Coles</h2>", 1)[1].split("<h2>Woolworths</h2>", 1)[0]
        self.assertIn("Refresh unavailable", coles_section)
        self.assertNotIn("No changes", coles_section)


class ScrapeFallbackTests(unittest.TestCase):
    def test_failed_retailer_retains_verified_snapshot(self):
        class FailedScraper:
            def scrape(self, queries):
                raise RuntimeError("blocked")

        class WorkingScraper:
            def scrape(self, queries):
                return {"woolworths:2": {"retailer": "Woolworths", "name": "New Passata"}}

        previous = {
            "coles:1": {"retailer": "Coles", "name": "Verified Tomato Paste"},
            "woolworths:1": {"retailer": "Woolworths", "name": "Old Passata"},
        }
        current, failures = scrape_with_fallback(
            (("Coles", FailedScraper()), ("Woolworths", WorkingScraper())), [], previous
        )
        self.assertIn("coles:1", current)
        self.assertNotIn("woolworths:1", current)
        self.assertIn("woolworths:2", current)
        self.assertEqual(len(failures), 1)


class LocationTests(unittest.TestCase):
    def test_cheltenham_location_is_retained(self):
        location = {"suburb": "Cheltenham", "postcode": "3192", "state": "VIC",
                    "context_mode": "delivery"}
        scraper = ColesScraper(location=location)
        self.assertEqual(scraper.location, location)

    def test_coles_resolves_exact_cheltenham_fulfilment_store(self):
        scraper = ColesScraper(location={
            "suburb": "Cheltenham", "postcode": "3192", "state": "VIC"
        })

        def fake_api_get(path, params=None):
            if path.endswith("suggestions"):
                return {"localities": [{
                    "latitude": -37.96451, "longitude": 145.055873,
                    "postcode": "3192", "suburb": "Cheltenham", "state": "VIC",
                }]}
            return {"locations": [{
                "postcode": "3192", "distance": {"measurement": 0.77},
                "fulfillmentStore": {"storeId": "669"},
            }]}

        scraper._api_get = fake_api_get
        self.assertEqual(scraper._resolve_store_id(), "669")

    def test_coles_uses_nearest_store_when_locality_crosses_postcode_boundary(self):
        scraper = ColesScraper(location={
            "suburb": "Broadway", "postcode": "2007", "state": "NSW"
        })
        def api_get(path, params):
            if path.endswith("suggestions"):
                return {"localities": [{
                    "postcode": "2007", "suburb": "Broadway", "state": "NSW",
                    "latitude": -33.884366, "longitude": 151.196502,
                }]}
            return {"locations": [{
                "postcode": "2037", "distance": {"measurement": 0.24},
                "fulfillmentStore": {"storeId": "839"},
            }]}
        scraper._api_get = api_get
        self.assertEqual(scraper._resolve_store_id(), "839")

    def test_coles_public_api_paginates_by_returned_page_size(self):
        scraper = ColesScraper(delay=0, max_pages=3, location={
            "suburb": "Cheltenham", "postcode": "3192", "state": "VIC"
        })
        scraper._resolve_store_id = lambda: "669"
        scraper._resolve_category = lambda store_id: {
            "id": "9373", "level": 2, "name": "Sauces"
        }
        starts = []

        def fake_api_get(path, params=None):
            starts.append(params["start"])
            page = params["start"]
            offset = page * 20
            count = 20 if page == 0 else 1
            return {
                "noOfResults": 21, "pageSize": 20,
                "results": [{
                    "id": offset + index + 1,
                    "name": f"Example Passata {offset + index + 1}",
                    "availability": True, "pricing": {"now": 3.0},
                } for index in range(count)],
            }

        scraper._api_get = fake_api_get
        self.assertEqual(len(scraper._browse_public_api()), 21)
        self.assertEqual(starts, [0, 1])

    def test_coles_multibuy_text_is_captured(self):
        _, product = ColesScraper._product({
            "id": "1", "name": "Example Passata", "availability": True,
            "pricing": {"now": 4.6, "specialType": "MULTI_SAVE",
                        "offerDescription": "Pick any 2 for $7",
                        "multiBuyPromotion": {"minQuantity": 2, "reward": 3.5}},
        })
        self.assertEqual(product["original_price"], 4.6)
        self.assertEqual(product["promotional_price"], "Pick any 2 for $7")
        self.assertEqual(product["discount_percent"], 0.2391)

    def test_coles_multibuy_outside_pricing_is_captured(self):
        _, product = ColesScraper._product({
            "id": "2", "name": "Example Pasta Sauce", "availability": True,
            "pricing": {"now": 4.5, "specialType": "MULTI_SAVE"},
            "promotions": [{"offerDescription": "Any 2 for $7"}],
        })
        self.assertEqual(product["original_price"], 4.5)
        self.assertEqual(product["promotional_price"], "2 for $7")
        self.assertEqual(product["discount_percent"], 0.2222)

    def test_coles_multibuy_badge_is_captured(self):
        _, product = ColesScraper._product({
            "id": "3", "name": "Example Pesto", "availability": True,
            "pricing": {"now": 6.0},
            "badges": {"promotion": {"PromotionText": "Buy 2 for $10.00"}},
        })
        self.assertEqual(product["promotional_price"], "2 for $10.00")
        self.assertEqual(product["discount_percent"], 0.1667)

    def test_coles_ordered_images_are_retained(self):
        _, product = ColesScraper._product({
            "id": "4", "name": "Example Passata", "availability": True,
            "pricing": {"now": 3.0},
            "imageUris": [{"uri": "/4/4.jpg"}, {"uri": "/4/4_2.jpg"}],
        })
        self.assertEqual(product["image_urls"], [
            "https://cdn.productimages.coles.com.au/productimages/4/4.jpg",
            "https://cdn.productimages.coles.com.au/productimages/4/4_2.jpg",
        ])

    def test_coles_taxonomy_classifies_stir_through_as_pasta_sauce(self):
        _, product = ColesScraper._product({
            "id": "5", "name": "Roasted Vegetables Stir Through Sauce",
            "brand": "Leggo's", "availability": True, "pricing": {"now": 4.6},
            "merchandiseHeir": {
                "category": "MEAL BASES", "subCategory": "PASTA SAUCE",
                "className": "CHUNKY",
            },
            "onlineHeirs": [{"aisle": "Pizza & Pasta"}],
        })
        self.assertEqual(product["category_group"], "Pasta Sauce")


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

    def test_woolworths_taxonomy_and_ordered_images_are_retained(self):
        _, product = WoolworthsScraper._product({
            "Stockcode": 957033,
            "Name": "Leggo's Stir Through Tomato Garlic & Caramelised Onion Sauce",
            "Brand": "Leggo's", "Price": 4.3, "PackageSize": "350g",
            "MediumImageFile": "https://cdn.example/medium/957033.jpg",
            "AdditionalAttributes": {
                "sapsubcategoryname": "PASTA SAUCE & CHEESE",
                "sapsegmentname": "PASTA SAUCE STIR THRU",
                "productimages": "957033.jpg,957033_2.jpg",
            },
        })
        self.assertEqual(product["category_group"], "Pasta Sauce")
        self.assertEqual(product["image_urls"], [
            "https://cdn.example/medium/957033.jpg",
            "https://cdn.example/medium/957033_2.jpg",
        ])

    def test_seafood_category_mode_does_not_apply_sauce_brand_exclusions(self):
        scraper = WoolworthsScraper(report_group="Canned Tuna")
        product_id, product = scraper._product({
            "Stockcode": 123, "Name": "Sirena Tuna In Oil 95g", "Brand": "Sirena",
            "PackageSize": "95g", "Price": 2.5, "IsAvailable": True,
        })
        self.assertEqual(product_id, "woolworths:123")
        self.assertTrue(scraper._include_product(product))
        self.assertEqual(product["category_group"], "Canned Tuna")

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

    def test_woolworths_multibuy_text_is_captured(self):
        _, product = WoolworthsScraper._product({
            "Stockcode": 5, "Name": "Example Passata", "Price": 4.0,
            "PromotionDescription": "2 for $6", "IsAvailable": True, "IsInStock": True,
        })
        self.assertEqual(product["original_price"], 4.0)
        self.assertEqual(product["promotional_price"], "2 for $6")
        self.assertEqual(product["discount_percent"], 0.25)
        old = {"woolworths:5": {**product, "promotional_price": None,
                                 "original_price": None, "discount_percent": None}}
        events = compare(old, {"woolworths:5": product}, "now")
        self.assertEqual(events[0]["change_type"], "Promotion")
        self.assertIn("2 for $6", render_html(events))

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


class CombinedCategoryScraperTests(unittest.TestCase):
    def test_combines_category_pages_without_duplicate_skus(self):
        class FakeScraper:
            def __init__(self, group, products):
                self.report_group = group
                self.category_url = "https://example.test/" + group
                self.products = products

            def scrape(self, queries):
                return self.products

        first = FakeScraper("Canned Tuna", {
            "woolworths:1": {"name": "Tuna", "category_group": "Canned Tuna"},
        })
        second = FakeScraper("Canned Salmon & Seafood", {
            "woolworths:1": {"name": "Duplicate", "category_group": "Other"},
            "woolworths:2": {"name": "Salmon",
                             "category_group": "Canned Salmon & Seafood"},
        })
        combined = CombinedCategoryScraper((first, second))
        products = combined.scrape([])
        self.assertEqual(set(products), {"woolworths:1", "woolworths:2"})
        self.assertEqual(products["woolworths:1"]["name"], "Tuna")
        self.assertEqual(combined.last_category_counts,
                         {"Canned Tuna": 1, "Canned Salmon & Seafood": 2})


class OnlineOnlyChangeTests(unittest.TestCase):
    def test_status_change_is_reported(self):
        old = {"coles:1": {"name": "A Pesto", "price": 2.0, "size": "100g",
                           "image_url": "a", "online_only": False}}
        new = {"coles:1": {"retailer": "Coles", "name": "A Pesto", "price": 2.0,
                           "size": "100g", "image_url": "a", "online_only": True,
                           "product_url": "u"}}
        events = compare(old, new, "2026-01-01T00:00:00+00:00")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["change_type"], "Online only")
        self.assertTrue(events[0]["online_only"])


class EmailVisibilityTests(unittest.TestCase):
    def test_promotion_ending_is_retained_but_hidden_from_email(self):
        old = {"coles:1": {"retailer": "Coles", "name": "Example Passata",
                            "price": 3.0, "original_price": 4.0,
                            "promotional_price": 3.0, "discount_percent": 0.25,
                            "size": "700g", "image_url": "", "product_url": "u"}}
        new = {"coles:1": {**old["coles:1"], "price": 4.0,
                            "original_price": None, "promotional_price": None,
                            "discount_percent": None}}
        events = compare(old, new, "now")
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["promotion_ended"])
        self.assertEqual(email_visible_events(events), [])
        self.assertNotIn("Example Passata", render_html(events))


class AvailabilityLifecycleTests(unittest.TestCase):
    def test_temporary_unavailable_once_then_back_in_stock(self):
        temporary = {"1": {"retailer": "Woolworths", "name": "A Passata",
                            "availability_state": "temporary_unavailable",
                            "availability_label": "Temporarily unavailable",
                            "product_url": "u"}}
        first = compare({}, temporary, "now")
        self.assertEqual(first[0]["change_type"], "Unavailable")
        self.assertEqual(compare(temporary, temporary, "later"), [])
        self.assertEqual(visible_products({}, temporary), temporary)
        self.assertEqual(visible_products(temporary, temporary), {})
        available = {"1": {**temporary["1"], "availability_state": "in_stock",
                           "availability_label": "Available"}}
        back = compare(temporary, available, "later")
        self.assertEqual(back[0]["change_type"], "Restocked")
        self.assertEqual(visible_products(temporary, available), available)

    def test_consensus_out_of_stock_is_shown_once(self):
        out = {"1": {"name": "A Passata", "availability_state": "out_of_stock",
                      "availability_label": "No availability in both locations",
                      "product_url": "u"}}
        events = compare({}, out, "now")
        self.assertEqual(events[0]["change_type"], "No availability")
        self.assertEqual(visible_products({}, out), out)
        self.assertEqual(compare(out, out, "later"), [])
        self.assertEqual(visible_products(out, out), {})


class AvailabilityConsensusTests(unittest.TestCase):
    primary_location = {"suburb": "Cheltenham", "state": "VIC", "postcode": "3192"}
    backup_location = {"suburb": "Broadway", "state": "NSW", "postcode": "2007"}

    @staticmethod
    def product(state, label=None):
        return {"retailer": "Coles", "name": "A Passata",
                "availability_state": state,
                "availability_label": label or state,
                "product_url": "u"}

    def merge(self, primary_state, backup_state=None, old_state=None, legacy=False):
        primary = {"coles:1": self.product(primary_state)}
        backup = ({} if backup_state is None else
                  {"coles:1": self.product(backup_state)})
        previous = ({} if old_state is None else {"coles:1": {
            **self.product(old_state),
            **({} if legacy else {"availability_consensus": "locations_agree"}),
        }})
        return apply_availability_consensus(
            primary, backup, previous, self.primary_location, self.backup_location
        )["coles:1"]

    def test_primary_full_does_not_require_backup_without_prior_issue(self):
        primary = {"coles:1": self.product("in_stock")}
        self.assertFalse(availability_backup_required(primary, {}))
        merged = self.merge("in_stock")
        self.assertEqual(merged["availability_state"], "in_stock")
        self.assertEqual(merged["availability_consensus"], "primary_fully_available")

    def test_mixed_result_preserves_last_full_consensus(self):
        merged = self.merge("out_of_stock", "in_stock", "in_stock")
        self.assertEqual(merged["availability_state"], "in_stock")
        self.assertEqual(merged["availability_consensus"], "mixed_preserved")

    def test_mixed_result_does_not_report_partial_restock(self):
        merged = self.merge("in_stock", "out_of_stock", "out_of_stock")
        self.assertEqual(merged["availability_state"], "out_of_stock")
        self.assertEqual(merged["availability_consensus"], "mixed_preserved")

    def test_both_unavailable_records_consensus_issue(self):
        merged = self.merge("out_of_stock", "out_of_stock", "in_stock")
        self.assertEqual(merged["availability_state"], "out_of_stock")
        self.assertIn("Cheltenham VIC 3192 and Broadway NSW 2007",
                      merged["availability_label"])

    def test_both_full_records_consensus_restock(self):
        primary = {"coles:1": self.product("in_stock")}
        previous = {"coles:1": self.product("out_of_stock")}
        self.assertTrue(availability_backup_required(primary, previous))
        merged = self.merge("in_stock", "in_stock", "out_of_stock")
        self.assertEqual(merged["availability_state"], "in_stock")
        self.assertIn("Available in", merged["availability_label"])

    def test_different_issues_do_not_replace_previous_consensus(self):
        merged = self.merge("temporary_unavailable", "out_of_stock", "in_stock")
        self.assertEqual(merged["availability_state"], "in_stock")

    def test_missing_backup_result_is_not_treated_as_unavailable(self):
        merged = self.merge("out_of_stock", None, "in_stock")
        self.assertEqual(merged["availability_state"], "in_stock")
        self.assertEqual(
            merged["availability_locations"]["Broadway NSW 2007"]["state"],
            "unknown",
        )

    def test_legacy_single_location_issue_does_not_become_consensus(self):
        merged = self.merge("out_of_stock", "in_stock", "out_of_stock", legacy=True)
        self.assertEqual(merged["availability_state"], "in_stock")
        self.assertTrue(merged["availability_consensus_migration"])

    def test_consensus_migration_suppresses_false_restock_but_keeps_price_change(self):
        old = {"1": {**self.product("out_of_stock"), "price": 4.0,
                     "size": "700g", "image_url": "a"}}
        new = {"1": {**self.product("in_stock"), "price": 5.0,
                     "size": "700g", "image_url": "a",
                     "availability_consensus_migration": True}}
        events = compare(old, new, "now")
        self.assertEqual(events[0]["change_type"], "RRP changed")


class ChangeTests(unittest.TestCase):
    def test_changed_fields_new_products_and_deduplication(self):
        old = {"1": {"name": "A Pesto", "price": 2.0, "size": "100g", "image_url": "a"}}
        new = {
            "1": {"name": "A Pesto", "price": 2.5, "size": "100g", "image_url": "b", "product_url": "u"},
            "2": {"name": "B Passata", "price": 3.0, "size": "700g", "image_url": "c", "product_url": "v"},
        }
        events = compare(old, new, "2026-01-01T00:00:00+00:00")
        self.assertEqual([e["change_type"] for e in events],
                         ["RRP changed; Image 1 changed", "New"])
        self.assertEqual(len({e["product_id"] for e in events}), len(events))
        self.assertEqual(compare(old, new, "later", [e["event_id"] for e in events]), [])

    def test_price_summaries_distinguish_rrp_and_promotion(self):
        base = {"name": "A Pesto", "size": "100g", "image_url": "a",
                "product_url": "u"}
        rrp = compare({"1": {**base, "price": 4.0}},
                      {"1": {**base, "price": 5.0}}, "now")
        self.assertEqual(rrp[0]["change_type"], "RRP changed")
        promotion = compare(
            {"1": {**base, "price": 4.0, "original_price": None,
                    "promotional_price": None, "discount_percent": None}},
            {"1": {**base, "price": 3.0, "original_price": 4.0,
                    "promotional_price": 3.0, "discount_percent": 0.25}}, "later")
        self.assertEqual(promotion[0]["change_type"], "Promotion")

    def test_image_change_names_the_positions(self):
        base = {"name": "A Pesto", "price": 4.0, "size": "100g", "product_url": "u"}
        old = {"1": {**base, "image_url": "a", "image_urls": ["a", "b", "c"]}}
        new = {"1": {**base, "image_url": "a", "image_urls": ["a", "d", "c", "e"]}}
        events = compare(old, new, "now")
        self.assertEqual(events[0]["change_type"], "Image 2 changed; Image 4 added")

    def test_legacy_history_is_consolidated_per_sku_and_observation(self):
        events = [
            {"observed_at": "now", "product_id": "coles:1", "change_type": "Price changed",
             "event_id": "a", "name": "Pesto"},
            {"observed_at": "now", "product_id": "coles:1", "change_type": "Image changed",
             "event_id": "b", "name": "Pesto"},
        ]
        consolidated = consolidate_events(events)
        self.assertEqual(len(consolidated), 1)
        self.assertEqual(consolidated[0]["change_type"], "Price; Image")


if __name__ == "__main__":
    unittest.main()
