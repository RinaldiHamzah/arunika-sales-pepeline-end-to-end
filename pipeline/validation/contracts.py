"""Canonical data contracts shared by validation, analysis, and loaders."""

from types import MappingProxyType


SOURCE_SPECS = MappingProxyType({
    "shopee": MappingProxyType({
        "order_id": "order_id", "order_date": "order_date", "product_input": "product_name",
        "quantity": "qty", "unit_price": "unit_price", "customer_name": "customer_name",
        "customer_city": "customer_city", "payment_method": "payment_method", "status": "status",
    }),
    "tokopedia": MappingProxyType({
        "order_id": "transaction_id", "order_date": "transaction_date", "product_input": "item_name",
        "quantity": "quantity", "unit_price": "price", "customer_name": "buyer_name",
        "customer_city": "city", "payment_method": "payment", "status": "status",
    }),
    "website": MappingProxyType({
        "order_id": "invoice_no", "order_date": "created_at", "product_input": "product_identifier",
        "quantity": "quantity", "unit_price": "unit_price", "source_total_amount": "total_amount",
        "customer_email": "customer_email", "status": "status",
    }),
    "offline": MappingProxyType({
        "order_id": "pos_receipt_no", "order_date": "sold_at", "product_input": "item_description",
        "quantity": "units", "unit_price": "item_price", "store_name": "store_name",
        "store_city": "store_city", "payment_method": "payment_type", "status": "status",
    }),
})

PRODUCT_RAW_COLUMNS = ("sku", "product_name", "brand", "category", "price")
META_COLUMNS = ("source", "source_file", "source_row_number", "source_sha256")
INTERNAL_SALES_COLUMNS = (
    "source", "order_id", "line_number", "order_date", "sku", "product_name", "brand",
    "category", "quantity", "unit_price", "gross_amount", "source_total_amount", "customer_name",
    "customer_email", "customer_city", "store_name", "store_city", "payment_method", "status",
    "source_file", "source_row_number", "source_sha256",)
CLEAN_PRODUCT_COLUMNS = ("product_id", "product_name", "brand", "kategori", "harga_satuan")
CLEAN_SALES_COLUMNS = (
    "order_id", "product_id", "product_name", "kategori", "quantity", "total_harga",
    "tanggal_order", "kota", "channel", "status", "customer_email", "harga_satuan",)

VALID_STATUSES = frozenset({"COMPLETED", "CANCELLED", "RETURNED"})
CHANNEL_LABELS = MappingProxyType({
    "shopee": "Shopee", "tokopedia": "Tokopedia", "website": "Website", "offline": "Offline Store",
})
TRANSACTION_GRAIN = "one row per order; line_number=1"
BUSINESS_KEY = ("source", "order_id", "line_number")
DISPOSITION_RULES = MappingProxyType({
    "clean": "first valid record for a business key",
    "duplicate": "later valid record with the same business key",
    "rejected": "record with an error or conflicting duplicate versions",
})

RAW_COLUMNS = MappingProxyType({
    "product": PRODUCT_RAW_COLUMNS,
    **{source: tuple(spec.values()) for source, spec in SOURCE_SPECS.items()},
})


def raw_column_mapping(source):
    """Return the identity mapping used when loading a raw CSV table."""
    return {column: column for column in RAW_COLUMNS[source]}
