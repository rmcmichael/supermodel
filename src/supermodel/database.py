import re
import sqlite3
from sqlite3 import Connection
from sqlite3 import Cursor
from sqlite3 import Row

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Database:
    """SQLite access for SuperModel.

    Not thread-safe: a single shared connection must be used from one thread.
    A future approach may run database work on a dedicated thread with a query queue.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Only initialize once"""
        if getattr(self, "_initialized", False):
            return

        self._initialized = True
        self._path: str = ":memory:"
        self._connection: Connection | None = None
        self._last_cursor: Cursor | None = None

    @property
    def path(self) -> str:
        """Path to database file"""
        return self._path

    @path.setter
    def path(self, path: str) -> None:
        # Callers must close() before changing path while a connection is open.
        if self._connection is not None:
            raise RuntimeError("Cannot change path while connected; call close() first")
        self._path = path

    @property
    def connection(self) -> Connection:
        """Return a connection to the database.  Open one if necessary."""
        if self._connection is None:
            self._connection = sqlite3.connect(self._path)
            self._connection.row_factory = Row
        return self._connection

    def close(self):
        """Close the connection to the database"""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._last_cursor = None

    def reset(self):
        """Close the connection and restore default singleton state."""
        self.close()
        self._path = ":memory:"

    def execute(self, sql: str, params: tuple | dict | None = None) -> Cursor:
        """Execute a SQL statement and commit. Return the cursor.

        Commits after every statement by design (granular commits).
        """
        try:
            result = self.connection.execute(
                sql, () if params is None else params
            )
            self.connection.commit()
            self._last_cursor = result
            return result
        except sqlite3.Error:
            self.connection.rollback()
            raise

    @property
    def lastrowid(self) -> int | None:
        if self._last_cursor is None:
            return None
        return self._last_cursor.lastrowid

    @property
    def rowcount(self) -> int | None:
        if self._last_cursor is None:
            return None
        return self._last_cursor.rowcount

    def table_exists(self, table: str) -> bool:
        stmt = 'SELECT name FROM sqlite_master WHERE type = "table" and name = :table'
        row = self.connection.execute(stmt, {"table": table}).fetchone()
        return row is not None

    def column_exists(self, table: str, column: str) -> bool:
        if not _IDENTIFIER.match(table):
            raise ValueError(f"Invalid table name: {table!r}")
        result = self.connection.execute(f"PRAGMA table_info({table})")
        for row in result:
            if row[1] == column:
                return True
        return False
