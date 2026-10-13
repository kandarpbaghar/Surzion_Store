#!/usr/bin/env python3
"""
Web scraper for surzion.com catalogue data.
Extracts products, categories, prices, and images.
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import time
from typing import List, Dict, Any

# Category mappings
CATEGORY_MAPPINGS = {
    'Orthopaedic Surgical Instruments': {'code': 'ORT', 'name': 'Orthopaedic'},
    'General Surgical Instruments': {'code': 'GEN', 'name': 'General'},
    'Dissecting Forceps': {'code': 'DIS', 'name': 'Dissecting'},
}

BASE_URL = 'https://surzion.com'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

class SurzionScraper:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.products = []
        self.categories = []

    def _fetch_page(self, url: str) -> BeautifulSoup:
        """Fetch and parse a page."""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None

    def _extract_price(self, price_text: str) -> float:
        """Extract price from text like '₹250.00' or '$250.00'."""
        if not price_text:
            return 0.0
        # Remove currency symbols and whitespace
        price_text = price_text.strip().replace('₹', '').replace('$', '').replace(',', '')
        try:
            return float(price_text)
        except ValueError:
            return 0.0

    def scrape_categories(self) -> List[Dict[str, str]]:
        """Scrape category pages and extract products."""
        categories = []

        for category_name, category_info in CATEGORY_MAPPINGS.items():
            category_data = {
                'code': category_info['code'],
                'name': category_info['name'],
                'display_name': category_name,
            }
            categories.append(category_data)
            print(f"Registered category: {category_name} (code: {category_info['code']})")

        self.categories = categories
        return categories

    def scrape_products_from_shop(self) -> List[Dict[str, Any]]:
        """Scrape products from the shop/instruments page."""
        products = []
        shop_url = urljoin(self.base_url, '/shop')

        print(f"\nScraping shop page: {shop_url}")
        soup = self._fetch_page(shop_url)
        if not soup:
            return products

        # Look for product containers - adjust selector based on actual HTML structure
        product_elements = soup.find_all('div', class_='product')
        if not product_elements:
            # Try alternative selectors
            product_elements = soup.find_all('article', class_='product-item')
        if not product_elements:
            product_elements = soup.find_all('a', class_='product-link')

        print(f"Found {len(product_elements)} product elements")

        for idx, elem in enumerate(product_elements):
            try:
                # Extract product link
                product_link = None
                if elem.name == 'a':
                    product_link = elem.get('href', '')
                else:
                    link_elem = elem.find('a', href=True)
                    if link_elem:
                        product_link = link_elem['href']

                if not product_link:
                    continue

                product_link = urljoin(self.base_url, product_link)

                # Extract product name
                name_elem = elem.find(['h2', 'h3', 'span'], class_=['product-name', 'product-title', 'name'])
                product_name = name_elem.text.strip() if name_elem else 'Unknown'

                # Extract price
                price_elem = elem.find(['span', 'p'], class_=['price', 'product-price'])
                product_price = self._extract_price(price_elem.text if price_elem else '0')

                # Extract image
                image_url = None
                img_elem = elem.find('img')
                if img_elem:
                    image_url = img_elem.get('src') or img_elem.get('data-src')
                    if image_url:
                        image_url = urljoin(self.base_url, image_url)

                product = {
                    'name': product_name,
                    'link': product_link,
                    'price': product_price,
                    'image_url': image_url,
                    'category': 'GEN',  # Default category
                }
                products.append(product)
                print(f"  [{idx+1}] {product_name} - ₹{product_price}")

                # Rate limiting
                time.sleep(0.1)

            except Exception as e:
                print(f"  Error parsing product: {e}")
                continue

        self.products = products
        return products

    def scrape_product_details(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """Scrape detailed information from a product page."""
        product_url = product['link']
        print(f"Scraping product details: {product['name']}")

        soup = self._fetch_page(product_url)
        if not soup:
            return product

        try:
            # Extract description
            desc_elem = soup.find('div', class_=['description', 'product-description', 'content'])
            if desc_elem:
                product['description'] = desc_elem.text.strip()

            # Extract detailed images
            images = []
            img_elements = soup.find_all('img', class_=['product-image', 'main-image', 'gallery-image'])
            for img in img_elements:
                src = img.get('src') or img.get('data-src')
                if src:
                    images.append(urljoin(self.base_url, src))

            if images:
                product['images'] = images
            elif product.get('image_url'):
                product['images'] = [product['image_url']]

            # Infer category from page content
            page_text = soup.get_text().lower()
            if 'orthopaedic' in page_text or 'orthopedic' in page_text:
                product['category'] = 'ORT'
            elif 'dissecting' in page_text:
                product['category'] = 'DIS'
            else:
                product['category'] = 'GEN'

            # Try to extract specifications
            specs = {}
            spec_elements = soup.find_all('li', class_='specification')
            for spec in spec_elements:
                text = spec.text.strip()
                if ':' in text:
                    key, val = text.split(':', 1)
                    specs[key.strip().lower()] = val.strip()

            if specs:
                product['specifications'] = specs

        except Exception as e:
            print(f"  Error extracting details: {e}")

        time.sleep(0.2)
        return product

    def scrape_all(self) -> Dict[str, Any]:
        """Run complete scraping process."""
        print("=" * 60)
        print("SURZION CATALOGUE SCRAPER")
        print("=" * 60)

        # Step 1: Register categories
        self.scrape_categories()

        # Step 2: Scrape product listings
        self.scrape_products_from_shop()

        # Step 3: Scrape detailed product information
        print(f"\nScraping {len(self.products)} product details...")
        for product in self.products:
            self.scrape_product_details(product)

        return {
            'categories': self.categories,
            'products': self.products,
        }

    def save_data(self, filename: str = 'scraped_data.json'):
        """Save scraped data to JSON file."""
        data = {
            'categories': self.categories,
            'products': self.products,
        }

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"\nData saved to {filename}")
        print(f"  Categories: {len(self.categories)}")
        print(f"  Products: {len(self.products)}")


if __name__ == '__main__':
    scraper = SurzionScraper()
    data = scraper.scrape_all()
    scraper.save_data('scraped_data.json')

    print("\n" + "=" * 60)
    print("SCRAPING COMPLETE")
    print("=" * 60)
    print(f"Categories: {len(data['categories'])}")
    print(f"Products: {len(data['products'])}")
    print("\nNext step: Run transform_data.py to create import CSV")
