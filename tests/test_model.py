from datetime import date
from datetime import datetime
from datetime import time
from datetime import timezone
from uuid import UUID

import pytest

from supermodel.column import BoolColumn
from supermodel.column import DateColumn
from supermodel.column import DateTimeColumn
from supermodel.column import FloatColumn
from supermodel.column import IntColumn
from supermodel.column import TextColumn
from supermodel.column import TimeColumn
from supermodel.model import Model
from supermodel.model import ModelError


def test_columns_built_from_annotations(db):
    class Person(Model):
        name: str = ""
        age: int = 0
        score: float = 0.0
        active: bool = False
        born: date = date(2000, 1, 1)
        alarm: time = time(0, 0, 0)
        last_seen: datetime = datetime(2000, 1, 1, tzinfo=timezone.utc)
        nickname: str | None = None

    assert set(Person._columns) == {
        "name",
        "age",
        "score",
        "active",
        "born",
        "alarm",
        "last_seen",
        "nickname",
    }
    assert isinstance(Person._columns["name"], TextColumn)
    assert Person._columns["name"].nullable is False
    assert isinstance(Person._columns["age"], IntColumn)
    assert isinstance(Person._columns["score"], FloatColumn)
    assert isinstance(Person._columns["active"], BoolColumn)
    assert isinstance(Person._columns["born"], DateColumn)
    assert isinstance(Person._columns["alarm"], TimeColumn)
    assert isinstance(Person._columns["last_seen"], DateTimeColumn)
    assert isinstance(Person._columns["nickname"], TextColumn)
    assert Person._columns["nickname"].nullable is True


def test_columns_include_inherited_annotations(db):
    class Animal(Model):
        name: str = ""

    class Dog(Animal):
        breed: str = ""

    assert set(Dog._columns) == {"name", "breed"}
    assert set(Animal._columns) == {"name"}


def test_default_table_and_column_names(db):
    class OrderItem(Model):
        unit_price: float = 0.0

    assert OrderItem.table_name == "ORDER_ITEM"
    assert OrderItem._column_names["unit_price"] == "UNIT_PRICE"


def test_table_name_can_be_overridden(db):
    class Thing(Model):
        label: str = ""

    Thing.table_name = "CUSTOM_THING"
    Thing().label = "a"
    Thing().save()

    assert db.table_exists("CUSTOM_THING")
    assert not db.table_exists("THING")


def test_column_name_override(db):
    class Thing(Model):
        label: str = ""

    Thing.column_name("label", "TITLE")
    thing = Thing()
    thing.label = "hello"
    thing.save()

    assert db.column_exists("THING", "TITLE")
    assert not db.column_exists("THING", "LABEL")
    loaded = Thing.get(thing.id)
    assert loaded.label == "hello"


def test_column_name_rejects_unknown_attribute(db):
    class Thing(Model):
        label: str = ""

    with pytest.raises(ModelError, match="Unknown attribute"):
        Thing.column_name("missing", "X")


def test_id_starts_none_and_is_read_only(db):
    class Thing(Model):
        label: str = ""

    thing = Thing()
    assert thing.id is None
    with pytest.raises(AttributeError):
        thing.id = "nope"  # type: ignore[misc]


def test_save_insert_assigns_uuid7_and_persists(db):
    class Thing(Model):
        label: str = ""
        quantity: int = 0

    thing = Thing()
    thing.label = "alpha"
    thing.quantity = 3
    result = thing.save()

    assert result is thing
    assert thing.id is not None
    parsed = UUID(thing.id)
    assert parsed.version == 7

    row = db.execute(
        "SELECT ID, LABEL, QUANTITY FROM THING WHERE ID = ?", (thing.id,)
    ).fetchone()
    assert row["LABEL"] == "alpha"
    assert row["QUANTITY"] == 3


def test_save_update_and_get_round_trip(db):
    class Thing(Model):
        label: str = ""
        active: bool = False

    thing = Thing()
    thing.label = "before"
    thing.active = True
    thing.save()
    original_id = thing.id

    thing.label = "after"
    thing.active = False
    thing.save()
    assert thing.id == original_id

    loaded = Thing.get(original_id)
    assert loaded is not thing
    assert loaded.id == original_id
    assert loaded.label == "after"
    assert loaded.active is False


def test_get_missing_id_raises(db):
    class Thing(Model):
        label: str = ""

    # Ensure table exists.
    Thing()._check_schema()

    with pytest.raises(ModelError, match="does not exist"):
        Thing.get("01900000-0000-7000-8000-000000000000")


def test_remove_deletes_row(db):
    class Thing(Model):
        label: str = ""

    thing = Thing()
    thing.label = "gone"
    thing.save()
    row_id = thing.id

    result = thing.remove()
    assert result is thing

    with pytest.raises(ModelError, match="does not exist"):
        Thing.get(row_id)


def test_remove_with_no_id_is_noop(db):
    class Thing(Model):
        label: str = ""

    thing = Thing()
    assert thing.remove() is thing


def test_schema_creates_table_with_id_and_columns(db):
    class Thing(Model):
        label: str = ""
        size: int | None = None

    db._ensure_connection()

    assert db.table_exists("THING")
    assert db.column_exists("THING", "ID")
    assert db.column_exists("THING", "LABEL")
    assert db.column_exists("THING", "SIZE")

    info = {
        row[1]: row
        for row in db.execute("PRAGMA table_info(THING)").fetchall()
    }
    assert info["ID"][2] == "TEXT"
    assert info["ID"][5] == 1  # primary key
    assert "NOT NULL" in Thing._columns["label"].ddl
    assert "DEFAULT NULL" in Thing._columns["size"].ddl


def test_schema_adds_missing_columns(db):
    db.execute("CREATE TABLE THING (ID TEXT PRIMARY KEY, LABEL TEXT NOT NULL DEFAULT '')")

    class Thing(Model):
        label: str = ""
        extra: int = 0

    db._ensure_connection()

    assert db.column_exists("THING", "EXTRA")
    # Existing column is not dropped or retyped.
    assert db.column_exists("THING", "LABEL")


def test_on_table_created_runs_only_for_new_table(db, tmp_path):
    calls: list[str] = []
    db.path = str(tmp_path / "on_create.db")

    class Thing(Model):
        label: str = ""

        def on_table_created(self) -> None:
            calls.append("created")

    db._ensure_connection()
    assert calls == ["created"]

    db.close()
    db._ensure_connection()
    assert calls == ["created"]


def test_typed_values_round_trip(db):
    class Event(Model):
        title: str = ""
        day: date = date(1, 1, 1)
        at: time = time(0, 0, 0)
        when: datetime = datetime(1, 1, 1, tzinfo=timezone.utc)
        ok: bool = False
        note: str | None = None

    event = Event()
    event.title = "meet"
    event.day = date(2024, 3, 15)
    event.at = time(14, 30, 5, 123456)
    event.when = datetime(2024, 3, 15, 14, 30, 5, 123456, tzinfo=timezone.utc)
    event.ok = True
    event.note = None
    event.save()

    loaded = Event.get(event.id)
    assert loaded.title == "meet"
    assert loaded.day == date(2024, 3, 15)
    assert loaded.at == time(14, 30, 5, 123456)
    assert loaded.when == datetime(
        2024, 3, 15, 14, 30, 5, 123456, tzinfo=timezone.utc
    )
    assert loaded.ok is True
    assert loaded.note is None


def test_naive_datetime_coerced_on_save(db):
    class Event(Model):
        when: datetime = datetime(1, 1, 1, tzinfo=timezone.utc)

    event = Event()
    event.when = datetime(2024, 3, 15, 14, 30, 5, 123456)  # naive
    event.save()

    loaded = Event.get(event.id)
    assert loaded.when == datetime(
        2024, 3, 15, 14, 30, 5, 123456, tzinfo=timezone.utc
    )


def test_unsupported_annotation_raises(db):
    with pytest.raises(ModelError, match="Unsupported model field type"):

        class Bad(Model):
            values: list = []


def test_reserved_id_field_raises(db):
    with pytest.raises(ModelError, match="reserved"):

        class Bad(Model):
            id: str = ""


def test_set_populates_attributes_and_returns_self(db):
    class Thing(Model):
        label: str = ""
        quantity: int = 0
        note: str | None = None

    thing = Thing()
    result = thing.set({"label": "alpha", "quantity": 4, "note": None})

    assert result is thing
    assert thing.label == "alpha"
    assert thing.quantity == 4
    assert thing.note is None


def test_set_ignores_unknown_keys(db):
    class Thing(Model):
        label: str = ""

    thing = Thing().set({"label": "kept", "extra": "ignored"})
    assert thing.label == "kept"
    assert not hasattr(thing, "extra")


def test_set_save_chain(db):
    class Thing(Model):
        label: str = ""

    thing = Thing().set({"label": "chained"}).save()
    loaded = Thing.get(thing.id)
    assert loaded.label == "chained"


def test_to_dict_returns_python_values(db):
    class Event(Model):
        title: str = ""
        day: date = date(1, 1, 1)
        at: time = time(0, 0, 0)
        when: datetime = datetime(1, 1, 1, tzinfo=timezone.utc)
        ok: bool = False
        note: str | None = None

    event = Event().set(
        {
            "title": "meet",
            "day": date(2024, 3, 15),
            "at": time(14, 30, 5, 123456),
            "when": datetime(2024, 3, 15, 14, 30, 5, 123456, tzinfo=timezone.utc),
            "ok": True,
            "note": None,
        }
    )

    assert event.to_dict() == {
        "title": "meet",
        "day": date(2024, 3, 15),
        "at": time(14, 30, 5, 123456),
        "when": datetime(2024, 3, 15, 14, 30, 5, 123456, tzinfo=timezone.utc),
        "ok": True,
        "note": None,
    }
    assert "id" not in event.to_dict()


def test_from_dict_single_saves_and_returns_instance(db):
    class Thing(Model):
        label: str = ""
        quantity: int = 0

    thing = Thing.from_dict({"label": "one", "quantity": 1})

    assert isinstance(thing, Thing)
    assert thing.id is not None
    assert thing.label == "one"
    assert Thing.get(thing.id).quantity == 1


def test_from_dict_list_saves_all_and_returns_list(db):
    class Thing(Model):
        label: str = ""

    results = Thing.from_dict([{"label": "a"}, {"label": "b"}])

    assert isinstance(results, list)
    assert len(results) == 2
    assert [t.label for t in results] == ["a", "b"]
    assert all(t.id is not None for t in results)
    assert Thing.count == 2


def test_from_dict_list_uses_transaction(db):
    class Thing(Model):
        label: str = ""

    Thing._check_schema()
    original_set = Thing.set

    def failing_set(self, values):
        if values.get("label") == "b":
            raise RuntimeError("boom")
        return original_set(self, values)

    Thing.set = failing_set  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="boom"):
            Thing.from_dict([{"label": "a"}, {"label": "b"}])
    finally:
        Thing.set = original_set  # type: ignore[method-assign]

    assert Thing.count == 0


def test_count_property(db):
    class Thing(Model):
        label: str = ""

    assert Thing.count == 0
    Thing().set({"label": "a"}).save()
    Thing().set({"label": "b"}).save()
    assert Thing.count == 2
    assert Thing().count == 2


def test_select_returns_all_instances(db):
    class Thing(Model):
        label: str = ""

    Thing.from_dict([{"label": "a"}, {"label": "b"}])
    results = Thing.select()

    assert len(results) == 2
    assert {t.label for t in results} == {"a", "b"}


def test_select_order_by_asc_and_desc(db):
    class Thing(Model):
        label: str = ""
        rank: int = 0

    Thing.from_dict(
        [
            {"label": "c", "rank": 1},
            {"label": "a", "rank": 2},
            {"label": "b", "rank": 2},
        ]
    )

    by_label = Thing.select(order_by=["label"])
    assert [t.label for t in by_label] == ["a", "b", "c"]

    by_rank_desc = Thing.select(order_by=["-rank", "+label"])
    assert [(t.rank, t.label) for t in by_rank_desc] == [
        (2, "a"),
        (2, "b"),
        (1, "c"),
    ]


def test_select_order_by_unknown_attribute_raises(db):
    class Thing(Model):
        label: str = ""

    Thing._check_schema()
    with pytest.raises(ModelError, match="Unknown attribute"):
        Thing.select(order_by=["missing"])


def test_select_filter_applied_in_python(db):
    class Thing(Model):
        label: str = ""
        active: bool = False

    Thing.from_dict(
        [
            {"label": "a", "active": True},
            {"label": "b", "active": False},
            {"label": "c", "active": True},
        ]
    )

    active = Thing.select(filter=lambda t: t.active)
    assert [t.label for t in active] == ["a", "c"]


def test_select_order_by_uses_column_name_override(db):
    class Thing(Model):
        label: str = ""

    Thing.column_name("label", "TITLE")
    Thing.from_dict([{"label": "b"}, {"label": "a"}])

    results = Thing.select(order_by=["label"])
    assert [t.label for t in results] == ["a", "b"]
