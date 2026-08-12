"""Model base class: annotation-driven schema and row persistence."""

from __future__ import annotations

import re
import types
import uuid

from datetime import date
from datetime import datetime
from datetime import time
from collections.abc import Callable

from typing import Any
from typing import ClassVar
from typing import Union
from typing import get_args
from typing import get_origin
from typing import get_type_hints

from .column import BoolColumn
from .column import Column
from .column import DateColumn
from .column import DateTimeColumn
from .column import FloatColumn
from .column import IntColumn
from .column import TextColumn
from .column import TimeColumn

from .database import Database

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_COLUMN_TYPES: dict[type, type[Column]] = {
    int: IntColumn,
    float: FloatColumn,
    bool: BoolColumn,
    str: TextColumn,
    date: DateColumn,
    time: TimeColumn,
    datetime: DateTimeColumn,
}


class ModelError(Exception):
    """Error raised by SuperModel for invalid model operations.

    Raised at class definition time for unsupported annotated field types or
    a reserved ``id`` field, and at runtime for invalid operations such as
    missing rows, unknown attributes, or bad identifiers.
    """

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


def _to_upper_snake(name: str) -> str:
    """Convert a CamelCase or snake_case name to ALL_CAPS_SNAKE."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).upper()


def _quote_ident(name: str) -> str:
    """Quote a SQL identifier for SQLite (handles reserved words)."""
    if not _IDENTIFIER.match(name):
        raise ModelError(f"Invalid SQL identifier: {name!r}")
    return f'"{name}"'


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Return ``(inner_type, nullable)`` for ``X | None``-style annotations."""
    origin = get_origin(annotation)
    if origin is types.UnionType or origin is Union:
        args = get_args(annotation)
        if len(args) == 2 and type(None) in args:
            inner = args[0] if args[1] is type(None) else args[1]
            return inner, True
    return annotation, False


def _column_for_annotation(annotation: Any) -> Column:
    """Build a Column strategy from a field annotation."""
    inner, nullable = _unwrap_optional(annotation)
    column_cls = _COLUMN_TYPES.get(inner)
    if column_cls is None:
        raise ModelError(
            f"Unsupported model field type: {annotation!r}. "
            "Use int, float, bool, str, date, time, datetime, "
            "or those types with | None."
        )
    return column_cls(nullable=nullable)


class _CountDescriptor:
    """Class-level ``Model.count`` property: row count for the model table."""

    def __get__(self, obj: Any, owner: type[Model] | None = None) -> int:
        if owner is None:
            raise AttributeError("count")
        owner._check_schema()
        table = _quote_ident(owner.table_name)
        stmt = f"SELECT COUNT(*) AS count FROM {table}"
        return owner._db.execute(stmt).fetchone()["count"]


class Model:
    """Base class for persisted models.

    Subclasses declare annotated fields; SuperModel builds a ``_columns``
    map, registers the class with :class:`Database`, and ensures the
    backing table on first connection (or immediately if already connected).
    Annotated fields whose names start with ``_`` are ignored for schema
    and persistence (use them for non-persistent instance state).
    Unsupported field types and a reserved ``id`` annotation raise
    :class:`ModelError` when the subclass is defined.

    Identity uses a read-only ``id`` property backed by private ``_id``.
    ``save()`` inserts (assigning a UUIDv7) when ``id is None``, otherwise
    updates. ``get`` / ``remove`` load and delete by that id. Query helpers
    include ``select``, ``count``, ``set``, ``to_dict``, and ``from_dict``.
    """

    _is_schema_checked: bool = False
    _db: Database = Database()
    _columns: ClassVar[dict[str, Column]]
    _column_names: ClassVar[dict[str, str]]
    table_name: ClassVar[str]
    count = _CountDescriptor()

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        # Each concrete subclass gets its own flag; do not share the base value.
        cls._is_schema_checked = False
        cls._columns = cls._build_columns()
        cls._column_names = {attr: _to_upper_snake(attr) for attr in cls._columns}
        cls.table_name = _to_upper_snake(cls.__name__)
        Database().register_model(cls)

    @classmethod
    def _build_columns(cls) -> dict[str, Column]:
        """Map persisted attribute names to Column strategies from annotations.

        Skips names starting with ``_`` and ``ClassVar`` annotations. Raises
        :class:`ModelError` if a field is named ``id`` (reserved) or if an
        annotation cannot be mapped to a supported column type.
        """
        columns: dict[str, Column] = {}
        # Includes inherited annotations; subclass overrides win.
        for name, annotation in get_type_hints(cls).items():
            if name.startswith("_"):
                continue
            if name == "id":
                raise ModelError(
                    "Cannot declare a persisted field named 'id'; "
                    "it is reserved for the read-only identity property"
                )
            if get_origin(annotation) is ClassVar:
                continue
            columns[name] = _column_for_annotation(annotation)
        return columns

    def __init__(self, **kwargs: Any) -> None:
        self._id: str | None = None

    @property
    def id(self) -> str | None:
        """Primary key, or ``None`` before the first successful insert."""
        return self._id

    @classmethod
    def column_name(cls, attribute_name: str, column_name: str) -> None:
        """Override the SQL column name for a persisted attribute.

        Args:
            attribute_name: Model attribute name (key in ``_columns``).
            column_name: SQL column name to use in DDL and queries.

        Raises:
            ModelError: If the attribute is unknown or ``column_name`` is
                not a safe SQL identifier.
        """
        if attribute_name not in cls._columns:
            raise ModelError(f"Unknown attribute {attribute_name!r} on {cls.__name__}")
        if not _IDENTIFIER.match(column_name):
            raise ModelError(f"Invalid column name: {column_name!r}")
        cls._column_names[attribute_name] = column_name

    @classmethod
    def _check_schema(cls) -> None:
        """Ensure the backing table matches this model.

        Idempotent. Invoked by Database on first connection and on late
        registration while connected. Creates the table if missing; adds
        missing columns with ``ALTER TABLE`` (additive only). Calls
        :meth:`on_table_created` on a fresh instance when the table is new.
        """
        if cls._is_schema_checked:
            return
        cls._is_schema_checked = True

        table_created = False
        if not cls._db.table_exists(cls.table_name):
            cls._create_table()
            table_created = True
        else:
            for attr in cls._columns:
                sql_name = cls._column_names[attr]
                if not cls._db.column_exists(cls.table_name, sql_name):
                    cls._add_column(attr)

        if table_created:
            cls().on_table_created()

    @classmethod
    def _create_table(cls) -> None:
        parts = ['"ID" TEXT PRIMARY KEY']
        for attr, column in cls._columns.items():
            sql_name = _quote_ident(cls._column_names[attr])
            parts.append(f"{sql_name} {column.ddl}")
        table = _quote_ident(cls.table_name)
        stmt = f"CREATE TABLE {table} ({', '.join(parts)})"
        cls._db.execute(stmt)

    @classmethod
    def _add_column(cls, attr: str) -> None:
        column = cls._columns[attr]
        sql_name = _quote_ident(cls._column_names[attr])
        table = _quote_ident(cls.table_name)
        stmt = f"ALTER TABLE {table} ADD COLUMN {sql_name} {column.ddl}"
        cls._db.execute(stmt)

    def on_table_created(self) -> None:
        """Hook invoked once after this model's table is newly created.

        Subclasses may override for seed data or similar setup.
        """

    def save(self) -> Model:
        """Insert a new row or update an existing one.

        If ``id is None``, generates a UUIDv7, inserts, and sets ``_id``.
        Otherwise updates the row for the current ``id``.

        Returns:
            ``self`` for fluent chaining.
        """
        type(self)._check_schema()
        if self._id is None:
            self._insert_row()
        else:
            self._update_row()
        return self

    def _insert_row(self) -> None:
        self._id = str(uuid.uuid7())
        attrs = list(self._columns)
        sql_names = ['"ID"'] + [_quote_ident(self._column_names[a]) for a in attrs]
        placeholders = [":id"] + [f":{a}" for a in attrs]
        table = _quote_ident(self.table_name)
        stmt = (
            f"INSERT INTO {table} "
            f"({', '.join(sql_names)}) "
            f"VALUES ({', '.join(placeholders)})"
        )
        self._db.execute(stmt, self._sql_params())

    def _update_row(self) -> None:
        attrs = list(self._columns)
        assignments = ", ".join(
            f"{_quote_ident(self._column_names[a])}=:{a}" for a in attrs
        )
        table = _quote_ident(self.table_name)
        stmt = f'UPDATE {table} SET {assignments} WHERE "ID" = :id'
        self._db.execute(stmt, self._sql_params())

    def _sql_params(self) -> dict[str, Any]:
        """Bind parameters for insert/update (attribute names as keys)."""
        params: dict[str, Any] = {"id": self._id}
        for attr, column in self._columns.items():
            params[attr] = column.to_sql(getattr(self, attr))
        return params

    @classmethod
    def get(cls, id: str) -> Model:
        """Load the row for ``id`` into a new instance.

        Args:
            id: Primary key value to load.

        Returns:
            A new model instance hydrated from the row.

        Raises:
            ModelError: If no row exists for ``id``.
        """
        cls._check_schema()
        table = _quote_ident(cls.table_name)
        stmt = f'SELECT * FROM {table} WHERE "ID" = ?'
        row = cls._db.execute(stmt, (id,)).fetchone()
        if row is None:
            raise ModelError(f"Id {id} does not exist in Model {cls.table_name}")
        return cls().set_from_row(row)

    def remove(self) -> Model:
        """Delete this instance's row when ``id`` is not ``None``.

        Returns:
            ``self`` for fluent chaining.
        """
        type(self)._check_schema()
        if self._id is not None:
            table = _quote_ident(self.table_name)
            stmt = f'DELETE FROM {table} WHERE "ID" = ?'
            self._db.execute(stmt, (self._id,))
        return self

    def set_from_row(self, row: Any) -> Model:
        """Hydrate this instance from a SQLite row mapping.

        Sets ``_id`` from the ``ID`` column and each annotated attribute
        via the corresponding Column codec.

        Args:
            row: A ``sqlite3.Row`` (or mapping) with SQL column names.

        Returns:
            ``self`` for fluent chaining.
        """
        self._id = row["ID"]
        for attr, column in type(self)._columns.items():
            sql_name = type(self)._column_names[attr]
            setattr(self, attr, column.from_sql(row[sql_name]))
        return self

    def set(self, values: dict[str, Any]) -> Model:
        """Populate persisted attributes from a dict of Python values.

        Only keys that match annotated model fields are applied. Values
        must already be the correct Python types (no string parsing).

        Args:
            values: Attribute name → value mapping.

        Returns:
            ``self`` for fluent chaining.
        """
        for attr in type(self)._columns:
            if attr in values:
                setattr(self, attr, values[attr])
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return persisted attributes as a dict of Python values.

        Includes annotated model fields only (not ``id``). Values are
        native Python types (``date``, ``time``, ``datetime``, ``bool``,
        etc.), not SQL encodings.
        """
        return {attr: getattr(self, attr) for attr in type(self)._columns}

    @classmethod
    def from_dict(
        cls, data: dict[str, Any] | list[dict[str, Any]]
    ) -> Model | list[Model]:
        """Create and save instance(s) from dict data.

        Accepts a single dict or a list of dicts. Each record is applied
        with :meth:`set` and then :meth:`save`. A list is saved inside a
        single :meth:`Database.transaction`.

        Args:
            data: One attribute dict, or a list of them.

        Returns:
            The saved instance for a single dict, or a list of saved
            instances for a list of dicts.
        """
        if isinstance(data, dict):
            return cls().set(data).save()

        with cls._db.transaction():
            return [cls().set(record).save() for record in data]

    @classmethod
    def select(
        cls,
        order_by: list[str] | None = None,
        filter: Callable[[Model], bool] | None = None,
    ) -> list[Model]:
        """Return all rows as model instances, optionally ordered and filtered.

        Fetches every row (``SELECT *``), then applies ``filter`` in Python
        if provided. There is no SQL ``WHERE`` DSL in v1.

        Args:
            order_by: Optional attribute names for SQL ``ORDER BY``.
                Prefix with ``-`` for descending, ``+`` or no prefix for
                ascending (for example ``["-last_login", "name"]``).
            filter: Optional ``model -> bool`` predicate applied after
                rows are hydrated.

        Returns:
            Matching model instances (possibly empty).

        Raises:
            ModelError: If an ``order_by`` entry names an unknown attribute.
        """
        cls._check_schema()
        table = _quote_ident(cls.table_name)
        stmt = f"SELECT * FROM {table}"
        stmt += cls._order_by_sql(order_by)

        models: list[Model] = []
        for row in cls._db.execute(stmt):
            model = cls().set_from_row(row)
            if filter is not None and not filter(model):
                continue
            models.append(model)
        return models

    @classmethod
    def _order_by_sql(cls, order_by: list[str] | None) -> str:
        """Build an ``ORDER BY`` clause from attribute-name directives."""
        if not order_by:
            return ""

        parts: list[str] = []
        for item in order_by:
            if item.startswith("-"):
                attr = item[1:]
                direction = "DESC"
            elif item.startswith("+"):
                attr = item[1:]
                direction = "ASC"
            else:
                attr = item
                direction = "ASC"

            if attr not in cls._columns:
                raise ModelError(
                    f"Unknown attribute {attr!r} in order_by for {cls.__name__}"
                )
            sql_name = _quote_ident(cls._column_names[attr])
            parts.append(f"{sql_name} {direction}")

        return " ORDER BY " + ", ".join(parts)
