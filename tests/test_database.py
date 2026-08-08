import sqlite3
from sqlite3 import Connection
from sqlite3 import Row

import pytest

from supermodel.database import Database


def test_database_is_singleton():
    first = Database()
    second = Database()
    assert first is second


def test_database_path_property():
    db = Database()
    assert db.path == ":memory:"
    db.path = "test.db"
    assert db.path == "test.db"
    db.path = ":memory:"


def test_connection_opens_lazily_and_reuses():
    db = Database()
    db.close()
    assert db._connection is None

    first = db.connection
    second = db.connection

    assert isinstance(first, Connection)
    assert first is second
    assert first.row_factory is Row

    db.close()


def test_close_clears_connection():
    db = Database()
    conn = db.connection
    db.close()

    assert db._connection is None
    assert conn is not db.connection

    db.close()


def test_connection_uses_path(tmp_path):
    db = Database()
    db.close()

    db_file = tmp_path / "test.db"
    db.path = str(db_file)
    conn = db.connection
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    conn.commit()
    db.close()

    assert db_file.exists()

    db.path = ":memory:"


def test_execute_write_and_read():
    db = Database()
    db.path = ":memory:"
    db.close()

    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO items (name) VALUES ('alpha')")
    row = db.execute("SELECT name FROM items WHERE id = 1").fetchone()

    assert row["name"] == "alpha"
    db.close()


def test_execute_with_params():
    db = Database()
    db.path = ":memory:"
    db.close()

    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO items (name) VALUES (?)", ("beta",))
    row = db.execute(
        "SELECT name FROM items WHERE name = :name", {"name": "beta"}
    ).fetchone()

    assert row["name"] == "beta"
    db.close()


def test_execute_rolls_back_on_error():
    db = Database()
    db.path = ":memory:"
    db.close()

    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")

    with pytest.raises(sqlite3.Error):
        db.execute("INSERT INTO missing_table (name) VALUES ('nope')")

    db.execute("INSERT INTO items (name) VALUES ('gamma')")
    row = db.execute("SELECT name FROM items WHERE name = 'gamma'").fetchone()

    assert row["name"] == "gamma"
    db.close()
