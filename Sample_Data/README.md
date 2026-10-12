# Sample data

`seed.json` holds the rows in dependency order (HSN → categories →
instruments → discount). Load them through the DATA API, not with SQL:

    python backend/app/services/agent_tools/app_api.py \
        --project Surzion_Store create --obj surz_category --file ...

Going through the engine is the point — it applies the model's defaults,
its item_change fills and its validations, so the seeded rows are the same
shape as rows a person would type. A direct INSERT would skip all three and
seed data the application itself would have refused.

Order matters: an instrument's HSN drives its GST rate, and its category
must exist for the lookup to resolve.

`surz_product_image` is the odd one out: it is the instrument's GALLERY,
child form 2 of `surz_product`, keyed by the instrument's NAME because its
PRODUCT_CODE is auto-generated at save. Save it WITH its parent in one
atomic call rather than afterwards:

    POST /api/livepreview/execute-batch
    {"project": "...", "obj_name": "surz_product",
     "header": {<the surz_product row>},
     "details": {"2": [{<the gallery row>}]},
     "apply_item_change": true}
