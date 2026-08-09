import sqlite3
from sqlite3 import Connection
from sqlite3 import Row

import pytest

from supermodel import Database
from supermodel.model import Model


class _FakeModel:
    """Minimal stand-in for Database registry / schema-ensure tests."""

    _is_schema_checked = False
    check_calls = 0

    @classmethod
    def _check_schema(cls) -> None:
        if cls._is_schema_checked:
            return
        cls._is_schema_checked = True
        cls.check_calls += 1

    @classmethod
    def reset_tracking(cls) -> None:
        cls._is_schema_checked = False
        cls.check_calls = 0


@pytest.fixture
def fake_model():
    _FakeModel.reset_tracking()
    yield _FakeModel
    _FakeModel.reset_tracking()


def test_database_is_singleton(db):
    assert db is Database()


def test_database_path_property(db):
    assert db.path == ":memory:"
    db.path = "test.db"
    assert db.path == "test.db"


def test_database_reset(db, tmp_path, fake_model):
    db.path = str(tmp_path / "test.db")
    db.register_model(fake_model)
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")

    db.reset()

    assert db is Database()
    assert db.path == ":memory:"
    assert db._connection is None
    assert db.lastrowid is None
    assert db._models == []
    assert not db.table_exists("items")


def test_path_rejects_change_while_connected(db):
    db.execute("SELECT 1")

    with pytest.raises(RuntimeError):
        db.path = "other.db"

    assert db.path == ":memory:"
    db.close()
    db.path = "other.db"
    assert db.path == "other.db"


def test_connection_opens_lazily_and_reuses(db):
    assert db._connection is None

    first = db._ensure_connection()
    second = db._ensure_connection()

    assert isinstance(first, Connection)
    assert first is second
    assert first.row_factory is Row


def test_close_clears_connection(db):
    conn = db._ensure_connection()
    db.close()

    assert db._connection is None
    assert conn is not db._ensure_connection()


def test_connection_uses_path(db, tmp_path):
    db_file = tmp_path / "test.db"
    db.path = str(db_file)
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    db.close()

    assert db_file.exists()


def test_execute_write_and_read(db):
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO items (name) VALUES ('alpha')")
    row = db.execute("SELECT name FROM items WHERE id = 1").fetchone()

    assert row["name"] == "alpha"


def test_execute_with_params(db):
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO items (name) VALUES (?)", ("beta",))
    row = db.execute(
        "SELECT name FROM items WHERE name = :name", {"name": "beta"}
    ).fetchone()

    assert row["name"] == "beta"


def test_execute_with_empty_params_dict(db):
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO items (name) VALUES ('delta')", {})
    row = db.execute("SELECT name FROM items WHERE id = 1", {}).fetchone()

    assert row["name"] == "delta"


def test_execute_rolls_back_on_error(db):
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")

    with pytest.raises(sqlite3.Error):
        db.execute("INSERT INTO missing_table (name) VALUES ('nope')")

    db.execute("INSERT INTO items (name) VALUES ('gamma')")
    row = db.execute("SELECT name FROM items WHERE name = 'gamma'").fetchone()

    assert row["name"] == "gamma"


def test_table_and_column_exists(db):
    assert not db.table_exists("items")
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    assert db.table_exists("items")
    assert db.column_exists("items", "name")
    assert not db.column_exists("items", "missing")

    with pytest.raises(ValueError):
        db.column_exists("items; drop table items", "name")


def test_lastrowid_and_rowcount(db):
    assert db.lastrowid is None
    assert db.rowcount is None

    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO items (name) VALUES ('epsilon')")

    assert db.lastrowid == 1
    assert db.rowcount == 1

    db.close()
    assert db.lastrowid is None
    assert db.rowcount is None


def test_database_exported_from_package(db):
    from supermodel import Database as ImportedDatabase

    assert ImportedDatabase is Database
    assert ImportedDatabase() is db


def test_register_model_is_idempotent(db, fake_model):
    db.register_model(fake_model)
    db.register_model(fake_model)

    assert db._models == [fake_model]
    assert fake_model.check_calls == 0


def test_schema_ensure_deferred_until_first_connection(db, fake_model):
    db.register_model(fake_model)

    assert fake_model.check_calls == 0
    assert not fake_model._is_schema_checked

    db._ensure_connection()

    assert fake_model.check_calls == 1
    assert fake_model._is_schema_checked


def test_schema_ensure_on_late_registration_while_connected(db, fake_model):
    db._ensure_connection()
    assert fake_model.check_calls == 0

    db.register_model(fake_model)

    assert fake_model.check_calls == 1
    assert fake_model._is_schema_checked


def test_schema_ensure_runs_for_all_registered_models_on_open(db):
    class FakeA(_FakeModel):
        check_calls = 0
        _is_schema_checked = False

    class FakeB(_FakeModel):
        check_calls = 0
        _is_schema_checked = False

    db.register_model(FakeA)
    db.register_model(FakeB)

    db._ensure_connection()

    assert FakeA.check_calls == 1
    assert FakeB.check_calls == 1


def test_schema_ensure_again_after_close(db, fake_model):
    db.register_model(fake_model)
    db._ensure_connection()
    assert fake_model.check_calls == 1

    db.close()
    assert not fake_model._is_schema_checked

    db._ensure_connection()
    assert fake_model.check_calls == 2


def test_model_subclass_registers_with_database(db):
    class Widget(Model):
        pass

    assert Widget in db._models
    assert Widget._is_schema_checked is False

    db._ensure_connection()

    assert Widget._is_schema_checked is True


def test_model_registers_before_path_is_set(db, tmp_path):
    class Widget(Model):
        pass

    db.path = str(tmp_path / "app.db")
    db._ensure_connection()

    assert Widget._is_schema_checked is True


def test_check_schema_is_idempotent(db):
    class Widget(Model):
        pass

    Widget._check_schema()
    Widget._check_schema()

    assert Widget._is_schema_checked is True


def test_transaction_commits_on_success(db):
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")

    with db.transaction():
        db.execute("INSERT INTO items (name) VALUES ('one')")
        db.execute("INSERT INTO items (name) VALUES ('two')")

    rows = db.execute("SELECT name FROM items ORDER BY id").fetchall()
    assert [row["name"] for row in rows] == ["one", "two"]


def test_transaction_rolls_back_on_error(db):
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")

    with pytest.raises(RuntimeError, match="boom"):
        with db.transaction():
            db.execute("INSERT INTO items (name) VALUES ('one')")
            raise RuntimeError("boom")

    rows = db.execute("SELECT name FROM items").fetchall()
    assert rows == []


def test_execute_outside_transaction_commits_immediately(db, tmp_path):
    db.path = str(tmp_path / "commit.db")
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO items (name) VALUES ('visible')")

    with sqlite3.connect(db.path) as other:
        other.row_factory = Row
        row = other.execute(
            "SELECT name FROM items WHERE name = 'visible'"
        ).fetchone()
        assert row["name"] == "visible"


def test_execute_inside_transaction_defers_commit(db, tmp_path):
    db.path = str(tmp_path / "defer.db")
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")

    with db.transaction():
        db.execute("INSERT INTO items (name) VALUES ('pending')")
        assert db._in_transaction is True
        with sqlite3.connect(db.path, timeout=0.2) as other:
            other.row_factory = Row
            row = other.execute(
                "SELECT name FROM items WHERE name = 'pending'"
            ).fetchone()
            assert row is None

    assert db._in_transaction is False
    row = db.execute(
        "SELECT name FROM items WHERE name = 'pending'"
    ).fetchone()
    assert row["name"] == "pending"


def test_nested_transaction_raises(db):
    with db.transaction():
        with pytest.raises(RuntimeError, match="Nested"):
            with db.transaction():
                pass
