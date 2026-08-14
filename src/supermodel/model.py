"""Model base class: annotation-driven schema and row persistence."""

from __future__ import annotations

import re
import types
import uuid

from datetime import date
from datetime import datetime
from datetime import time
from datetime import timezone
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
from .column import FKColumn
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


def _is_model_type(annotation: Any) -> bool:
    return (
        isinstance(annotation, type)
        and issubclass(annotation, Model)
        and annotation is not Model
    )


def _column_for_annotation(annotation: Any) -> Column:
    """Build a Column strategy from a scalar field annotation."""
    inner, nullable = _unwrap_optional(annotation)
    column_cls = _COLUMN_TYPES.get(inner)
    if column_cls is None:
        raise ModelError(
            f"Unsupported model field type: {annotation!r}. "
            "Use int, float, bool, str, date, time, datetime, "
            "a Model subclass (FK), list[Model] (virtual reverse), "
            "or those scalar types with | None."
        )
    return column_cls(nullable=nullable)


class _FKDescriptor:
    """Lazy foreign-key attribute: stores parent id, resolves parent on access."""

    def __init__(
        self, name: str, parent_cls: type[Model], nullable: bool = False
    ) -> None:
        self.name = name
        self.parent_cls = parent_cls
        self.nullable = nullable
        self._obj_attr = f"_{name}_obj"

    def __set_name__(self, owner: type[Model], name: str) -> None:
        self.name = name
        self._obj_attr = f"_{name}_obj"

    def __get__(self, obj: Model | None, owner: type[Model] | None = None) -> Any:
        if obj is None:
            return self
        if hasattr(obj, self._obj_attr):
            return getattr(obj, self._obj_attr)
        if self.name not in obj._fk_ids:
            if self.nullable:
                return None
            raise AttributeError(
                f"{type(obj).__name__}.{self.name} has not been set"
            )
        fk_id = obj._fk_ids[self.name]
        if fk_id is None:
            return None
        parent = self.parent_cls.get(fk_id)
        setattr(obj, self._obj_attr, parent)
        return parent

    def __set__(self, obj: Model, value: Any) -> None:
        if value is None:
            if not self.nullable:
                raise ModelError(
                    f"{type(obj).__name__}.{self.name} requires a "
                    f"{self.parent_cls.__name__} instance (got None)"
                )
            setattr(obj, self._obj_attr, None)
            obj._fk_ids[self.name] = None
            return
        if not isinstance(value, self.parent_cls):
            raise ModelError(
                f"{type(obj).__name__}.{self.name} requires a "
                f"{self.parent_cls.__name__} instance "
                f"(got {type(value).__name__})"
            )
        setattr(obj, self._obj_attr, value)
        obj._fk_ids[self.name] = value.id


class _CollectionDescriptor:
    """Virtual one-to-many reverse relation: lazy list of child instances."""

    def __init__(
        self, name: str, child_cls: type[Model], fk_attr: str
    ) -> None:
        self.name = name
        self.child_cls = child_cls
        self.fk_attr = fk_attr
        self._cache_attr = f"_{name}_list"

    def __set_name__(self, owner: type[Model], name: str) -> None:
        self.name = name
        self._cache_attr = f"_{name}_list"

    def __get__(self, obj: Model | None, owner: type[Model] | None = None) -> Any:
        if obj is None:
            return self
        if hasattr(obj, self._cache_attr):
            return getattr(obj, self._cache_attr)
        if obj.id is None:
            result: list[Model] = []
        else:
            result = self.child_cls._select_by_fk(self.fk_attr, obj.id)
        setattr(obj, self._cache_attr, result)
        return result

    def __set__(self, obj: Model, value: Any) -> None:
        raise ModelError(
            f"{type(obj).__name__}.{self.name} is a virtual collection; "
            "assign the child foreign key and save the child instead"
        )


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

    Model-typed attributes are foreign keys. Use ``Parent | None`` for a
    nullable FK. ``list[ChildModel]`` attributes are virtual reverse
    relations (no column).

    Identity uses a read-only ``id`` property backed by private ``_id``.
    ``save()`` inserts (assigning a UUIDv7) when ``id is None``, otherwise
    updates. ``get`` / ``remove`` load and delete by that id (``remove``
    cascades to children that reference this row). Query helpers include
    ``select``, ``count``, ``set``, ``to_dict``, and ``from_dict``.
    """

    _is_schema_checked: bool = False
    _db: Database = Database()
    _columns: ClassVar[dict[str, Column]]
    _column_names: ClassVar[dict[str, str]]
    _fk_attrs: ClassVar[dict[str, type[Model]]]
    _collection_attrs: ClassVar[dict[str, tuple[type[Model], str]]]
    _pending_annotations: ClassVar[dict[str, Any]]
    _relations_resolved: ClassVar[bool]
    table_name: ClassVar[str]
    count = _CountDescriptor()

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        # Each concrete subclass gets its own flag; do not share the base value.
        cls._is_schema_checked = False
        cls._relations_resolved = False
        cls._fk_attrs = {}
        cls._collection_attrs = {}
        cls._pending_annotations = {}
        cls._columns = {}
        cls._column_names = {}
        cls.table_name = _to_upper_snake(cls.__name__)
        cls._ingest_annotations()
        Database().register_model(cls)

    @classmethod
    def _ingest_annotations(cls) -> None:
        """Classify annotations into columns, FKs, collections, or deferred."""
        raw: dict[str, Any] = {}
        for base in reversed(cls.__mro__):
            if base is Model or base is object:
                continue
            for name, annotation in getattr(base, "__annotations__", {}).items():
                if name.startswith("_"):
                    continue
                raw[name] = annotation

        if "id" in raw:
            raise ModelError(
                "Cannot declare a persisted field named 'id'; "
                "it is reserved for the read-only identity property"
            )

        hints = cls._safe_type_hints()
        for name, annotation in raw.items():
            resolved = hints.get(name, annotation)
            if get_origin(resolved) is ClassVar:
                continue
            cls._classify_field(name, resolved)

        cls._column_names = {
            attr: _to_upper_snake(attr) for attr in cls._columns
        }

    @classmethod
    def _safe_type_hints(cls) -> dict[str, Any]:
        try:
            return get_type_hints(cls)
        except Exception:
            pass
        module = __import__(cls.__module__, fromlist=["*"])
        globalns = dict(vars(module))
        # Ensure Model module names are visible when resolving base ClassVars.
        import supermodel.model as model_module

        globalns.update(vars(model_module))
        localns = {m.__name__: m for m in Database()._models}
        localns[cls.__name__] = cls
        try:
            return get_type_hints(cls, globalns=globalns, localns=localns)
        except Exception:
            return {}

    @classmethod
    def _classify_field(cls, name: str, annotation: Any) -> None:
        if get_origin(annotation) is ClassVar:
            return
        if isinstance(annotation, str):
            cls._pending_annotations[name] = annotation
            return

        inner, nullable = _unwrap_optional(annotation)
        origin = get_origin(inner)

        if origin is list:
            args = get_args(inner)
            if len(args) != 1:
                raise ModelError(
                    f"Unsupported model field type: {annotation!r}. "
                    "Use list[SomeModel] for virtual reverse relations."
                )
            child = args[0]
            if isinstance(child, str) or not isinstance(child, type):
                cls._pending_annotations[name] = annotation
                return
            if not _is_model_type(child):
                raise ModelError(
                    f"Unsupported model field type: {annotation!r}. "
                    "list[...] reverse relations require a Model subclass."
                )
            if nullable:
                raise ModelError(
                    f"{cls.__name__}.{name}: virtual collections cannot be optional"
                )
            cls._collection_attrs[name] = (child, "")
            setattr(cls, name, _CollectionDescriptor(name, child, ""))
            return

        if isinstance(inner, str) or not isinstance(inner, type):
            cls._pending_annotations[name] = annotation
            return

        if _is_model_type(inner):
            cls._fk_attrs[name] = inner
            cls._columns[name] = FKColumn(nullable=nullable)
            setattr(cls, name, _FKDescriptor(name, inner, nullable=nullable))
            return

        cls._columns[name] = _column_for_annotation(annotation)

    @classmethod
    def _resolve_relations(cls) -> None:
        """Resolve deferred annotations and wire collection → FK links."""
        if cls._pending_annotations:
            hints = cls._safe_type_hints()
            resolved_names = []
            for name, raw in list(cls._pending_annotations.items()):
                annotation = hints.get(name)
                if annotation is None or isinstance(annotation, str):
                    continue
                # Temporarily remove so classify does not re-pend the same key blindly.
                resolved_names.append(name)
                cls._pending_annotations.pop(name, None)
                cls._classify_field(name, annotation)
                if name in cls._pending_annotations:
                    # Still unresolved (nested forward ref).
                    continue
            cls._column_names = {
                attr: _to_upper_snake(attr) for attr in cls._columns
            }

        # Link virtual collections to the child's FK attribute.
        for coll_name, (child_cls, _fk) in list(cls._collection_attrs.items()):
            if not _is_model_type(child_cls):
                continue
            # Ensure child has resolved its FKs first.
            if getattr(child_cls, "_pending_annotations", None):
                child_cls._resolve_relations()
            fk_matches = [
                attr
                for attr, parent in child_cls._fk_attrs.items()
                if parent is cls
            ]
            if len(fk_matches) == 0:
                if cls._pending_annotations or child_cls._pending_annotations:
                    continue
                raise ModelError(
                    f"{cls.__name__}.{coll_name}: no foreign key on "
                    f"{child_cls.__name__} pointing at {cls.__name__}"
                )
            if len(fk_matches) > 1:
                raise ModelError(
                    f"{cls.__name__}.{coll_name}: multiple foreign keys on "
                    f"{child_cls.__name__} point at {cls.__name__}; "
                    "ambiguous reverse relation"
                )
            fk_attr = fk_matches[0]
            cls._collection_attrs[coll_name] = (child_cls, fk_attr)
            setattr(cls, coll_name, _CollectionDescriptor(coll_name, child_cls, fk_attr))

        if not cls._pending_annotations:
            cls._relations_resolved = True

    @classmethod
    def _ensure_relations_resolved(cls) -> None:
        Database()._resolve_all_relations()
        if cls._pending_annotations:
            raise ModelError(
                f"{cls.__name__} has unresolved relation annotations: "
                f"{sorted(cls._pending_annotations)}"
            )

    def __init__(self, **kwargs: Any) -> None:
        self._id: str | None = None
        self._fk_ids: dict[str, str | None] = {}

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
        cls._ensure_relations_resolved()
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
        Otherwise updates the row for the current ``id``. Required foreign
        keys must be set and must reference a parent that already has an
        ``id``. Optional foreign keys (``Parent | None``) may be unset or
        ``None`` (stored as ``NULL``); an assigned parent must still have
        an ``id``.

        Does not cascade: only this instance is written. Related parents
        and children are not saved.

        Returns:
            ``self`` for fluent chaining.
        """
        type(self)._check_schema()
        self._validate_foreign_keys()
        if self._id is None:
            self._insert_row()
        else:
            self._update_row()
        self._db.cache_put(self)
        return self

    def _validate_foreign_keys(self) -> None:
        for attr in type(self)._fk_attrs:
            parent_id = self._fk_sql_id(attr)
            if parent_id is not None:
                continue
            obj = getattr(self, f"_{attr}_obj", None)
            if obj is not None:
                raise ModelError(
                    f"{type(self).__name__}.{attr} parent must be saved "
                    f"(parent id is None) before save()"
                )
            if type(self)._columns[attr].nullable:
                continue
            raise ModelError(
                f"{type(self).__name__}.{attr} must be set before save()"
            )

    def _fk_sql_id(self, attr: str) -> str | None:
        obj = getattr(self, f"_{attr}_obj", None)
        if obj is not None:
            return obj.id
        return self._fk_ids.get(attr)

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
        try:
            self._db.execute(stmt, self._sql_params())
        except Exception:
            self._id = None
            raise

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
            if attr in type(self)._fk_attrs:
                fk_id = self._fk_sql_id(attr)
                params[attr] = column.to_sql(fk_id)
            else:
                value = getattr(self, attr)
                # Keep in-memory datetime values timezone-aware after coerce.
                if isinstance(value, datetime) and value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                    setattr(self, attr, value)
                params[attr] = column.to_sql(value)
        return params

    @classmethod
    def get(cls, id: str) -> Model:
        """Load the row for ``id`` into a new instance.

        Returns a cached instance when the identity map already holds
        this ``(class, id)``.

        Args:
            id: Primary key value to load.

        Returns:
            A model instance hydrated from the row (or the cached one).

        Raises:
            ModelError: If no row exists for ``id``.
        """
        cls._check_schema()
        cached = cls._db.cache_get(cls, id)
        if cached is not None:
            return cached  # type: ignore[return-value]

        table = _quote_ident(cls.table_name)
        stmt = f'SELECT * FROM {table} WHERE "ID" = ?'
        row = cls._db.execute(stmt, (id,)).fetchone()
        if row is None:
            raise ModelError(f"Id {id} does not exist in Model {cls.table_name}")
        instance = cls().set_from_row(row)
        cls._db.cache_put(instance)
        return instance

    def remove(self) -> Model:
        """Delete this instance's row when ``id`` is not ``None``.

        Cascades: removes child rows whose foreign keys point at this
        instance (recursively), then deletes this row and evicts it from
        the identity cache. Each statement commits independently.

        Returns:
            ``self`` for fluent chaining.
        """
        type(self)._check_schema()
        if self._id is None:
            return self
        self._cascade_remove_children(seen=set())
        table = _quote_ident(type(self).table_name)
        stmt = f'DELETE FROM {table} WHERE "ID" = ?'
        self._db.execute(stmt, (self._id,))
        self._db.cache_evict(type(self), self._id)
        return self

    def _cascade_remove_children(self, seen: set[tuple[type, str]]) -> None:
        key = (type(self), self._id)  # type: ignore[arg-type]
        if key in seen:
            raise ModelError(
                f"Relationship cycle detected while removing {type(self).__name__} "
                f"id={self._id}"
            )
        seen.add(key)

        parent_cls = type(self)
        for model_cls in list(self._db._models):
            fk_attrs = getattr(model_cls, "_fk_attrs", {})
            for fk_attr, fk_parent in fk_attrs.items():
                if fk_parent is not parent_cls:
                    continue
                for child in model_cls._select_by_fk(fk_attr, self._id):  # type: ignore[arg-type]
                    child._cascade_remove_children(seen)
                    child_table = _quote_ident(model_cls.table_name)
                    stmt = f'DELETE FROM {child_table} WHERE "ID" = ?'
                    self._db.execute(stmt, (child.id,))
                    if child.id is not None:
                        self._db.cache_evict(model_cls, child.id)

    @classmethod
    def _select_by_fk(cls, fk_attr: str, parent_id: str) -> list[Model]:
        """Load rows whose foreign-key column equals ``parent_id``."""
        cls._check_schema()
        table = _quote_ident(cls.table_name)
        sql_name = _quote_ident(cls._column_names[fk_attr])
        stmt = f"SELECT * FROM {table} WHERE {sql_name} = ?"
        models: list[Model] = []
        for row in cls._db.execute(stmt, (parent_id,)):
            row_id = row["ID"]
            cached = cls._db.cache_get(cls, row_id)
            if cached is not None:
                models.append(cached)  # type: ignore[arg-type]
                continue
            model = cls().set_from_row(row)
            cls._db.cache_put(model)
            models.append(model)
        return models

    def set_from_row(self, row: Any) -> Model:
        """Hydrate this instance from a SQLite row mapping.

        Sets ``_id`` from the ``ID`` column and each annotated attribute
        via the corresponding Column codec. Foreign keys store the parent
        id for lazy resolution.

        Args:
            row: A ``sqlite3.Row`` (or mapping) with SQL column names.

        Returns:
            ``self`` for fluent chaining.
        """
        self._id = row["ID"]
        for attr, column in type(self)._columns.items():
            sql_name = type(self)._column_names[attr]
            value = column.from_sql(row[sql_name])
            if attr in type(self)._fk_attrs:
                self._fk_ids[attr] = value
                obj_attr = f"_{attr}_obj"
                if hasattr(self, obj_attr):
                    delattr(self, obj_attr)
            else:
                setattr(self, attr, value)
        return self

    def set(self, values: dict[str, Any]) -> Model:
        """Populate persisted attributes from a dict of Python values.

        Only keys that match annotated model fields are applied. Scalar
        values must already be the correct Python types. Foreign keys
        accept a parent id ``str`` or a parent model instance. Optional
        foreign keys also accept ``None``.

        Args:
            values: Attribute name → value mapping.

        Returns:
            ``self`` for fluent chaining.
        """
        for attr in type(self)._columns:
            if attr not in values:
                continue
            value = values[attr]
            if attr in type(self)._fk_attrs:
                parent_cls = type(self)._fk_attrs[attr]
                if value is None or isinstance(value, parent_cls):
                    setattr(self, attr, value)
                elif isinstance(value, str):
                    self._fk_ids[attr] = value
                    obj_attr = f"_{attr}_obj"
                    if hasattr(self, obj_attr):
                        delattr(self, obj_attr)
                else:
                    raise ModelError(
                        f"{type(self).__name__}.{attr} expects "
                        f"{parent_cls.__name__} or id str, got {type(value).__name__}"
                    )
            else:
                setattr(self, attr, value)
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return persisted attributes as a dict of Python values.

        Includes annotated model fields only (not ``id``). Foreign keys
        are exported as parent id strings, or ``None`` when unset or
        nullable and null. Virtual collections are omitted.
        Values are native Python types (``date``, ``time``, ``datetime``,
        ``bool``, etc.), not SQL encodings.
        """
        result: dict[str, Any] = {}
        for attr in type(self)._columns:
            if attr in type(self)._fk_attrs:
                result[attr] = self._fk_sql_id(attr)
            else:
                result[attr] = getattr(self, attr)
        return result

    @classmethod
    def from_dict(
        cls, data: dict[str, Any] | list[dict[str, Any]]
    ) -> Model | list[Model]:
        """Create and save instance(s) from dict data.

        Accepts a single dict or a list of dicts. Each record is applied
        with :meth:`set` and then :meth:`save`. List items are saved
        sequentially (each ``save`` commits independently); a failure
        mid-list can leave earlier rows persisted.

        Args:
            data: One attribute dict, or a list of them.

        Returns:
            The saved instance for a single dict, or a list of saved
            instances for a list of dicts.
        """
        if isinstance(data, dict):
            return cls().set(data).save()

        return [cls().set(record).save() for record in data]

    @classmethod
    def select(
        cls,
        order_by: list[str] | None = None,
        filter: Callable[[Model], bool] | None = None,
    ) -> list[Model]:
        """Return all rows as model instances, optionally ordered and filtered.

        Fetches every row (``SELECT *``), then applies ``filter`` in Python
        if provided. There is no SQL ``WHERE`` DSL in v1. Rows already in
        the identity cache are returned as-is (in-memory attributes win).

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
            row_id = row["ID"]
            cached = cls._db.cache_get(cls, row_id)
            if cached is not None:
                model = cached  # type: ignore[assignment]
            else:
                model = cls().set_from_row(row)
                cls._db.cache_put(model)
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
