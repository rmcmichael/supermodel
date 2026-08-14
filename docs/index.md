# SuperModel

Simple, model-first SQLite for Python.

SuperModel (`supermodel`) persists plain Python classes in SQLite. Models
define the schema; annotated attributes become columns. Requires Python 3.13+.

## Highlights

- **Model-first** — declare typed fields on a `Model` subclass; the library
  creates and evolves tables (additive only)
- **Fluent API** — chain instance methods, for example
  `User().set({...}).save()`
- **UUIDv7 identity** — read-only string `id`, assigned on first insert
- **Type-hinted columns** — `str`, `int`, `float`, `bool`, `date`, `time`,
  `datetime`, and `X | None` for nullables; model types for foreign keys
  (`Parent | None` for optional); `list[Model]` for virtual reverse relations
- **Automatic schema** — models register on subclassing; tables are ensured
  when the database connects
- **Identity cache** — one in-memory instance per `(model, id)` while referenced
- **Cascade delete** — `remove()` deletes dependent children via foreign keys

```python
from supermodel import Database, Model

Database().path = "app.db"

class User(Model):
    name: str = ""
    active: bool = False

user = User().set({"name": "Ada", "active": True}).save()
loaded = User.get(user.id)
```

```{toctree}
:maxdepth: 2
:caption: Contents

design
api
```
