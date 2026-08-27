import time
import os
from urllib.parse import quote_plus

from curl_cffi import requests
from curl_cffi.const import CurlHttpVersion

from .matcher import is_allowed_product, normalize, split_name_size
from .promotions import find_multibuy_text, multibuy_unit_price
from .scraper import ScrapeError, USER_AGENT


BASE_URL = "https://www.woolworths.com.au"
SEARCH_URL = BASE_URL + "/apis/ui/Search/products"


class WoolworthsScraper:
    def __init__(self, delay=1.0, max_pages=20, page_size=36, location=None):
        self.delay = delay
        self.max_pages = max_pages
        self.page_size = min(page_size, 36)
        self.location = location or {}
        proxy_url = os.getenv("RETAIL_PROXY_URL", "").strip()
        session_args = {"impersonate": "chrome"}
        if proxy_url:
            session_args["proxy"] = proxy_url
        self.session = requests.Session(**session_args)
        self.primed = False
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": BASE_URL,
        })

    @staticmethod
    def _find_products(payload):
        candidates = []
        stack = [payload]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                if (value.get("Stockcode") or value.get("StockCode")) and value.get("Name"):
                    candidates.append(value)
                else:
                    stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
        unique = {}
        for item in candidates:
            product_id = str(item.get("Stockcode") or item.get("StockCode"))
            unique[product_id] = item
        return list(unique.values())

    @staticmethod
    def _product(raw):
        product_id = str(raw.get("Stockcode") or raw.get("StockCode") or "").strip()
        name, size = split_name_size(
            raw.get("Name") or raw.get("DisplayName") or "",
            raw.get("PackageSize") or raw.get("PackageSizeDisplay") or "",
        )
        slug = normalize(raw.get("UrlFriendlyName") or raw.get("Url") or "")
        if slug.startswith("http"):
            product_url = slug
        elif slug.startswith("/"):
            product_url = BASE_URL + slug
        else:
            product_url = f"{BASE_URL}/shop/productdetails/{product_id}/{slug}" if slug else \
                f"{BASE_URL}/shop/productdetails/{product_id}"
        image = (raw.get("MediumImageFile") or raw.get("LargeImageFile") or
                 raw.get("SmallImageFile") or raw.get("ImageFile") or "")
        if image.startswith("//"):
            image = "https:" + image
        elif image.startswith("/"):
            image = BASE_URL + image
        price = raw.get("Price")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = normalize(price)
        was = raw.get("WasPrice")
        try:
            was = float(was) if was is not None else None
        except (TypeError, ValueError):
            was = None
        is_promo = bool(was and isinstance(price, (int, float)) and was > price and
                        (raw.get("IsOnSpecial") or raw.get("IsOnlineOnly")))
        multibuy_text = find_multibuy_text(raw)
        multibuy_price = multibuy_unit_price(multibuy_text)
        is_multibuy = bool(multibuy_text and isinstance(price, (int, float)))
        is_available = bool(raw.get("IsAvailable", True))
        is_in_stock = bool(raw.get("IsInStock", is_available))
        explicit_temporary = bool(raw.get("IsTemporarilyUnavailable"))
        if is_available and is_in_stock:
            availability_state = "in_stock"
            availability_label = "Available"
        elif explicit_temporary or (not is_available and not is_in_stock):
            availability_state = "temporary_unavailable"
            availability_label = "Temporarily unavailable"
        else:
            availability_state = "out_of_stock"
            availability_label = "Out of stock"
        return "woolworths:" + product_id, {
            "retailer": "Woolworths", "brand": normalize(raw.get("Brand")),
            "name": name, "price": price,
            "original_price": price if is_multibuy else (was if is_promo else None),
            "promotional_price": multibuy_text if is_multibuy else (price if is_promo else None),
            "discount_percent": (round((price - multibuy_price) / price, 4)
                                   if is_multibuy and multibuy_price is not None and price > multibuy_price
                                   else (round((was - price) / was, 4) if is_promo else None)),
            "availability_state": availability_state, "availability_label": availability_label,
            "size": size,
            "online_only": bool(raw.get("IsOnlineOnly")),
            "image_url": image, "product_url": product_url, "source": product_url,
        }

    def search(self, query):
        found = {}
        postcode = self.location.get("postcode", "")
        if not self.primed:
            try:
                self.session.get(
                    BASE_URL + "/shop/search/products?searchTerm=pesto", timeout=45
                ).raise_for_status()
                self.primed = True
            except requests.RequestsError as exc:
                raise ScrapeError(f"Woolworths session setup failed: {exc}") from exc
        for page in range(1, self.max_pages + 1):
            location_url = f"/shop/search/products?searchTerm={quote_plus(query)}"
            if postcode:
                location_url += f"&postcode={quote_plus(postcode)}"
            body = {
                "Filters": [], "IsSpecial": False, "Location": location_url,
                "PageNumber": page, "PageSize": self.page_size, "SearchTerm": query,
                "SortType": "TraderRelevance", "IsRegisteredRewardCardPromotion": False,
                "ExcludeSearchTypes": ["UntraceableV2"], "GpBoost": 0,
                "GroupEdmVariants": False,
            }
            if postcode:
                body["Postcode"] = postcode
            try:
                response = self.session.post(
                    SEARCH_URL, json=body, timeout=40,
                    http_version=CurlHttpVersion.V1_1,
                    headers={"Referer": BASE_URL + location_url,
                             "X-Requested-With": "XMLHttpRequest"},
                )
                response.raise_for_status()
            except requests.RequestsError as exc:
                raise ScrapeError(f"Woolworths search failed: {exc}") from exc
            if "json" not in response.headers.get("content-type", "").lower():
                raise ScrapeError("Woolworths returned a non-JSON response. No report was generated.")
            products = self._find_products(response.json())
            if not products:
                break
            for raw in products:
                product_id, product = self._product(raw)
                if (product_id != "woolworths:" and
                        is_allowed_product(product["name"], product["brand"])):
                    found[product_id] = product
            if len(products) < self.page_size:
                break
            time.sleep(self.delay)
        return found

    def scrape(self, queries):
        products = {}
        for index, query in enumerate(queries):
            products.update(self.search(query))
            if index + 1 < len(queries):
                time.sleep(self.delay)
        if not products:
            raise ScrapeError("Woolworths returned no matching products. Snapshot was not replaced.")
        missing = [pid for pid, p in products.items() if not p["name"] or not p["product_url"]]
        if missing:
            raise ScrapeError(
                f"Woolworths returned incomplete records for {len(missing)} products. "
                "Snapshot was not replaced."
            )
        return products
