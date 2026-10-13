#!/usr/bin/env python3
"""
Transform scraped data into application import format (CSV).
Creates import files for Categories, HSN/GST, and Products.
"""

import json
import csv
from typing import List, Dict, Any
from pathlib import Path

# Fixed HSN/GST data (all surgical instruments fall under this code)
HSN_GST_DATA = [
    {
        'HSN_CODE': '90183990',
        'DESCR': 'Surgical instruments and appliances',
        'GST_RATE': 12.0,
    }
]

# Category definitions
CATEGORIES = [
    {'CATEGORY_CODE': 'ORT', 'CATEGORY_NAME': 'Orthopaedic Surgical Instruments'},
    {'CATEGORY_CODE': 'GEN', 'CATEGORY_NAME': 'General Surgical Instruments'},
    {'CATEGORY_CODE': 'DIS', 'CATEGORY_NAME': 'Dissecting Forceps'},
]


class DataTransformer:
    def __init__(self, scraped_data_file: str = 'scraped_data.json'):
        self.scraped_data = {}
        self.products = []
        self.categories = []

        with open(scraped_data_file, 'r', encoding='utf-8') as f:
            self.scraped_data = json.load(f)

    def transform_categories(self) -> List[Dict[str, Any]]:
        """Transform category data."""
        self.categories = CATEGORIES
        print(f"Transformed {len(self.categories)} categories")
        return self.categories

    def transform_products(self) -> List[Dict[str, Any]]:
        """Transform product data to application schema."""
        products = []

        for idx, product in enumerate(self.scraped_data['products']):
            # Map to application schema
            transformed = {
                'PRODUCT_NAME': product.get('name', '').strip(),
                'CATEGORY_CODE': product.get('category', 'GEN'),
                'UNIT_PRICE': product.get('price', 0),
                'MRP': product.get('price', 0),  # Use same price for MRP
                'DESCR': product.get('description', '').strip()[:500],  # Limit description
                'HSN_CODE': '90183990',  # Fixed HSN code for surgical instruments
                'IS_ACTIVE': 'Y',
                'SORT_ORDER': idx + 1,
            }

            # Add first image as primary image
            images = product.get('images', [])
            if images:
                transformed['IMAGE_URL'] = images[0]

            # Add specifications as additional info
            specs = product.get('specifications', {})
            if specs:
                spec_text = '; '.join([f"{k}: {v}" for k, v in specs.items()])
                if transformed['DESCR']:
                    transformed['DESCR'] = f"{transformed['DESCR']} [{spec_text}]"
                else:
                    transformed['DESCR'] = spec_text

            products.append(transformed)

        self.products = products
        print(f"Transformed {len(self.products)} products")
        return self.products

    def write_csv(self, filename: str, data: List[Dict[str, Any]], fieldnames: List[str]):
        """Write data to CSV file."""
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in data:
                # Ensure all fields exist, fill missing with empty string
                clean_row = {field: row.get(field, '') for field in fieldnames}
                writer.writerow(clean_row)
        print(f"  ✓ {filename}")

    def generate_import_files(self, output_dir: str = '.'):
        """Generate all import CSV files."""
        output_path = Path(output_dir)

        print("\nGenerating import files:")

        # 1. HSN/GST codes
        hsn_fieldnames = ['HSN_CODE', 'DESCR', 'GST_RATE']
        self.write_csv(
            output_path / 'import_hsn_gst.csv',
            HSN_GST_DATA,
            hsn_fieldnames
        )

        # 2. Categories
        category_fieldnames = ['CATEGORY_CODE', 'CATEGORY_NAME']
        self.write_csv(
            output_path / 'import_categories.csv',
            self.categories,
            category_fieldnames
        )

        # 3. Products
        product_fieldnames = [
            'PRODUCT_NAME',
            'CATEGORY_CODE',
            'UNIT_PRICE',
            'MRP',
            'DESCR',
            'HSN_CODE',
            'IMAGE_URL',
            'IS_ACTIVE',
            'SORT_ORDER',
        ]
        self.write_csv(
            output_path / 'import_products.csv',
            self.products,
            product_fieldnames
        )

        # 4. Summary file (combined - optional, for reference)
        print("\n" + "=" * 60)
        print("IMPORT FILE SUMMARY")
        print("=" * 60)
        print(f"HSN/GST Codes:  {len(HSN_GST_DATA)} record(s)")
        print(f"Categories:     {len(self.categories)} record(s)")
        print(f"Products:       {len(self.products)} record(s)")

        if self.products:
            print("\nSample products:")
            for product in self.products[:3]:
                print(f"  • {product['PRODUCT_NAME']} (₹{product['UNIT_PRICE']})")
            if len(self.products) > 3:
                print(f"  ... and {len(self.products) - 3} more")

    def generate_import_instructions(self):
        """Generate instructions for manual import in the application."""
        instructions = """
IMPORT INSTRUCTIONS FOR SURZION STORE
======================================

The following CSV files have been generated:
  1. import_hsn_gst.csv      - Tax/GST codes
  2. import_categories.csv   - Product categories
  3. import_products.csv     - Products (main data)

IMPORT ORDER (Important - respect dependencies):
-----------------------------------------------

Step 1: Import HSN/GST Codes
  • Navigate to: Data Entry → HSN & GST
  • Action: Import
  • Select file: import_hsn_gst.csv
  • Mode: Merge (to keep existing records)
  • Confirm import

Step 2: Import Categories
  • Navigate to: Data Entry → Categories
  • Action: Import
  • Select file: import_categories.csv
  • Mode: Merge (or Replace if you want only these categories)
  • Confirm import

Step 3: Import Products
  • Navigate to: Data Entry → Instruments
  • Action: Import
  • Select file: import_products.csv
  • Mode: Replace (to clear old sample data and import new)
  • Preview the mapping:
    - PRODUCT_NAME → Product Name
    - CATEGORY_CODE → Category
    - UNIT_PRICE → Unit Price
    - MRP → MRP
    - DESCR → Description
    - HSN_CODE → HSN Code
    - IMAGE_URL → Image URL
    - IS_ACTIVE → Is Active
    - SORT_ORDER → Sort Order
  • Confirm import

POST-IMPORT VERIFICATION
------------------------

After import completes:
  1. Go to Instruments page to verify product count and display
  2. Open a sample product to verify:
     • Image loads correctly
     • Price and description display
     • Category assignment is correct
  3. Check storefront (Instruments/Shop page):
     • All products visible in correct categories
     • Images load
     • Prices display correctly
  4. Test shop filters by category to ensure category links work

ROLLBACK (if needed)
-------------------
If import fails or shows issues:
  • The application tracks import history
  • Previous versions of data are preserved
  • You can revert by re-importing the backup files
  • Or manually edit/delete records as needed

Note: The PRODUCT_CODE is auto-generated by the application (SURZ-00001, etc.)
and does not need to be provided in the import file.
"""

        with open('IMPORT_INSTRUCTIONS.txt', 'w') as f:
            f.write(instructions)

        print("\n" + instructions)


if __name__ == '__main__':
    import sys

    input_file = sys.argv[1] if len(sys.argv) > 1 else 'scraped_data.json'

    print("=" * 60)
    print("DATA TRANSFORMATION")
    print("=" * 60)
    print(f"Input: {input_file}\n")

    try:
        transformer = DataTransformer(input_file)
        transformer.transform_categories()
        transformer.transform_products()
        transformer.generate_import_files()
        transformer.generate_import_instructions()

        print("\n✓ Transformation complete!")
        print("\nFiles ready for import:")
        print("  • import_hsn_gst.csv")
        print("  • import_categories.csv")
        print("  • import_products.csv")

    except FileNotFoundError:
        print(f"Error: {input_file} not found")
        print("Please run scraper.py first to generate scraped_data.json")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
