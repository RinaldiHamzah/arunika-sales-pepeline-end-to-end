"""Transform validated clean records into warehouse loading rows."""
from __future__ import annotations

import hashlib
import json
import pandas as pd

from pipeline.validation.contracts import CHANNEL_LABELS

SOURCE_NAMES = {source: label.upper().replace(" ", "_") for source, label in CHANNEL_LABELS.items()}
_HASH_EXCLUDED = {"source_file", "source_row_number", "source_sha256"}


def source_record_hash(record: dict) -> str:
	"""Stable content hash used to detect corrections for an existing business key."""
	values = {key: value for key, value in record.items() if key not in _HASH_EXCLUDED}
	return hashlib.sha256(json.dumps(values, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def filter_incremental_results(results, existing_keys):
	"""Keep new rows and changed rows; skip only an identical key/content hash.

	``existing_keys`` accepts the legacy set of keys and the production mapping
	``business_key -> source_record_hash``.
	"""
	is_mapping = hasattr(existing_keys, "get")
	filtered = {}
	for source, result in results.items():
		if source == "product":
			filtered[source] = result
			continue
		clean = result.clean.copy()
		if not clean.empty:
			source_name = SOURCE_NAMES[source]
			keys = list(zip(
				[source_name] * len(clean),
				clean["order_id"],
				clean["line_number"].astype(int),
			))
			hashes = [source_record_hash(row) for row in clean.to_dict("records")]
			clean = clean[[
				key not in existing_keys or (is_mapping and existing_keys.get(key) != row_hash)
				for key, row_hash in zip(keys, hashes)
			]].reset_index(drop=True)
		filtered[source] = type(result)(
			clean=clean,
			rejected=result.rejected,
			duplicates=result.duplicates,
			issues=result.issues,
			profile=result.profile,
			summary=result.summary,
		)
	return filtered


def clean_results_to_staging(results) -> pd.DataFrame:
	"""Build typed staging rows from the validated clean results."""
	rows = []
	for source, result in results.items():
		if source == "product":
			continue
		for record in result.clean.to_dict("records"):
			customer_name = record.get("customer_name")
			customer_email = record.get("customer_email")
			customer_city = record.get("customer_city")
			customer_nk = None
			if customer_email:
				customer_nk = f"{SOURCE_NAMES[source]}:EMAIL:{customer_email}"
			elif customer_name:
				customer_nk = f"{SOURCE_NAMES[source]}:NAME:{customer_name}:{customer_city or ''}"
			rows.append({
				"source_name": SOURCE_NAMES[source],
				"source_row_number": int(record["source_row_number"]),
				"source_order_id": record["order_id"],
				"source_line_number": int(record["line_number"]),
				"order_date": record["order_date"].date(),
				"product_input": record["product_name"],
				"mapped_sku": record["sku"],
				"customer_nk": customer_nk,
				"customer_name": customer_name,
				"city": record.get("store_city") if source == "offline" else customer_city,
				"payment_method": record.get("payment_method"),
				"sale_status": record["status"],
				"quantity": int(record["quantity"]),
				"unit_price": record["unit_price"],
				"source_total_amount": record.get("source_total_amount"),
				"source_record_hash": source_record_hash(record),
			})
	return pd.DataFrame(rows)
