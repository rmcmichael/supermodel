import sqlite3
from sqlite3 import Connection
from sqlite3 import Cursor
from sqlite3 import Row
from typing import Callable


class Singleton(type):
    def __init__(self, *args, **kwargs):
        self.__instance = None
        super().__init__(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        if self.__instance is None:
            self.__instance = super().__call__(*args, **kwargs)
            return self.__instance
        else:
            return self.__instance


class Database(metaclass=Singleton):
    def __init__(self):
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

    def execute(
        self, sql: str, params: {} = None, success: Callable[[Cursor], None] = None
    ) -> Cursor:
        """Execute a SQL statement
        Return the resulting cursor
        If a success callback is provided, call it
        """
        if params is None:
            result = self.connection.execute(sql)
        else:
            result = self.connection.execute(sql, params)

        self.connection.commit()
        if success is not None:
            success(result)
        return result

    def column_exists(self, table: str, column: str) -> bool:
        result = self.connection.execute("PRAGMA table_info({})".format(table))
        for row in result:
            if row[1] == column:
                return True

        return False

    def table_exists(self, table: str):
        stmt = 'SELECT name FROM sqlite_master WHERE type = "table" and name = :table'
        row = self.connection.execute(stmt, {"table": table}).fetchone()
        if row is not None:
            return True
        else:
            return False
