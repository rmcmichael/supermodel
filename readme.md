# SuperModel

Simple, model-first SQLite for Python.

SuperModel (`supermodel`) persists plain Python classes in SQLite. Models define the schema; annotated attributes become columns. Requires Python 3.13+.

## Highlights

- **Model-first** — declare typed fields on a `Model` subclass; the library creates and evolves tables (additive only)
- **Fluent API** — chain instance methods, for example `User().set({...}).save()`
- **UUIDv7 identity** — read-only string `id`, assigned on first insert
- **Type-hinted columns** — `str`, `int`, `float`, `bool`, `date`, `time`, `datetime`, and `X | None` for nullables
- **Automatic schema** — models register on subclassing; tables are ensured when the database connects
- **Transactions** — `with Database().transaction(): ...` for multi-row work

```python
from supermodel import Database, Model

Database().path = "app.db"

class User(Model):
    name: str = ""
    active: bool = False

user = User().set({"name": "Ada", "active": True}).save()
loaded = User.get(user.id)
```

See [doc/design.md](doc/design.md) for the full design.
