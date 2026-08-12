import re
import sqlite3
from sqlite3 import Connection
from sqlite3 import Cursor
from sqlite3 import Row
from weakref import WeakValueDictionary


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

    :meth:`execute` commits after each successful statement. There is no
    multi-statement transaction API.

    Maintains a :class:`~weakref.WeakValueDictionary` identity cache so
    ``get`` / ``select`` / relation loading return the same instance for a
    given model class and id while a strong reference remains.

    Not thread-safe: use from a single thread. A future design may move
    database work onto a dedicated thread with a query queue.

    Example::

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
        self._identity: WeakValueDictionary = WeakValueDictionary()

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
        schema is ensured when the connection is first opened. After
        registration, attempts to resolve deferred relation annotations
        across all registered models.

        Args:
            model_cls: Model subclass (or test double) exposing
                ``_check_schema`` and ``_is_schema_checked``.
        """
        if model_cls not in self._models:
            self._models.append(model_cls)
        self._resolve_all_relations()
        if self._connection is not None:
            model_cls._check_schema()

    def _resolve_all_relations(self) -> None:
        """Resolve deferred FK / collection annotations on registered models."""
        for model_cls in list(self._models):
            resolve = getattr(model_cls, "_resolve_relations", None)
            if resolve is not None:
                resolve()

    def cache_get(self, model_cls: type, id: str) -> object | None:
        """Return the cached instance for ``(model_cls, id)``, if any."""
        return self._identity.get((model_cls, id))

    def cache_put(self, instance: object) -> None:
        """Register ``instance`` in the identity cache when it has an id."""
        instance_id = getattr(instance, "id", None)
        if instance_id is None:
            return
        self._identity[(type(instance), instance_id)] = instance

    def cache_evict(self, model_cls: type, id: str) -> None:
        """Remove ``(model_cls, id)`` from the identity cache if present."""
        self._identity.pop((model_cls, id), None)

    def clear_identity_cache(self) -> None:
        """Drop all identity-cache entries."""
        self._identity = WeakValueDictionary()

    def _ensure_schemas(self) -> None:
        """Run ``_check_schema`` for every registered model."""
        self._resolve_all_relations()
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
        :attr:`rowcount`. Clears the identity cache and resets
        per-connection schema-checked flags on registered models so the
        next open re-ensures schemas. Does not change ``path`` or the
        model registry.
        """
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._last_cursor = None
        self.clear_identity_cache()
        self._clear_schema_checked()

    def reset(self) -> None:
        """Reset the singleton to defaults.

        Closes any open connection, clears the model registry and identity
        cache, and sets ``path`` back to ``None``. Useful in tests and for
        reconfiguration.
        """
        self.close()
        self._models.clear()
        self._path = None

    def execute(self, sql: str, params: tuple | dict | None = None) -> Cursor:
        """Execute SQL, commit on success, and return the cursor.

        Commits after every successful statement. On ``sqlite3.Error``,
        rolls back and re-raises.

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
            connection.commit()
            self._last_cursor = result
            return result
        except sqlite3.Error:
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
