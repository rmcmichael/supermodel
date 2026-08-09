# SuperModel Design Notes

Easy Python class-oriented, model-first access to SQLite

## Database

- TODO: Support synchronizing multiple copies of a database through an intermediary web service (not designed yet)
- Outside an explicit transaction, `execute()` commits after each statement (same granular-commit behavior as today)
- Provide a transaction context manager on the Database singleton, for example:

```python
with Database().transaction():
    user.set({...}).save()
    item.set({...}).save()
```

- While inside `transaction()`, statements participate in one transaction: commit on clean exit, roll back if the block exits with an exception
- Nested `transaction()` blocks are not required for v1; document that callers should not nest them
- Needed for multi-row operations such as `from_dict` lists and future sync work; implement with the rest of the design changes

## Model

### Differences in approach from the original implementation

- IDs are now UUIDv7
  - Previously, models were identified by an auto-incrementing database column
  - Now, models are identified by a string populated by a UUIDv7 value
  - On initialization, id is `None` (stored privately as `_id`)
  - id is exposed as a read-only property (getter, no setter); callers cannot assign it
  - `save()` follows the original pattern: if `id is None`, insert; otherwise update
  - On first insert, the library generates a UUIDv7, assigns `_id`, and includes `ID` in the `INSERT`
  - When hydrating from the database (`get` / `set_from_row` / `select`), the library sets `_id` from the row
  - The primary key for the model's backing table will be a TEXT column named `ID`
  - Requires Python 3.13+ for `uuid.uuid7`

- Type Inference
  - Previously, the type of the table column was determined by the value that an attribute was initialized with.
  - Now the type of the table column will be determined by the type hint associated with the class attribute
  - Example: `name: str = ""` will result in a TEXT column in the backing table

- Null Columns
  - Previously, null columns were not allowed. Every column had to be populated with a value
  - This was largely because type inference required an initial column value
  - Now, if the type hint for an attribute allows `None` (for example `str | None`), the column in the backing table is allowed to contain a null
  - Example: `name: str | None = None` will create a TEXT column that allows nulls
  - Use `X | None` for nullable attributes in all cases (not `Optional[X]` or other spellings)

- Schema Updates
  - Previously, the calling application had to call the `check_schema()` method for every model
  - Now, `Model.__init_subclass__` registers each model with the Database singleton
  - `_check_schema()` is private and idempotent
  - `_check_schema()` runs when a model is registered if a connection is already open, and for all registered models when the connection is first opened (so importing models before `Database.path` is set still works)
  - If the table does not exist, create it in one `CREATE TABLE` with the `ID` primary key and all known model columns
  - If the table exists, add any missing columns with `ALTER TABLE ... ADD COLUMN` (additive only)
  - Schema evolution non-goals: no column type changes, renames, or drops
  - `on_table_created()` runs only when the table was newly created; subclasses may override it for seed data or similar setup

- Table and Column Names
  - By default, table names will be derived from the model class name as all-caps snake case
  - By default, column names will be derived from the attribute name as all-caps snake case
  - The user can specify the table name with the `table_name` property (getter and setter)
  - The user can override a column name with `column_name(attribute_name, column_name)`

### Public Model API

- Prefer a conversational / fluent style: mutating instance methods return `self` so callers can chain (for example `User().set({...}).save()`)
- No `success=` callbacks on Model or Database methods. Rely on return values and chaining; callbacks can be added later if needed
- Library-raised errors use `ModelError` (renamed from the original `ModelException`)
- `save()` — if `id is None`, insert (assign UUIDv7); otherwise update. Returns `self`
- `get(id)` — classmethod; loads the row for `id` into a new instance and returns it. Raises `ModelError` if the id does not exist
- The original `getone()` is not carried forward
- `remove()` — deletes the row for this instance when `id` is not `None`. Returns `self`
- `select(order_by=None, filter=None)` — classmethod; returns a list of model instances
  - `order_by`: optional list of attribute names for SQL `ORDER BY`. Prefix with `-` for descending and `+` (or no prefix) for ascending (same idea as the original library)
  - `filter`: optional callable `model -> bool` applied in Python after rows are fetched. Rename of the original `where` parameter so it is not confused with SQL `WHERE`
  - Filtering is post-fetch (`SELECT *`, then keep matching instances). No SQL `WHERE` DSL in v1
  - The original in-library `groupby` post-processing is not carried forward; callers can group results themselves
  - Example: `User.select(order_by=["-last_login", "name"], filter=lambda u: u.active)`
- `count` — class-level property; number of rows in the model's table (for example `User.count`)
- `set(values)` — populate attributes from a `dict`; returns `self`
  - Values are expected as real Python types matching the attribute annotations
  - No free-form string parsing (for example no `dateparser`); callers convert strings before `set`
- `to_dict()` — return a `dict` of model attributes with Python values (including `date` / `time` / `datetime` / `bool`). Replaces the original `dict` property and `json_values`; no separate JSON export helper (callers may use `json.dumps` themselves if needed)
- `from_dict(data)` — classmethod; replaces the original `load()`
  - Accepts a single `dict` or a list of `dict`s
  - For each record: create an instance, `set(...)`, `save()`
  - A single `dict` returns that saved instance; a list returns a list of saved instances
  - No `json_file` parameter; callers that have JSON should `json.load` / `json.loads` themselves and pass the resulting dict(s)

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

- The Column DDL scheme above is unchanged: required types use `NOT NULL DEFAULT <type sentinel>`; optional types use `DEFAULT NULL`
- SQL `DEFAULT` values exist mainly so `ALTER TABLE ... ADD COLUMN` can succeed on a non-empty table (SQLite requires a default when adding a `NOT NULL` column). For existing rows, the new column is filled with that SQL default
- Application code should rely on Python attribute defaults from the model class (for example `name: str = ""`, `active: bool = False`), not on the SQL sentinels
- Type-level SQL sentinels such as `0`, `""`, `"0001-01-01"`, and `"00:00:00.000000"` must not be treated as meaningful application values
- Per-field Python defaults are not mirrored into the SQL `DEFAULT` clause; constructors and instance initialization populate attribute values before insert

### Implementation Notes on Types

- Every model has a private `_columns` map that will contain one item per persisted user attribute
- Only annotated model fields are included; `_id` is handled separately from `_columns`
- The key will be the attribute name
- Each item will be an instance of a subclass of Column by type
- The Column subclasses are IntColumn, FloatColumn, DateColumn, TimeColumn, DateTimeColumn, BoolColumn, and TextColumn
- Model will delegate the DDL and value translation activities into those classes
- After a table is newly created, call `on_table_created()` on a fresh instance of the model class

### Date, Time, and DateTime Storage

- **Breaking change** from the original library: stored TEXT formats are not wire-compatible with old databases
  - Original `datetime`: `YYYY-MM-DD HH:MM:SS.ffffff` (naive, space separator)
  - Original `time`: `HH:MM:SS` (no microseconds)
  - Original `date`: `YYYY-MM-DD` (unchanged)
- Canonical TEXT formats for the new library (same strings used for DDL defaults and codecs):
  - `datetime.date`: `YYYY-MM-DD`
  - `datetime.time`: `HH:MM:SS.ffffff` (microseconds included; naive, no timezone)
  - `datetime.datetime`: `YYYY-MM-DDTHH:MM:SS.ffffff±HH:MM` (ISO-8601 with offset; timezone-aware)
- `time` attributes are always naive (no timezone)
- `datetime` attributes are always timezone-aware
- If a naive `datetime` is assigned, coerce it to UTC (treat the naive value as UTC and attach `timezone.utc`). Do not raise; keep the API simple

## Implementation Plan

Implement against this design in steps. **Each step includes unit tests for that slice** (not deferred to the end).

1. **Database** — DONE: model registry hooks, `transaction()`, schema ensure on first connection / late registration; unit tests for registry, transactions, and schema timing
2. **Column types** — DONE: DDL fragments and to/from SQL codecs; unit tests for each column type’s DDL and value conversion
3. **Model core** — DONE: annotations → `_columns`, `__init_subclass__`, identity, `save` / `get` / `remove`; unit tests for persistence and identity rules
4. **Query and helpers** — DONE: `select`, `count`, `set`, `to_dict`, `from_dict`; unit tests for query/helper behavior
5. **Package exports** — expose the public API from the package (`Database`, `Model`, `ModelError`, etc.) and add any remaining integration-style tests across slices
