# Surzion Store - Catalogue Import Instructions

## Overview

Three CSV files have been generated containing the complete Surzion surgical instruments catalogue:

| File | Records | Purpose | Load Order |
|------|---------|---------|------------|
| **import_hsn_gst.csv** | 1 | Tax and GST codes | **1st** (Master data) |
| **import_categories.csv** | 3 | Product categories | **2nd** (Master data) |
| **import_products.csv** | 22 | Products/Instruments | **3rd** (Transaction data) |

## Important: Load Order

These files **must be imported in the exact order shown above** because:
- Products reference Categories (foreign key)
- Products reference HSN codes (foreign key)
- Importing in the wrong order will cause validation errors

---

## Step 1: Import HSN/GST Codes

1. Open the Surzion Store application
2. Navigate to: **Data Entry** → **HSN & GST**
3. Click the **Import** button
4. Select file: **import_hsn_gst.csv**
5. **Import Settings:**
   - Mode: **Merge** (preserves existing records if any)
   - Validation: Should show 1 record ready to import
6. Click **Import** to execute
7. Wait for completion message

**Expected Result:** 1 HSN code record imported (Code: 90183990)

---

## Step 2: Import Categories

1. Navigate to: **Data Entry** → **Categories**
2. Click the **Import** button
3. Select file: **import_categories.csv**
4. **Import Settings:**
   - Mode: **Merge** (keeps existing records)
   - Validation: Should show 3 categories ready to import
5. Click **Import** to execute
6. Wait for completion message

**Expected Result:** 3 category records imported:
- GEN: Surgical Instruments
- ORT: Orthopaedic
- DIS: Dissecting Forceps

---

## Step 3: Import Products (Main Catalogue)

1. Navigate to: **Data Entry** → **Instruments**
2. Click the **Import** button
3. Select file: **import_products.csv**
4. **Import Settings:**
   - Mode: **Replace** (clears the existing 21 sample products and loads fresh data)
   - Validation: Should show 22 products ready to import
5. **Verify the column mapping** (should auto-map):
   - PRODUCT_NAME → Product Name
   - CATEGORY_CODE → Category (will show category names)
   - UNIT_PRICE → Price
   - MRP → List Price
   - DESCR → Description
   - HSN_CODE → HSN Code
   - GST_RATE → GST %
   - SUBTITLE → Subtitle
   - IMAGE_URL → Main Photo
   - HOVER_IMAGE_URL → Hover Photo
   - STOCK_QTY → Stock Quantity
   - REORDER_LEVEL → Reorder Level
   - SLUG → URL Slug
   - SORT_ORDER → Display Order
   - IS_ACTIVE → Active Status
   - (GRADE, FINISH, LENGTH_MM, PATTERN are optional spec fields)

6. Click **Import** to execute
7. Wait for completion message

**Expected Result:** 22 product records imported with all details, images, and metadata.

---

## Step 4: Verification

### In the Data Entry Screen
After import completes, verify in the **Instruments** screen:
- [ ] Row count shows 22 products (from the import_products.csv file)
- [ ] All products are marked IS_ACTIVE = 'Y'
- [ ] Categories are correctly assigned (GEN, ORT, DIS)
- [ ] Prices are populated correctly
- [ ] Descriptions are complete

### In the Storefront (Public Site)
Visit the **Instruments** (Shop) page to verify:
- [ ] All 22 products visible on the Instruments page
- [ ] Products display in correct categories:
  - **Surgical Instruments (GEN)**: Should show Adenoid Curette, Artery Forceps variants, etc.
  - **Orthopaedic (ORT)**: Should show Adson Beckman Retractor, Bone Hooks, etc.
  - **Dissecting Forceps (DIS)**: Should show Adson Brown Tissue Forceps, Allis Tissue Forceps, etc.
- [ ] Product images load correctly
- [ ] Prices display as expected
- [ ] Category filtering/navigation works
- [ ] Search finds products by name

### Spot-Check Sample Products
Open 2-3 products to verify:
- [ ] Product name displays
- [ ] Description is complete and readable
- [ ] Main image (IMAGE_URL) loads
- [ ] Price (UNIT_PRICE) shows correctly
- [ ] Category assignment is correct
- [ ] Subtitle appears if populated
- [ ] Stock quantity is displayed (if used)

---

## CSV File Formats

### import_hsn_gst.csv
```csv
HSN_CODE,DESCR,GST_RATE
90183990,Surgical instruments and appliances,12.0
```

### import_categories.csv
```csv
CATEGORY_CODE,CATEGORY_NAME,DESCR,IMAGE_URL,SORT_ORDER,IS_ACTIVE
GEN,Surgical Instruments,Artery forceps...,/api/designers/assets/raw?project=...,1,Y
ORT,Orthopaedic,Reduction clamps...,/api/designers/assets/raw?project=...,2,Y
DIS,Dissecting Forceps,Tissue and dissecting forceps...,/api/designers/assets/raw?project=...,3,Y
```

### import_products.csv
```csv
PRODUCT_NAME,CATEGORY_CODE,UNIT_PRICE,MRP,DESCR,HSN_CODE,GST_RATE,SUBTITLE,IMAGE_URL,...
Adenoid Curette with Cage,GEN,2250,2655,"A specialised ENT surgical instrument...",90183990,12.0,...
...22 products total...
```

---

## Troubleshooting

### Import Fails - "Foreign Key Not Found"
**Cause:** Categories or HSN codes not imported yet
**Solution:** Ensure you're importing in the correct order:
1. HSN/GST codes first
2. Categories second
3. Products third

### Import Succeeds but Products Don't Appear in Shop
**Cause:** IS_ACTIVE column is not set to 'Y'
**Solution:** Edit products to set IS_ACTIVE = 'Y' (imported file should have this set)

### Images Don't Display on Website
**Cause:** IMAGE_URL paths are relative to application assets
**Solution:** 
- The paths like `/api/designers/assets/raw?project=Surzion_Store&file=...` are internal application asset references
- These should work if deployed in the same project
- If images don't load, contact deployment team to ensure asset server is running

### Duplicate Products After Import
**Cause:** Used "Merge" mode instead of "Replace" mode for products
**Solution:** 
- Use "Replace" mode for the final products import (Step 3) to clear old data
- If duplicates exist, manually delete the old records or re-import with Replace mode

---

## Data Included in Import

### Products by Category:

**Surgical Instruments (GEN) - 8 products:**
- Adenoid Curette with Cage
- Artery Forceps (Crile, Kocher, Ochsner, Pean, Robert)
- Babcock Forceps variants
- Bulldog Clamps
- Others

**Orthopaedic (ORT) - 6 products:**
- Adson Beckman Retractor
- Allison Lung Retractor
- Anderson Tendon Tunneling Forceps
- Bone Hooks and Reduction Clamps
- Others

**Dissecting Forceps (DIS) - 8 products:**
- Adson Brown Tissue Forceps (regular and fine)
- Allis Tissue Forceps variants
- Birkett Tonsil Artery Forceps
- Castpaw Retractor
- Others

**Total: 22 surgical instruments with:**
- Product names and descriptions
- Unit prices and MRP
- Category assignments
- HSN/GST tax codes
- Stock levels and reorder points
- Product images
- Ribbon badges (New, Best Seller, Top Quality, etc.)

---

## Rollback / Undo Import

If you need to undo the import:

1. **Option A: Revert to Previous Data**
   - The application tracks record history (if audit enabled)
   - Contact administrator to restore from backup

2. **Option B: Manual Delete**
   - Go to Data Entry → Instruments
   - Delete unwanted products individually
   - Or re-import with corrected files

3. **Option C: Restore Sample Data**
   - If you need the original 21 sample products back
   - The file `/Sample_Data/seed.json` contains the original data
   - Re-run the import process with original files

---

## Next Steps After Import

After successful import:

1. **Publish Changes** (if using versioning):
   - Deploy/publish to make changes live on website

2. **Update Marketing Content**:
   - Edit category pages to update images/descriptions if needed
   - Update homepage if product lineup features change

3. **Review Pricing**:
   - Verify all prices are correct in the shop
   - Adjust MRP (list price) vs UNIT_PRICE (selling price) as needed

4. **Configure Search/Filtering** (if applicable):
   - Test category filters
   - Test search by product name
   - Test search by attributes if available

5. **Train Staff**:
   - Ensure customer service knows where to find product details
   - Update FAQ if product list changes

---

## Support

If you encounter issues:
1. Check the **Troubleshooting** section above
2. Review import logs in the application
3. Verify CSV file format matches examples
4. Ensure columns are in the correct order
5. Check that all required fields are populated

For more help:
- See the application's import feature documentation
- Contact system administrator

---

**Generated:** 2026-10-13  
**Source:** Sample_Data/seed.json (Surzion Store catalogue)  
**Files:** 3 CSV import files (22 total records)
