from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone

import pytest

from supermodel.column import BoolColumn
from supermodel.column import DateColumn
from supermodel.column import DateTimeColumn
from supermodel.column import FKColumn
from supermodel.column import FloatColumn
from supermodel.column import IntColumn
from supermodel.column import TextColumn
from supermodel.column import TimeColumn


@pytest.mark.parametrize(
    ("column", "expected_ddl"),
    [
        (IntColumn(), "INTEGER NOT NULL DEFAULT 0"),
        (IntColumn(nullable=True), "INTEGER DEFAULT NULL"),
        (FloatColumn(), "REAL NOT NULL DEFAULT 0.0"),
        (FloatColumn(nullable=True), "REAL DEFAULT NULL"),
        (DateColumn(), 'TEXT NOT NULL DEFAULT "0001-01-01"'),
        (DateColumn(nullable=True), "TEXT DEFAULT NULL"),
        (TimeColumn(), 'TEXT NOT NULL DEFAULT "00:00:00.000000"'),
        (TimeColumn(nullable=True), "TEXT DEFAULT NULL"),
        (
            DateTimeColumn(),
            'TEXT NOT NULL DEFAULT "0001-01-01T00:00:00.000000+00:00"',
        ),
        (DateTimeColumn(nullable=True), "TEXT DEFAULT NULL"),
        (BoolColumn(), "INTEGER NOT NULL DEFAULT 0"),
        (BoolColumn(nullable=True), "INTEGER DEFAULT NULL"),
        (TextColumn(), 'TEXT NOT NULL DEFAULT ""'),
        (TextColumn(nullable=True), "TEXT DEFAULT NULL"),
        (FKColumn(), 'TEXT NOT NULL DEFAULT ""'),
        (FKColumn(nullable=True), "TEXT DEFAULT NULL"),
    ],
)
def test_column_ddl(column, expected_ddl):
    assert column.ddl == expected_ddl


def test_int_column_round_trip():
    column = IntColumn()
    assert column.to_sql(42) == 42
    assert column.from_sql(42) == 42


def test_int_column_rejects_bool_and_wrong_types():
    column = IntColumn()
    with pytest.raises(TypeError):
        column.to_sql(True)
    with pytest.raises(TypeError):
        column.to_sql(3.14)
    with pytest.raises(TypeError):
        column.from_sql(True)


def test_float_column_round_trip():
    column = FloatColumn()
    assert column.to_sql(3.5) == 3.5
    assert column.from_sql(3.5) == 3.5
    assert column.to_sql(2) == 2.0
    assert column.from_sql(2) == 2.0


def test_float_column_rejects_bool():
    column = FloatColumn()
    with pytest.raises(TypeError):
        column.to_sql(True)


def test_bool_column_round_trip():
    column = BoolColumn()
    assert column.to_sql(True) == 1
    assert column.to_sql(False) == 0
    assert column.from_sql(1) is True
    assert column.from_sql(0) is False


def test_bool_column_rejects_non_bool_python_and_invalid_sql():
    column = BoolColumn()
    with pytest.raises(TypeError):
        column.to_sql(1)
    with pytest.raises(TypeError):
        column.from_sql(2)


def test_text_column_round_trip():
    column = TextColumn()
    assert column.to_sql("hello") == "hello"
    assert column.from_sql("hello") == "hello"
    assert column.to_sql("") == ""


def test_date_column_round_trip():
    column = DateColumn()
    value = date(2024, 3, 15)
    assert column.to_sql(value) == "2024-03-15"
    assert column.from_sql("2024-03-15") == value


def test_date_column_rejects_datetime():
    column = DateColumn()
    with pytest.raises(TypeError):
        column.to_sql(datetime(2024, 3, 15, tzinfo=timezone.utc))


def test_time_column_round_trip():
    column = TimeColumn()
    value = time(14, 30, 5, 123456)
    assert column.to_sql(value) == "14:30:05.123456"
    assert column.from_sql("14:30:05.123456") == value


def test_time_column_rejects_timezone_aware():
    column = TimeColumn()
    aware = time(14, 30, 5, 123456, tzinfo=timezone.utc)
    with pytest.raises(TypeError, match="naive"):
        column.to_sql(aware)


def test_datetime_column_round_trip_aware():
    column = DateTimeColumn()
    value = datetime(2024, 3, 15, 14, 30, 5, 123456, tzinfo=timezone.utc)
    encoded = column.to_sql(value)
    assert encoded == "2024-03-15T14:30:05.123456+00:00"
    assert column.from_sql(encoded) == value


def test_datetime_column_preserves_non_utc_offset():
    column = DateTimeColumn()
    offset = timezone(timedelta(hours=-5))
    value = datetime(2024, 3, 15, 9, 30, 0, 0, tzinfo=offset)
    encoded = column.to_sql(value)
    assert encoded == "2024-03-15T09:30:00.000000-05:00"
    assert column.from_sql(encoded) == value


def test_datetime_column_coerces_naive_to_utc():
    column = DateTimeColumn()
    naive = datetime(2024, 3, 15, 14, 30, 5, 123456)
    encoded = column.to_sql(naive)
    assert encoded == "2024-03-15T14:30:05.123456+00:00"
    assert column.from_sql(encoded) == naive.replace(tzinfo=timezone.utc)


def test_datetime_column_from_sql_coerces_naive_string():
    column = DateTimeColumn()
    result = column.from_sql("2024-03-15T14:30:05.123456")
    assert result == datetime(2024, 3, 15, 14, 30, 5, 123456, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "column",
    [
        IntColumn(),
        FloatColumn(),
        BoolColumn(),
        TextColumn(),
        FKColumn(),
        DateColumn(),
        TimeColumn(),
        DateTimeColumn(),
    ],
)
def test_non_nullable_rejects_none(column):
    with pytest.raises(TypeError, match="NULL"):
        column.to_sql(None)
    with pytest.raises(TypeError, match="NULL"):
        column.from_sql(None)


@pytest.mark.parametrize(
    "column",
    [
        IntColumn(nullable=True),
        FloatColumn(nullable=True),
        BoolColumn(nullable=True),
        TextColumn(nullable=True),
        FKColumn(nullable=True),
        DateColumn(nullable=True),
        TimeColumn(nullable=True),
        DateTimeColumn(nullable=True),
    ],
)
def test_nullable_accepts_none(column):
    assert column.to_sql(None) is None
    assert column.from_sql(None) is None
