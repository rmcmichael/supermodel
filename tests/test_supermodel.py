"""Package exports and cross-slice integration tests."""

from datetime import date
from datetime import datetime
from datetime import time
from datetime import timezone

import pytest

import supermodel
from supermodel import Database
from supermodel import Model
from supermodel import ModelError


def test_version():
    assert supermodel.__version__ == "0.1.0"


def test_public_exports():
    assert supermodel.Database is Database
    assert supermodel.Model is Model
    assert supermodel.ModelError is ModelError
    assert set(supermodel.__all__) == {
        "Database",
        "Model",
        "ModelError",
        "__version__",
    }


def test_public_symbols_match_submodules():
    from supermodel.database import Database as DatabaseFromModule
    from supermodel.model import Model as ModelFromModule
    from supermodel.model import ModelError as ModelErrorFromModule

    assert Database is DatabaseFromModule
    assert Model is ModelFromModule
    assert ModelError is ModelErrorFromModule


def test_integration_fluent_persist_and_query(db):
    class User(Model):
        name: str = ""
        active: bool = False
        joined: date = date(1, 1, 1)

    class Item(Model):
        title: str = ""
        price: float = 0.0
        available: datetime = datetime(1, 1, 1, tzinfo=timezone.utc)
        note: str | None = None

    alice = User().set(
        {"name": "Alice", "active": True, "joined": date(2024, 1, 2)}
    ).save()
    bob = User().set(
        {"name": "Bob", "active": False, "joined": date(2024, 2, 3)}
    ).save()
    Item().set(
        {
            "title": "widget",
            "price": 1.5,
            "available": datetime(
                2024, 3, 15, 14, 30, 5, 123456, tzinfo=timezone.utc
            ),
            "note": None,
        }
    ).save()
    Item().set(
        {
            "title": "gadget",
            "price": 2.25,
            "available": datetime(
                2024, 4, 1, 9, 0, 0, tzinfo=timezone.utc
            ),
            "note": "spare",
        }
    ).save()

    assert User.count == 2
    assert Item.count == 2

    loaded = User.get(alice.id)
    assert loaded.to_dict() == {
        "name": "Alice",
        "active": True,
        "joined": date(2024, 1, 2),
    }

    active_users = User.select(
        order_by=["name"],
        filter=lambda u: u.active,
    )
    assert [u.name for u in active_users] == ["Alice"]

    items = Item.select(order_by=["-price"])
    assert [i.title for i in items] == ["gadget", "widget"]
    assert items[1].note is None
    assert items[1].available == datetime(
        2024, 3, 15, 14, 30, 5, 123456, tzinfo=timezone.utc
    )

    bob.remove()
    assert User.count == 1
    with pytest.raises(ModelError, match="does not exist"):
        User.get(bob.id)


def test_integration_schema_and_on_table_created_via_public_api(db, tmp_path):
    db.path = str(tmp_path / "integration.db")
    assert db.table_exists("THING") is False
    seeded: list[str] = []

    class Thing(Model):
        label: str = ""
        alarm: time = time(0, 0, 0)

        def on_table_created(self) -> None:
            seeded.append("created")
            type(self)().set(
                {"label": "seed", "alarm": time(8, 30, 0, 123456)}
            ).save()

    # Connection already open: registration should create the table and run the hook.
    assert seeded == ["created"]
    assert Thing.count == 1
    assert db.table_exists("THING")
    assert db.column_exists("THING", "ID")
    assert db.column_exists("THING", "LABEL")
    assert db.column_exists("THING", "ALARM")

    loaded = Thing.select()[0]
    assert loaded.label == "seed"
    assert loaded.alarm == time(8, 30, 0, 123456)
