from .scraper import ScrapeError


class CombinedCategoryScraper:
    """Treat several category pages as one retailer catalogue without duplicate SKUs."""

    def __init__(self, scrapers):
        self.scrapers = tuple(scrapers)
        self.last_category_counts = {}

    def scrape(self, queries):
        combined = {}
        self.last_category_counts = {}
        for scraper in self.scrapers:
            products = scraper.scrape(queries)
            group = scraper.report_group or scraper.category_url
            self.last_category_counts[group] = len(products)
            for product_id, product in products.items():
                combined.setdefault(product_id, product)
        if not combined:
            raise ScrapeError("The configured category pages returned no products.")
        return combined
