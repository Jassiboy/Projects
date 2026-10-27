"""Verify safe query runner integration behavior with isolated unit or opt-in integration tests."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.database.mysql import MySQLReadOnlyAdapter
from backend.app.database.safe_query_runner import SafeQueryRunner


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MYSQL_INTEGRATION") != "1",
    reason="Set RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL database",
)


def test_runs_read_only_query_against_mysql():
    """Verify that runs read only query against mysql; the test passes when the expected behavior is preserved."""
    adapter = MySQLReadOnlyAdapter()
    try:
        result = SafeQueryRunner(adapter).run("SELECT 1 AS value")
    finally:
        adapter.close()

    assert result.columns == ["value"]
    assert result.rows == [{"value": 1}]
    assert result.row_count == 1
    assert result.truncated is False
