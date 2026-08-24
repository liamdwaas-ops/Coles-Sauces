import html
import json
import os
import re
import time
from urllib.parse import quote, urlencode

import requests

from .matcher import is_wanted_name, normalize, split_name_size


BASE_URL = "https://www.coles.com.au"
USER_AGENT = "Mozilla/5.0 (compatible; ColesProductChangeMonitor/1.0; personal-use)"


class ScrapeError(RuntimeError):
    pass


class ColesScraper:
    def __init__(self, delay=1.0, max_pages=20, page_size=48):
        self.delay = delay
        self.max_pages = max_pages
        self.page_size = page_size
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json,text/html"})
        self.build_id = os.getenv("COLES_BUILD_ID", "").strip()

    def _get(self, url, **kwargs):
        response = self.session.get(url, timeout=35, **kwargs)
        response.raise_for_status()
        return response

    def discover_build_id(self):
        if self.build_id:
            return self.build_id
        for path in ("/", "/search/products?q=pesto"):
            try:
                text = self._get(BASE_URL + path).text
            except requests.RequestException:
                continue
            match = re.search(r'"buildId"\s*:\s*"([^"]+)"', text)
            if match:
                self.build_id = html.unescape(match.group(1))
                return self.build_id
        raise ScrapeError(
            "Coles blocked build-ID discovery. Set the repository secret COLES_BUILD_ID "
            "to the current buildId from the Coles page source. No report was generated."
        )

    @staticmethod
    def _find_results(payload):
        page_props = payload.get("pageProps", {})
        likely = [page_props.get("searchResults"), page_props.get("results"), page_props.get("products")]
        for value in likely:
            if isinstance(value, dict):
                for key in ("results", "products", "items"):
                    if isinstance(value.get(key), list):
                        return value[key], value
            if isinstance(value, list):
                return value, {}
        stack = [page_props]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ("results", "products", "items") and isinstance(child, list):
                        if any(isinstance(x, dict) and ("name" in x or "id" in x) for x in child):
                            return child, value
                    stack.append(child)
            elif isinstance(value, list):
                stack.extend(value)
        raise ScrapeError("Coles returned JSON, but its product structure was not recognised.")

    @staticmethod
    def _product(raw):
        pricing = raw.get("pricing") or raw.get("price") or {}
        if not isinstance(pricing, dict):
            pricing = {"now": pricing}
        raw_name = raw.get("name") or raw.get("title") or raw.get("description") or ""
        name, size = split_name_size(raw_name, raw.get("size") or raw.get("packageSize") or "")
        product_id = str(raw.get("id") or raw.get("productId") or raw.get("code") or "").strip()
        slug = normalize(raw.get("slug") or raw.get("seoToken") or "")
        uri = ""
        images = raw.get("imageUris") or raw.get("images") or []
        if images:
            first = images[0]
            uri = first.get("uri", "") if isinstance(first, dict) else str(first)
        uri = raw.get("imageUrl") or raw.get("image_url") or uri
        if uri.startswith("/"):
            uri = "https://cdn.productimages.coles.com.au/productimages" + uri
        product_url = raw.get("url") or (f"{BASE_URL}/product/{slug}" if slug else "")
        if product_url.startswith("/"):
            product_url = BASE_URL + product_url
        if not product_url and product_id:
            product_url = f"{BASE_URL}/product/{product_id}"
        price = pricing.get("now", pricing.get("value", pricing.get("current")))
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = normalize(price)
        return product_id, {
            "name": name, "price": price, "size": size, "image_url": uri,
            "product_url": product_url, "source": product_url,
        }

    def search(self, query):
        build_id = self.discover_build_id()
        found = {}
        for page in range(1, self.max_pages + 1):
            params = {"q": query}
            if page > 1:
                params["page"] = page
            url = f"{BASE_URL}/_next/data/{quote(build_id, safe='')}/en/search/products.json?{urlencode(params)}"
            response = self._get(url)
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type.lower():
                raise ScrapeError("Coles returned a bot-protection page instead of product JSON. No report was generated.")
            results, metadata = self._find_results(response.json())
            if not results:
                break
            for raw in results:
                if not isinstance(raw, dict):
                    continue
                product_id, product = self._product(raw)
                if product_id and is_wanted_name(product["name"]):
                    found[product_id] = product
            total = metadata.get("totalResults") or metadata.get("total") or metadata.get("totalCount")
            if total is not None and page * self.page_size >= int(total):
                break
            if len(results) < self.page_size:
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
            raise ScrapeError("Coles returned no matching products. Snapshot was not replaced.")
        missing = [pid for pid, p in products.items() if not p["name"] or not p["product_url"]]
        if missing:
            raise ScrapeError(f"Coles returned incomplete records for {len(missing)} products. Snapshot was not replaced.")
        return products

