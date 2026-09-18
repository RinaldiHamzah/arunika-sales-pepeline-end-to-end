"""Incremental business-key filtering tests."""

from pathlib import Path

from pipeline.transform.standardize import clean_results_to_staging, filter_incremental_results, source_record_hash
from pipeline.validation.data_quality import run_quality


def test_second_run_keeps_only_new_business_keys():
	results = run_quality(Path("data/source"))
	all_rows = clean_results_to_staging(results)
	existing = set(
		zip(
			all_rows["source_name"].head(10),
			all_rows["source_order_id"].head(10),
			all_rows["source_line_number"].head(10),
		)
	)
	incremental = filter_incremental_results(results, existing)
	incremental_rows = clean_results_to_staging(incremental)
	assert len(incremental_rows) == len(all_rows) - len(existing)
	assert not set(zip(
		incremental_rows["source_name"],
		incremental_rows["source_order_id"],
		incremental_rows["source_line_number"],
	)) & existing


def test_unchanged_snapshot_has_no_new_rows():
	results = run_quality(Path("data/source"))
	rows = clean_results_to_staging(results)
	existing = set(zip(rows["source_name"], rows["source_order_id"], rows["source_line_number"]))
	assert clean_results_to_staging(filter_incremental_results(results, existing)).empty


def test_changed_record_is_reprocessed_when_hash_differs():
	results = run_quality(Path("data/source"))
	clean = results["website"].clean
	row = clean.iloc[0].to_dict()
	key = ("WEBSITE", row["order_id"], int(row["line_number"]))
	old_hash = source_record_hash(row)
	existing = {key: old_hash}
	changed = clean.copy()
	changed.loc[changed.index[0], "quantity"] = int(changed.iloc[0]["quantity"]) + 1
	mutated = type(results["website"])(
		clean=changed, rejected=results["website"].rejected,
		duplicates=results["website"].duplicates, issues=results["website"].issues,
		profile=results["website"].profile, summary=results["website"].summary,
	)
	filtered = filter_incremental_results({"website": mutated}, existing)["website"].clean
	assert len(filtered) == len(changed)
	assert source_record_hash(filtered.iloc[0].to_dict()) != old_hash
