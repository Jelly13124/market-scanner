"""Verify the debate setting migration preserves old templates in SQLite."""

from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_existing_template_defaults_to_one_round_and_can_be_customized():
    migration = import_module(
        "app.backend.alembic.versions.a4c8d2e6f901_analyze_flow_debate_rounds")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE analyze_flows (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("INSERT INTO analyze_flows VALUES (1, 'saved-template')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text("SELECT name, debate_rounds FROM analyze_flows")).one() == (
                "saved-template", 1)
            connection.execute(text("UPDATE analyze_flows SET debate_rounds = 5 WHERE id = 1"))
            assert connection.execute(text("SELECT debate_rounds FROM analyze_flows")).scalar_one() == 5
            migration.downgrade()
        assert "debate_rounds" not in {c["name"] for c in inspect(connection).get_columns("analyze_flows")}
        assert connection.execute(text("SELECT name FROM analyze_flows")).scalar_one() == "saved-template"
    engine.dispose()
