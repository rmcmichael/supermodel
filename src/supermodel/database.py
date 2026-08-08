import sqlite3
from sqlite3 import Connection
from sqlite3 import Cursor
from sqlite3 import Row


class Database:
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
        self._path = ":memory:"
        self._connection = None

    @property
    def path(self) -> str:
        """Path to database file"""
        return self._path

    @path.setter
    def path(self, path: str) -> None:
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

    def execute(self, sql: str, params: tuple | dict | None = None) -> Cursor:
        """Execute a SQL statement and commit. Return the cursor.

        Commits after every statement by design (granular commits).
        """
        try:
            result = self.connection.execute(sql, params or ())
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise
