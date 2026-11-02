"""Validasi kontrak data canonical untuk analisis dan pemuat data."""

from types import MappingProxyType

SOURCE_SPECS = MappingProxyType(
    {
        "shopee": MappingProxyType(
            {
                "order_id": "order_id",
                "line_number": "order_line_id",
                "order_date": "order_date",
                "product_input": "product_name",
                "quantity": "qty",
                "unit_price": "unit_price",
                "customer_name": "customer_name",
                "customer_city": "customer_city",
                "payment_method": "payment_method",
                "status": "status",
            }
        ),
        "tokopedia": MappingProxyType(
            {
                "order_id": "transaction_id",
                "line_number": "item_sequence",
                "order_date": "transaction_date",
                "product_input": "item_name",
                "quantity": "quantity",
                "unit_price": "price",
                "customer_name": "buyer_name",
                "customer_city": "city",
                "payment_method": "payment",
                "status": "status",
            }
        ),
        "website": MappingProxyType(
            {
                "order_id": "invoice_no",
                "line_number": "line_item_no",
                "order_date": "created_at",
                "product_input": "product_identifier",
                "quantity": "quantity",
                "unit_price": "unit_price",
                "source_total_amount": "total_amount",
                "customer_email": "customer_email",
                "status": "status",
            }
        ),
        "offline": MappingProxyType(
            {
                "order_id": "pos_receipt_no",
                "line_number": "receipt_line_no",
                "order_date": "sold_at",
                "product_input": "item_description",
                "quantity": "units",
                "unit_price": "item_price",
                "store_name": "store_name",
                "store_city": "store_city",
                "payment_method": "payment_type",
                "status": "status",
            }
        ),
    }
)

PRODUCT_RAW_COLUMNS = ("sku", "product_name", "brand", "category", "price")
META_COLUMNS = ("source", "source_file", "source_row_number", "source_sha256")
INTERNAL_SALES_COLUMNS = (
    "source",
    "order_id",
    "line_number",
    "order_date",
    "sku",
    "product_name",
    "brand",
    "category",
    "quantity",
    "unit_price",
    "gross_amount",
    "source_total_amount",
    "customer_name",
    "customer_email",
    "customer_city",
    "store_name",
    "store_city",
    "payment_method",
    "status",
    "source_file",
    "source_row_number",
    "source_sha256",
)
CLEAN_PRODUCT_COLUMNS = ("product_id", "product_name", "brand", "kategori", "harga_satuan")
CLEAN_SALES_COLUMNS = (
    "order_id",
    "line_number",
    "product_id",
    "product_name",
    "kategori",
    "quantity",
    "total_harga",
    "tanggal_order",
    "kota",
    "channel",
    "status",
    "customer_email",
    "harga_satuan",
)

VALID_STATUSES = frozenset({"COMPLETED", "CANCELLED", "RETURNED"})
CHANNEL_LABELS = MappingProxyType(
    {
        "shopee": "Shopee",
        "tokopedia": "Tokopedia",
        "website": "Website",
        "offline": "Offline Store",
    }
)
SOURCE_NAMES = MappingProxyType({source: label.upper().replace(" ", "_") for source, label in CHANNEL_LABELS.items()})
TRANSACTION_GRAIN = "one row per source order line"
BUSINESS_KEY = ("source", "order_id", "line_number")


def order_line_key(source: str, order_id: str, line_number: int) -> tuple[str, str, int]:
    """Bentuk identitas satu item pesanan; hash isi bukan bagian dari identitas."""
    return source, str(order_id), int(line_number)


DISPOSITION_RULES = MappingProxyType(
    {
        "clean": "first valid record for a business key",
        "duplicate": "later valid record with the same business key",
        "rejected": "record with an error or conflicting duplicate versions",
    }
)

RAW_COLUMNS = MappingProxyType(
    {
        "product": PRODUCT_RAW_COLUMNS,
        **{source: tuple(spec.values()) for source, spec in SOURCE_SPECS.items()},
    }
)


def raw_column_mapping(source):
    """Kembalikan pemetaan identitas yang digunakan saat memuat tabel CSV raw."""
    return {column: column for column in RAW_COLUMNS[source]}
