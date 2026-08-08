import re
import sqlite3
from sqlite3 import Connection
from sqlite3 import Cursor
from sqlite3 import Row

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Database:
    """Process-wide singleton for SQLite access used by SuperModel.

    Call ``Database()`` anywhere to get the shared instance. Configure
    ``path`` before the first connection is opened. Default path is
    ``":memory:"``.

    Not thread-safe: use from a single thread. A future design may move
    database work onto a dedicated thread with a query queue.

    Example:
        db = Database()
        db.path = "app.db"
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        db.execute("INSERT INTO items (name) VALUES (?)", ("alpha",))

    TODO: Consider moving the connection to a dedicated thread with a query queue.
    TODO: Consider a context manager to allow multiple queries to be committed at once.
    """

    _instance = None

    def __new__(cls):
        """Return the shared Database instance, creating it if needed."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize default state once for the shared instance."""
        if getattr(self, "_initialized", False):
            return

        self._initialized = True
        self._path: str = ":memory:"
        self._connection: Connection | None = None
        self._last_cursor: Cursor | None = None

    @property
    def path(self) -> str:
        """Filesystem path or SQLite URI for the database file.

        Defaults to ``":memory:"``. Cannot be changed while a connection
        is open; call :meth:`close` first.

        Raises:
            RuntimeError: If set while a connection is open.
        """
        return self._path

    @path.setter
    def path(self, path: str) -> None:
        # Callers must close() before changing path while a connection is open.
        if self._connection is not None:
            raise RuntimeError("Cannot change path while connected; call close() first")
        self._path = path

    def _ensure_connection(self) -> Connection:
        """Open the SQLite connection for ``path`` if needed, then return it."""
        if self._connection is None:
            self._connection = sqlite3.connect(self._path)
            self._connection.row_factory = Row
        return self._connection

    def close(self) -> None:
        """Close the open connection, if any.

        Clears the last cursor used by :attr:`lastrowid` and
        :attr:`rowcount`. Does not change ``path``.
        """
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._last_cursor = None

    def reset(self) -> None:
        """Reset the singleton to defaults.

        Closes any open connection and sets ``path`` back to
        ``":memory:"``. Useful in tests and for reconfiguration.
        """
        self.close()
        self._path = ":memory:"

    def execute(self, sql: str, params: tuple | dict | None = None) -> Cursor:
        """Execute SQL, commit, and return the cursor.

        Commits after every statement by design (granular commits).
        On ``sqlite3.Error``, rolls back and re-raises.

        Args:
            sql: SQL statement to run.
            params: Positional ``tuple`` or named ``dict`` bind
                parameters. ``None`` means no parameters.

        Returns:
            The ``sqlite3.Cursor`` from the statement.

        Raises:
            sqlite3.Error: If SQLite rejects the statement.
        """
        try:
            connection = self._ensure_connection()
            result = connection.execute(sql, () if params is None else params)
            connection.commit()
            self._last_cursor = result
            return result
        except sqlite3.Error:
            self._ensure_connection().rollback()
            raise

    @property
    def lastrowid(self) -> int | None:
        """Row id from the last successful :meth:`execute`, if any."""
        if self._last_cursor is None:
            return None
        return self._last_cursor.lastrowid

    @property
    def rowcount(self) -> int | None:
        """Row count from the last successful :meth:`execute`, if any."""
        if self._last_cursor is None:
            return None
        return self._last_cursor.rowcount

    def table_exists(self, table: str) -> bool:
        """Return whether ``table`` exists in the database.

        Args:
            table: Table name to look up in ``sqlite_master``.
        """
        stmt = 'SELECT name FROM sqlite_master WHERE type = "table" and name = :table'
        row = self._ensure_connection().execute(stmt, {"table": table}).fetchone()
        return row is not None

    def column_exists(self, table: str, column: str) -> bool:
        """Return whether ``column`` exists on ``table``.

        Args:
            table: Table name. Must be a simple identifier
                (``[A-Za-z_][A-Za-z0-9_]*``).
            column: Column name to look for.

        Raises:
            ValueError: If ``table`` is not a valid identifier.
        """
        if not _IDENTIFIER.match(table):
            raise ValueError(f"Invalid table name: {table!r}")
        result = self._ensure_connection().execute(f"PRAGMA table_info({table})")
        for row in result:
            if row[1] == column:
                return True
        return False
