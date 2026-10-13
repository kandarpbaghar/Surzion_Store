#!/usr/bin/env python3
"""
Generate import CSV files from the existing seed.json data.
This uses the already-catalogued Surzion products.
"""

import json
import csv
from pathlib import Path


def generate_import_files():
    """Generate import files from seed.json."""

    # Load seed data
    with open('Sample_Data/seed.json', 'r', encoding='utf-8') as f:
        seed_data = json.load(f)

    output_dir = Path('.')

    print("=" * 70)
    print("GENERATING IMPORT FILES FROM SEED DATA")
    print("=" * 70)

    # 1. Export HSN/GST codes
    if 'surz_hsn_gst' in seed_data:
        hsn_data = seed_data['surz_hsn_gst']
        fieldnames = ['HSN_CODE', 'DESCR', 'GST_RATE']

        with open(output_dir / 'import_hsn_gst.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in hsn_data:
                writer.writerow({
                    'HSN_CODE': row.get('hsn_code', ''),
                    'DESCR': row.get('descr', ''),
                    'GST_RATE': row.get('gst_rate', ''),
                })

        print(f"\n✓ HSN/GST codes: import_hsn_gst.csv ({len(hsn_data)} codes)")

    # 2. Export categories
    if 'surz_category' in seed_data:
        category_data = seed_data['surz_category']
        fieldnames = ['CATEGORY_CODE', 'CATEGORY_NAME', 'DESCR', 'IMAGE_URL', 'SORT_ORDER', 'IS_ACTIVE']

        with open(output_dir / 'import_categories.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in category_data:
                writer.writerow({
                    'CATEGORY_CODE': row.get('category_code', ''),
                    'CATEGORY_NAME': row.get('category_name', ''),
                    'DESCR': row.get('descr', ''),
                    'IMAGE_URL': row.get('image_url', ''),
                    'SORT_ORDER': row.get('sort_order', ''),
                    'IS_ACTIVE': row.get('is_active', 'Y'),
                })

        print(f"✓ Categories: import_categories.csv ({len(category_data)} categories)")

    # 3. Export products
    if 'surz_product' in seed_data:
        product_data = seed_data['surz_product']
        fieldnames = [
            'PRODUCT_NAME', 'CATEGORY_CODE', 'UNIT_PRICE', 'MRP', 'DESCR',
            'HSN_CODE', 'GST_RATE', 'SUBTITLE', 'IMAGE_URL', 'HOVER_IMAGE_URL',
            'GRADE', 'FINISH', 'LENGTH_MM', 'PATTERN', 'RIBBON',
            'STOCK_QTY', 'REORDER_LEVEL', 'SLUG', 'SORT_ORDER', 'IS_ACTIVE'
        ]

        with open(output_dir / 'import_products.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for idx, row in enumerate(product_data):
                writer.writerow({
                    'PRODUCT_NAME': row.get('product_name', ''),
                    'CATEGORY_CODE': row.get('category_code', ''),
                    'UNIT_PRICE': row.get('unit_price', ''),
                    'MRP': row.get('mrp', ''),
                    'DESCR': row.get('descr', ''),
                    'HSN_CODE': row.get('hsn_code', ''),
                    'GST_RATE': row.get('gst_rate', ''),
                    'SUBTITLE': row.get('subtitle', ''),
                    'IMAGE_URL': row.get('image_url', ''),
                    'HOVER_IMAGE_URL': row.get('hover_image_url', ''),
                    'GRADE': row.get('grade', ''),
                    'FINISH': row.get('finish', ''),
                    'LENGTH_MM': row.get('length_mm', ''),
                    'PATTERN': row.get('pattern', ''),
                    'RIBBON': row.get('ribbon', ''),
                    'STOCK_QTY': row.get('stock_qty', ''),
                    'REORDER_LEVEL': row.get('reorder_level', ''),
                    'SLUG': row.get('slug', ''),
                    'SORT_ORDER': idx + 1,
                    'IS_ACTIVE': row.get('is_active', 'Y'),
                })

        print(f"✓ Products: import_products.csv ({len(product_data)} products)")

    # Print summary
    print("\n" + "=" * 70)
    print("IMPORT FILES READY")
    print("=" * 70)
    print("\nFiles generated:")
    print("  1. import_hsn_gst.csv       - Tax codes (load first)")
    print("  2. import_categories.csv    - Product categories (load second)")
    print("  3. import_products.csv      - Products (load third)")

    print("\nNext steps:")
    print("  1. Open the application")
    print("  2. Navigate to: Data Entry → HSN & GST")
    print("  3. Click Import and select: import_hsn_gst.csv")
    print("  4. Navigate to: Data Entry → Categories")
    print("  5. Click Import and select: import_categories.csv")
    print("  6. Navigate to: Data Entry → Instruments")
    print("  7. Click Import and select: import_products.csv")
    print("  8. Mode: Replace (to clear old sample data)")
    print("  9. Verify imports completed successfully")
    print("\nSee IMPORT_INSTRUCTIONS.txt for detailed steps")


if __name__ == '__main__':
    try:
        generate_import_files()
        print("\n✓ Import file generation complete!")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
