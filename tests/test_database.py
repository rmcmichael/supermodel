import sqlite3
from sqlite3 import Connection
from sqlite3 import Row

import pytest

from supermodel import Database


def test_database_is_singleton(db):
    assert db is Database()


def test_database_path_property(db):
    assert db.path == ":memory:"
    db.path = "test.db"
    assert db.path == "test.db"


def test_database_reset(db, tmp_path):
    db.path = str(tmp_path / "test.db")
    _ = db.connection
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")

    db.reset()

    assert db is Database()
    assert db.path == ":memory:"
    assert db._connection is None
    assert db.lastrowid is None
    assert not db.table_exists("items")


def test_path_rejects_change_while_connected(db):
    _ = db.connection

    with pytest.raises(RuntimeError):
        db.path = "other.db"

    assert db.path == ":memory:"
    db.close()
    db.path = "other.db"
    assert db.path == "other.db"


def test_connection_opens_lazily_and_reuses(db):
    assert db._connection is None

    first = db.connection
    second = db.connection

    assert isinstance(first, Connection)
    assert first is second
    assert first.row_factory is Row


def test_close_clears_connection(db):
    conn = db.connection
    db.close()

    assert db._connection is None
    assert conn is not db.connection


def test_connection_uses_path(db, tmp_path):
    db_file = tmp_path / "test.db"
    db.path = str(db_file)
    conn = db.connection
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    conn.commit()
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
