from uuid import uuid4

from pipeline.load.staging_loader import _raw_record_ids


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _MappingResult(self._rows)

    def __iter__(self):
        return iter(self._rows)

    def first(self):
        return tuple(self._rows[0].values()) if self._rows else None


class _MappingResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _Connection:
    def execute(self, statement, params):
        sql = str(statement)
        if "WHERE ingestion_run_id" in sql:
            return _Result([])
        if "WHERE source_row_number" in sql:
            return _Result([{"raw_record_id": 71}])
        raise AssertionError(f"Unexpected query: {sql}")


def test_staging_can_reference_unchanged_raw_record_from_previous_run():
    records = _raw_record_ids(
        _Connection(),
        uuid4(),
        [{"source_name": "SHOPEE", "source_row_number": 1}],
    )

    assert records[("SHOPEE", 1)] == 71
