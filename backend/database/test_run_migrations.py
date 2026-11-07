import unittest

from backend.database.run_migrations import migration_files, split_migration


class MigrationRunnerTests(unittest.TestCase):
    def test_discovers_migrations_in_order(self):
        self.assertEqual(
            [path.name for path in migration_files()],
            ["001_schema.sql", "002_hitl_trading.sql"],
        )

    def test_baseline_enables_uuid_extension(self):
        schema_path = migration_files()[0]
        statements = split_migration(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(statements, ['CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'])

    def test_hitl_migration_contains_six_requested_tables(self):
        hitl_path = migration_files()[1]
        statements = split_migration(hitl_path.read_text(encoding="utf-8"))
        tables = {
            statement.split("CREATE TABLE ", 1)[1].split(" ", 1)[0]
            for statement in statements
            if statement.startswith("CREATE TABLE ")
        }

        self.assertEqual(
            tables,
            {
                "research_signals",
                "supervisor_reviews",
                "orders",
                "executions",
                "portfolio_positions",
                "agent_tokens_audit",
            },
        )


if __name__ == "__main__":
    unittest.main()
