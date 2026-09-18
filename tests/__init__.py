# --------------------------------------------------------------------------
# Test package initialisation.
#
# An in-memory SQLite database lives inside a single connection, which cannot
# serve the concurrent writers this suite exercises. Redirect it to a
# throwaway file database before any application module reads the setting, so
# that DATABASE_URL=sqlite:///:memory: still means "no external database".
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import atexit
import os
import shutil
import tempfile

_configured_database_url = os.environ.get("DATABASE_URL", "")

if _configured_database_url.startswith("sqlite") and (
    ":memory:" in _configured_database_url
    or _configured_database_url.rstrip("/") == "sqlite:"
):
    _test_db_dir = tempfile.mkdtemp(prefix="bifrost-test-db-")
    atexit.register(shutil.rmtree, _test_db_dir, True)
    os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_dir}/bifrost_test.sqlite3"
