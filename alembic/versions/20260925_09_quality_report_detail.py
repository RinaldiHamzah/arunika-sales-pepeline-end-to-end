"""Add an explicit per-source data-quality reporting view."""

from alembic import op

revision = "20260925_09"
down_revision = "20260925_08"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE OR REPLACE VIEW audit.v_data_quality_by_rule AS
SELECT r.run_id, r.pipeline_name, r.started_at, r.status AS pipeline_status,
       q.source_name, q.rule_name, q.severity, SUM(q.failed_records) AS failed_records,
       MAX(q.evaluated_at) AS evaluated_at, q.details
FROM audit.data_quality_results q
JOIN audit.pipeline_runs r ON r.run_id = q.run_id
GROUP BY r.run_id, r.pipeline_name, r.started_at, r.status,
         q.source_name, q.rule_name, q.severity, q.details;

CREATE OR REPLACE VIEW audit.v_data_quality_report AS
WITH source_metrics AS (
    SELECT r.run_id, r.pipeline_name, r.started_at, r.status AS pipeline_status,
           metric ->> 'source_name' AS source_name,
           COALESCE((metric ->> 'source_records')::BIGINT, 0) AS source_records,
           COALESCE((metric ->> 'extracted_records')::BIGINT, 0) AS candidate_records,
           COALESCE((metric ->> 'skipped_unchanged_records')::BIGINT, 0) AS skipped_unchanged_records,
           COALESCE((metric ->> 'validated_records')::BIGINT, 0) AS valid_records,
           COALESCE((metric ->> 'rejected_records')::BIGINT, 0) AS rejected_records,
           COALESCE((metric ->> 'duplicate_records')::BIGINT, 0) AS duplicate_records
    FROM audit.pipeline_runs r
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(r.source_metrics, '[]'::jsonb)) AS metric
), quality_summary AS (
    SELECT q.run_id, q.source_name,
           COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'missing_value'), 0) AS missing_value_records,
           COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'duplicate'), 0) AS duplicate_issue_records,
           COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'invalid_quantity'), 0) AS invalid_quantity_records,
           COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'invalid_price_or_amount'), 0) AS invalid_price_or_amount_records,
           COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'invalid_date'), 0) AS invalid_date_records,
           COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'invalid_status'), 0) AS invalid_status_records,
           COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'unmapped_product'), 0) AS unmapped_product_records,
           COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'other'), 0) AS other_issue_records,
           COALESCE(SUM(q.failed_records) FILTER (WHERE q.severity = 'WARNING'), 0) AS warning_issue_records
    FROM audit.data_quality_results q
    GROUP BY q.run_id, q.source_name
)
SELECT m.*, COALESCE(q.missing_value_records, 0) AS missing_value_records,
       COALESCE(q.duplicate_issue_records, 0) AS duplicate_issue_records,
       COALESCE(q.invalid_quantity_records, 0) AS invalid_quantity_records,
       COALESCE(q.invalid_price_or_amount_records, 0) AS invalid_price_or_amount_records,
       COALESCE(q.invalid_date_records, 0) AS invalid_date_records,
       COALESCE(q.invalid_status_records, 0) AS invalid_status_records,
       COALESCE(q.unmapped_product_records, 0) AS unmapped_product_records,
       COALESCE(q.other_issue_records, 0) AS other_issue_records,
       COALESCE(q.warning_issue_records, 0) AS warning_issue_records
FROM source_metrics m
LEFT JOIN quality_summary q ON q.run_id = m.run_id AND q.source_name = m.source_name;
    """)


def downgrade():
    op.execute("DROP VIEW IF EXISTS audit.v_data_quality_report;")
    op.execute("""
CREATE OR REPLACE VIEW audit.v_data_quality_by_rule AS
SELECT r.run_id, r.pipeline_name, r.started_at, r.status AS pipeline_status,
       q.source_name, q.rule_name, q.severity, SUM(q.failed_records) AS failed_records,
       MAX(q.evaluated_at) AS evaluated_at
FROM audit.data_quality_results q
JOIN audit.pipeline_runs r ON r.run_id = q.run_id
GROUP BY r.run_id, r.pipeline_name, r.started_at, r.status,
         q.source_name, q.rule_name, q.severity;
    """)
