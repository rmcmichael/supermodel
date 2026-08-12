# SuperModel Design

Easy Python class-oriented, model-first access to SQLite.

Models define the schema. Annotated class attributes become table columns. Persistence uses a fluent instance API (`User().set({...}).save()`). The library targets Python 3.13+ (for `uuid.uuid7`).

## Goals

- Model-first: schema comes from typed model classes
- Simple: plain Python classes, fluent chaining, return values over callbacks
- Synchronizable (future): support syncing multiple database copies through an intermediary web service (not designed yet)

## Database

`Database` is a process-wide singleton. Call `Database()` anywhere to get the shared instance.

- `Database.path` defaults to `None`; callers must set it before the first connection. Connecting with `path is None` raises `RuntimeError`. Use `":memory:"` for an in-memory database
- Outside an explicit transaction, `execute()` commits after each statement
- Provide a transaction context manager:

```python
with Database().transaction():
    user.set({...}).save()
    item.set({...}).save()
```

- Inside `transaction()`, statements participate in one transaction: commit on clean exit, roll back if the block exits with an exception
- Nested `transaction()` blocks are not supported in v1; callers must not nest them
- Needed for multi-row operations such as `from_dict` lists and future sync work
- Not thread-safe in v1 (single-thread use). A future design may move connection work onto a dedicated thread with a query queue

## Model

### Identity

- Models are identified by a string primary key populated with a UUIDv7
- On initialization, `id` is `None` (stored privately as `_id`)
- `id` is a read-only property (getter only); callers cannot assign it
- `save()`: if `id is None`, insert; otherwise update
- On first insert, the library generates a UUIDv7, assigns `_id`, and includes `ID` in the `INSERT`
- When hydrating from the database (`get` / `set_from_row` / `select`), the library sets `_id` from the row
- The primary key for the model's backing table is a TEXT column named `ID`

### Schema from Annotations

- Column types are determined by the type hint on each class attribute (for example `name: str = ""` → TEXT)
- Only annotated model fields are persisted; `_id` is handled separately from `_columns`
- Attribute names beginning with `_` are not persisted (no column). Use this for transient / non-persistent instance state (for example `_cache: dict = {}`)
- If the type hint allows `None` (for example `str | None`), the column may be null
- Use `X | None` for nullable attributes (not `Optional[X]` or other spellings)
- Example: `name: str | None = None` creates a TEXT column that allows nulls
- An annotated field whose type is not one of the supported mappings (see [Model Attribute to Table Column Mapping](#model-attribute-to-table-column-mapping)) raises `ModelError` when the model class is defined, not later at save time
- Declaring a persisted field named `id` also raises `ModelError` (reserved for the read-only identity property)

### Schema Lifecycle

- `Model.__init_subclass__` registers each model with the Database singleton
- `_check_schema()` is private and idempotent
- `_check_schema()` runs when a model is registered if a connection is already open, and for all registered models when the connection is first opened (so importing models before `Database.path` is set still works)
- If the table does not exist, create it in one `CREATE TABLE` with the `ID` primary key and all known model columns
- If the table exists, add any missing columns with `ALTER TABLE ... ADD COLUMN` (additive only)
- Schema evolution non-goals: no column type changes, renames, or drops
- `on_table_created()` runs only when the table was newly created; subclasses may override it for seed data or similar setup

### Table and Column Names

- By default, table names are derived from the model class name as all-caps snake case
- By default, column names are derived from the attribute name as all-caps snake case
- Override the table name with the `table_name` property (getter and setter)
- Override a column name with `column_name(attribute_name, column_name)`

### Public Model API

Prefer a conversational / fluent style: mutating instance methods return `self` so callers can chain (for example `User().set({...}).save()`).

Library-raised errors use `ModelError`. No `success=` callbacks on Model or Database methods; rely on return values and chaining.

| API | Behavior |
| --- | --- |
| `save()` | If `id is None`, insert (assign UUIDv7); otherwise update. Returns `self` |
| `get(id)` | Classmethod; loads the row for `id` into a new instance. Raises `ModelError` if missing |
| `remove()` | Deletes the row for this instance when `id` is not `None`. Returns `self` |
| `select(order_by=None, filter=None)` | Classmethod; returns a list of model instances |
| `count` | Class-level property; row count for the model's table (for example `User.count`) |
| `set(values)` | Populate attributes from a `dict`; returns `self` |
| `to_dict()` | Return a `dict` of model attributes with Python values |
| `from_dict(data)` | Classmethod; create and save from a `dict` or list of `dict`s |

**`select` details**

- `order_by`: optional list of attribute names for SQL `ORDER BY`. Prefix with `-` for descending and `+` (or no prefix) for ascending
- `filter`: optional callable `model -> bool` applied in Python after rows are fetched
- Filtering is post-fetch (`SELECT *`, then keep matching instances). No SQL `WHERE` DSL in v1
- Example: `User.select(order_by=["-last_login", "name"], filter=lambda u: u.active)`

**`set` / `to_dict` / `from_dict` details**

- `set` expects real Python types matching the attribute annotations; callers convert strings before `set`
- `to_dict` returns Python values (including `date` / `time` / `datetime` / `bool`). No separate JSON export helper; callers may use `json.dumps` if needed
- `from_dict` accepts a single `dict` or a list of `dict`s. For each record: create an instance, `set(...)`, `save()`. A single `dict` returns that saved instance; a list returns a list of saved instances (list saves run inside one `Database.transaction()`). Callers that have JSON should `json.load` / `json.loads` themselves and pass the resulting dict(s)

### Model Attribute to Table Column Mapping

| Python Type                 | Column DDL                                               |
| --------------------------- | -------------------------------------------------------- |
| int                         | INTEGER NOT NULL DEFAULT 0                               |
| int \| None                 | INTEGER DEFAULT NULL                                     |
| float                       | REAL NOT NULL DEFAULT 0.0                                |
| float \| None               | REAL DEFAULT NULL                                        |
| datetime.date               | TEXT NOT NULL DEFAULT "0001-01-01"                       |
| datetime.date \| None       | TEXT DEFAULT NULL                                        |
| datetime.time               | TEXT NOT NULL DEFAULT "00:00:00.000000"                  |
| datetime.time \| None       | TEXT DEFAULT NULL                                        |
| datetime.datetime           | TEXT NOT NULL DEFAULT "0001-01-01T00:00:00.000000+00:00" |
| datetime.datetime \| None   | TEXT DEFAULT NULL                                        |
| bool                        | INTEGER NOT NULL DEFAULT 0                               |
| bool \| None                | INTEGER DEFAULT NULL                                     |
| str                         | TEXT NOT NULL DEFAULT ""                                 |
| str \| None                 | TEXT DEFAULT NULL                                        |

### Defaults

- Required types use `NOT NULL DEFAULT <type sentinel>`; optional types use `DEFAULT NULL`
- SQL `DEFAULT` values exist mainly so `ALTER TABLE ... ADD COLUMN` can succeed on a non-empty table (SQLite requires a default when adding a `NOT NULL` column). For existing rows, the new column is filled with that SQL default
- Application code should rely on Python attribute defaults from the model class (for example `name: str = ""`, `active: bool = False`), not on the SQL sentinels
- Type-level SQL sentinels such as `0`, `""`, `"0001-01-01"`, and `"00:00:00.000000"` must not be treated as meaningful application values
- Per-field Python defaults are not mirrored into the SQL `DEFAULT` clause; constructors and instance initialization populate attribute values before insert

### Column Strategies

- Every model has a private `_columns` map with one entry per persisted user attribute
- The key is the attribute name; each value is a subclass of `Column` by type
- Column subclasses: `IntColumn`, `FloatColumn`, `DateColumn`, `TimeColumn`, `DateTimeColumn`, `BoolColumn`, `TextColumn`
- Model delegates DDL and value translation to those classes
- After a table is newly created, call `on_table_created()` on a fresh instance of the model class

### Date, Time, and DateTime Storage

Canonical TEXT formats (same strings used for DDL defaults and codecs):

- `datetime.date`: `YYYY-MM-DD`
- `datetime.time`: `HH:MM:SS.ffffff` (microseconds included; naive, no timezone)
- `datetime.datetime`: `YYYY-MM-DDTHH:MM:SS.ffffff±HH:MM` (ISO-8601 with offset; timezone-aware)

Rules:

- `time` attributes are always naive (no timezone)
- `datetime` attributes are always timezone-aware
- If a naive `datetime` is assigned, coerce it to UTC (treat the naive value as UTC and attach `timezone.utc`). Do not raise; keep the API simple

## Package Exports

Public API from the `supermodel` package: `Database`, `Model`, `ModelError`, and `__version__`.

## Out of Scope (v1)

- Nested transactions
- SQL `WHERE` DSL (use post-fetch `filter` instead)
- Schema renames, type changes, or drops
- Thread-safe Database access
- Multi-copy sync over a web service (noted as future work; not designed)

## Implemented

The following design elements are implemented in `src/supermodel` with unit and integration tests under `tests/`:

- **Database** — singleton, path gating, model registry, `transaction()`, schema ensure on first connection / late registration
- **Column types** — DDL fragments and to/from SQL codecs for int, float, bool, str, date, time, datetime (nullable and required)
- **Model core** — annotations → `_columns`, `__init_subclass__`, UUIDv7 identity, `save` / `get` / `remove`, table/column naming, additive schema, `on_table_created`
- **Query and helpers** — `select`, `count`, `set`, `to_dict`, `from_dict` (including transactional list import)
- **Package exports** — `Database`, `Model`, `ModelError`, `__version__` from `supermodel`

Not yet implemented (design only):

- Synchronizing multiple database copies through an intermediary web service
- Dedicated Database worker thread / query queue
