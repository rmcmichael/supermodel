import re
import sqlite3
from contextlib import contextmanager
from sqlite3 import Connection
from sqlite3 import Cursor
from sqlite3 import Row
from typing import Iterator

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Database:
    """Process-wide singleton for SQLite access used by SuperModel.

    Call ``Database()`` anywhere to get the shared instance. Configure
    ``path`` before the first connection is opened. Default path is
    ``None``; connecting before ``path`` is set raises ``RuntimeError``.

    Models register themselves via :meth:`register_model`. Schema checks
    run when the connection is first opened (for all registered models)
    and immediately when a model registers while a connection is already
    open.

    Outside an explicit :meth:`transaction`, :meth:`execute` commits after
    each statement. Nested ``transaction()`` blocks are not supported.

    Not thread-safe: use from a single thread. A future design may move
    database work onto a dedicated thread with a query queue.

    Example:
        db = Database()
        db.path = "app.db"
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        db.execute("INSERT INTO items (name) VALUES (?)", ("alpha",))

    TODO: Consider moving the connection to a dedicated thread with a query queue.
    TODO: Support synchronizing multiple copies of a database through an
        intermediary web service (not designed yet).
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
        self._path: str | None = None
        self._connection: Connection | None = None
        self._last_cursor: Cursor | None = None
        self._models: list[type] = []
        self._in_transaction: bool = False

    @property
    def path(self) -> str | None:
        """Filesystem path or SQLite URI for the database file.

        Defaults to ``None``. Must be set before a connection is opened.
        Cannot be changed while a connection is open; call :meth:`close`
        first. Use ``":memory:"`` for an in-memory database.

        Raises:
            RuntimeError: If set while a connection is open.
        """
        return self._path

    @path.setter
    def path(self, path: str | None) -> None:
        # Callers must close() before changing path while a connection is open.
        if self._connection is not None:
            raise RuntimeError("Cannot change path while connected; call close() first")
        self._path = path
    def register_model(self, model_cls: type) -> None:
        """Register a model class for schema ensure.

        Idempotent for a given class. If a connection is already open,
        calls ``model_cls._check_schema()`` immediately. Otherwise the
        schema is ensured when the connection is first opened.

        Args:
            model_cls: Model subclass (or test double) exposing
                ``_check_schema`` and ``_is_schema_checked``.
        """
        if model_cls in self._models:
            return
        self._models.append(model_cls)
        if self._connection is not None:
            model_cls._check_schema()

    def _ensure_schemas(self) -> None:
        """Run ``_check_schema`` for every registered model."""
        for model_cls in self._models:
            model_cls._check_schema()

    def _clear_schema_checked(self) -> None:
        """Allow schema ensure to run again after the connection closes."""
        for model_cls in self._models:
            model_cls._is_schema_checked = False

    def _ensure_connection(self) -> Connection:
        """Open the SQLite connection for ``path`` if needed, then return it.

        On first open, ensures schema for all registered models.

        Raises:
            RuntimeError: If ``path`` has not been set.
        """
        if self._path is None:
            raise RuntimeError("Database.path must be set before connecting")
        if self._connection is None:
            self._connection = sqlite3.connect(self._path)
            self._connection.row_factory = Row
            self._ensure_schemas()
        return self._connection

    def close(self) -> None:
        """Close the open connection, if any.

        Clears the last cursor used by :attr:`lastrowid` and
        :attr:`rowcount`. Resets per-connection schema-checked flags on
        registered models so the next open re-ensures schemas. Does not
        change ``path`` or the model registry.
        """
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._last_cursor = None
        self._in_transaction = False
        self._clear_schema_checked()

    def reset(self) -> None:
        """Reset the singleton to defaults.

        Closes any open connection, clears the model registry, and sets
        ``path`` back to ``None``. Useful in tests and for
        reconfiguration.
        """
        self.close()
        self._models.clear()
        self._path = None

    @contextmanager
    def transaction(self) -> Iterator["Database"]:
        """Run statements in a single transaction.

        Commits on clean exit; rolls back if the block exits with an
        exception. Nested ``transaction()`` blocks are not supported.

        Yields:
            The shared Database instance.

        Raises:
            RuntimeError: If called while already inside a transaction.
        """
        if self._in_transaction:
            raise RuntimeError("Nested Database.transaction() is not supported")

        connection = self._ensure_connection()
        self._in_transaction = True
        try:
            connection.execute("BEGIN")
            yield self
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._in_transaction = False

    def execute(self, sql: str, params: tuple | dict | None = None) -> Cursor:
        """Execute SQL and return the cursor.

        Outside :meth:`transaction`, commits after every statement
        (granular commits). Inside a transaction, does not commit; the
        surrounding transaction commits or rolls back as a whole.
        On ``sqlite3.Error`` outside a transaction, rolls back and
        re-raises.

        Args:
            sql: SQL statement to run.
            params: Positional ``tuple`` or named ``dict`` bind
                parameters. ``None`` means no parameters.

        Returns:
            The ``sqlite3.Cursor`` from the statement.

        Raises:
            sqlite3.Error: If SQLite rejects the statement.
        """
        connection = self._ensure_connection()
        try:
            result = connection.execute(sql, () if params is None else params)
            if not self._in_transaction:
                connection.commit()
            self._last_cursor = result
            return result
        except sqlite3.Error:
            if not self._in_transaction:
                connection.rollback()
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

        Returns:
            True if the table exists in the database, False otherwise
        """
        stmt = 'SELECT name FROM sqlite_master WHERE type = "table" and name = :table'
        row = self._ensure_connection().execute(stmt, {"table": table}).fetchone()
        return row is not None

    def column_exists(self, table: str, column: str) -> bool:
        """Return whether ``column`` exists on ``table``.

        Args:
            table: Name of the table the column belongs to
            column: Column name to look for

        Returns:
            True if the column exists on the table, False otherwise
        """

        # Prevent SQL injection
        if not _IDENTIFIER.match(table):
            raise ValueError(f"Invalid table name: {table!r}")

        # Check if the column exists on the table
        result = self._ensure_connection().execute(f"PRAGMA table_info({table})")
        for row in result:
            if row[1] == column:
                return True
        return False
