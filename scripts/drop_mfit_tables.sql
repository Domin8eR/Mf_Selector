-- ============================================================
-- Drop all MFit application tables (created by Alembic migrations)
-- Keeps the 65 original Accord Fintech vendor tables intact
-- ============================================================

BEGIN;

-- M5: Compare
DROP TABLE IF EXISTS comparison_session CASCADE;

-- M4: Governance & Chat
DROP TABLE IF EXISTS tool_call_log CASCADE;
DROP TABLE IF EXISTS chat_message CASCADE;
DROP TABLE IF EXISTS chat_thread CASCADE;
DROP TABLE IF EXISTS approval_comment CASCADE;
DROP TABLE IF EXISTS approval_request CASCADE;
DROP TABLE IF EXISTS audit_event CASCADE;
DROP TABLE IF EXISTS data_quality_exception CASCADE;

-- Ranking engine
DROP TABLE IF EXISTS ranking_component_contribution CASCADE;
DROP TABLE IF EXISTS ranking_result CASCADE;
DROP TABLE IF EXISTS ranking_run CASCADE;

-- Rule governance
DROP TABLE IF EXISTS rule_component CASCADE;
-- Must drop FK on rule_set.active_version_id before dropping rule_version
ALTER TABLE IF EXISTS rule_set DROP CONSTRAINT IF EXISTS fk_rule_set_active_version;
DROP TABLE IF EXISTS rule_version CASCADE;
DROP TABLE IF EXISTS rule_set CASCADE;

-- Metrics engine
DROP TABLE IF EXISTS calculation_lineage CASCADE;
DROP TABLE IF EXISTS rolling_metric_value CASCADE;
DROP TABLE IF EXISTS metric_value_snapshot CASCADE;
DROP TABLE IF EXISTS metric_definition CASCADE;

-- Time-series
DROP TABLE IF EXISTS excess_return_daily CASCADE;
DROP TABLE IF EXISTS benchmark_return_daily CASCADE;
DROP TABLE IF EXISTS fund_return_daily CASCADE;
DROP TABLE IF EXISTS benchmark_level_daily CASCADE;
DROP TABLE IF EXISTS fund_nav_daily CASCADE;

-- Data governance
DROP TABLE IF EXISTS ingestion_run CASCADE;
DROP TABLE IF EXISTS data_version CASCADE;

-- Core reference
DROP TABLE IF EXISTS scheme_plan CASCADE;
DROP TABLE IF EXISTS scheme CASCADE;
DROP TABLE IF EXISTS benchmark CASCADE;
DROP TABLE IF EXISTS category CASCADE;
DROP TABLE IF EXISTS trading_calendar CASCADE;
DROP TABLE IF EXISTS amc CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS firms CASCADE;

-- Alembic tracking
DROP TABLE IF EXISTS alembic_version CASCADE;

-- Drop custom enum types created by migrations
DROP TYPE IF EXISTS user_role CASCADE;
DROP TYPE IF EXISTS data_version_status CASCADE;
DROP TYPE IF EXISTS ingestion_run_status CASCADE;
DROP TYPE IF EXISTS rule_version_status CASCADE;
DROP TYPE IF EXISTS approval_status CASCADE;
DROP TYPE IF EXISTS exception_severity CASCADE;
DROP TYPE IF EXISTS exception_status CASCADE;

COMMIT;
