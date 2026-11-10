import json

import pytest

from pipeline.source_manifest import load_source_manifest


def test_missing_manifest_defaults_to_non_reconcilable_batches(tmp_path):
    declarations = load_source_manifest(tmp_path)

    assert declarations["WEBSITE"].ingestion_mode == "INCREMENTAL_BATCH"
    assert not declarations["WEBSITE"].is_reconcilable


def test_full_snapshot_requires_explicit_scope_timestamp_and_completeness(tmp_path):
    (tmp_path / "source_manifest.json").write_text(
        json.dumps(
            {
                "sources": {
                    "WEBSITE": {
                        "ingestion_mode": "FULL_SNAPSHOT",
                        "snapshot_scope": "ALL_HISTORY",
                        "snapshot_timestamp": "2026-11-10T10:00:00+07:00",
                        "snapshot_completeness": "COMPLETE",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    declaration = load_source_manifest(tmp_path)["WEBSITE"]

    assert declaration.is_reconcilable
    assert declaration.snapshot_timestamp is not None


@pytest.mark.parametrize(
    "declaration",
    [
        {"ingestion_mode": "FULL_SNAPSHOT", "snapshot_completeness": "COMPLETE"},
        {
            "ingestion_mode": "FULL_SNAPSHOT",
            "snapshot_scope": "ALL_HISTORY",
            "snapshot_timestamp": "2026-11-10T10:00:00",
            "snapshot_completeness": "COMPLETE",
        },
        {
            "ingestion_mode": "FULL_SNAPSHOT",
            "snapshot_scope": "ALL_HISTORY",
            "snapshot_timestamp": "2026-11-10T10:00:00+07:00",
            "snapshot_completeness": "PARTIAL",
        },
    ],
)
def test_incomplete_or_timezone_less_full_snapshot_is_rejected(tmp_path, declaration):
    (tmp_path / "source_manifest.json").write_text(json.dumps({"sources": {"WEBSITE": declaration}}), encoding="utf-8")

    with pytest.raises(ValueError, match="FULL_SNAPSHOT|snapshot_timestamp"):
        load_source_manifest(tmp_path)
