"""Destructive schema checks are confined to the disposable *_test database."""
from sqlalchemy import inspect

from competitive_intel.persistence.schema import initialize_schema
from conftest import DELETE_ORDER


def enums(engine):
    with engine.connect() as c:
        return dict(c.exec_driver_sql(
            "SELECT TABLE_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND ((TABLE_NAME='agent_runs' AND COLUMN_NAME='status') "
            "OR (TABLE_NAME='reports' AND COLUMN_NAME='report_type'))"
        ).all())


def test_old_database_upgrade_preserves_history_and_is_restart_safe(persistence, mysql_engine):
    with persistence.transaction() as tx:
        run_id = persistence.agent_runs.create(tx, input_name='Migration sample', normalized_input='migration sample')
    try:
        with mysql_engine.begin() as c:
            assert c.exec_driver_sql('SELECT DATABASE()').scalar().endswith('_test')
            c.exec_driver_sql("ALTER TABLE agent_runs MODIFY status ENUM('RUNNING','COMPLETED','FAILED') NOT NULL DEFAULT 'RUNNING'")
            c.exec_driver_sql("ALTER TABLE reports MODIFY report_type ENUM('BASELINE','CHANGE_TRACKING') NOT NULL")
            c.exec_driver_sql("DELETE FROM schema_migrations WHERE version='003_partial_success.sql'")
            c.exec_driver_sql("DELETE FROM schema_migrations WHERE version='004_competitive_reports.sql'")
        initialize_schema(mysql_engine)
        initialize_schema(mysql_engine)
        assert 'PARTIAL_SUCCESS' in enums(mysql_engine)['agent_runs']
        assert 'PARTIAL_EVIDENCE' in enums(mysql_engine)['reports']
        with persistence.transaction() as tx:
            assert persistence.agent_runs.get(tx, run_id)['input_name'] == 'Migration sample'
        # Simulate interrupted DDL: both ALTERs applied, migration marker not committed.
        with mysql_engine.begin() as c:
            c.exec_driver_sql("DELETE FROM schema_migrations WHERE version='003_partial_success.sql'")
            c.exec_driver_sql("DELETE FROM schema_migrations WHERE version='004_competitive_reports.sql'")
        initialize_schema(mysql_engine)
    finally:
        initialize_schema(mysql_engine)


def test_fresh_database_initialization(mysql_engine):
    # Only fixed project table names; never a production database or arbitrary tables.
    try:
        with mysql_engine.begin() as c:
            assert c.exec_driver_sql('SELECT DATABASE()').scalar().endswith('_test')
            for table in (*DELETE_ORDER, 'schema_migrations'):
                c.exec_driver_sql(f'DROP TABLE IF EXISTS `{table}`')
        initialize_schema(mysql_engine)
        assert 'PARTIAL_SUCCESS' in enums(mysql_engine)['agent_runs']
        assert 'PARTIAL_EVIDENCE' in enums(mysql_engine)['reports']
        assert set(DELETE_ORDER) <= set(inspect(mysql_engine).get_table_names())
    finally:
        initialize_schema(mysql_engine)
