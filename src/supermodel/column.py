"""Column types: DDL fragments and Python ↔ SQL value codecs."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timezone
from typing import Any
from typing import ClassVar


class Column(ABC):
    """Base strategy for a persisted model attribute.

    Owns the SQL type, nullability, DDL fragment (without the column name),
    and conversion between Python values and SQLite bind/row values.
    """

    sql_type: ClassVar[str]
    default_sql: ClassVar[str]

    def __init__(self, nullable: bool = False) -> None:
        self.nullable = nullable

    @property
    def ddl(self) -> str:
        """Return the type / nullability / default clause for CREATE or ALTER."""
        if self.nullable:
            return f"{self.sql_type} DEFAULT NULL"
        return f"{self.sql_type} NOT NULL DEFAULT {self.default_sql}"

    def to_sql(self, value: Any) -> Any:
        """Convert a Python attribute value to a SQLite bind value."""
        if value is None:
            if not self.nullable:
                raise TypeError(f"{type(self).__name__} does not allow NULL")
            return None
        return self._to_sql(value)

    def from_sql(self, value: Any) -> Any:
        """Convert a SQLite row value to a Python attribute value."""
        if value is None:
            if not self.nullable:
                raise TypeError(f"{type(self).__name__} does not allow NULL")
            return None
        return self._from_sql(value)

    @abstractmethod
    def _to_sql(self, value: Any) -> Any:
        """Convert a non-None Python value to SQL."""

    @abstractmethod
    def _from_sql(self, value: Any) -> Any:
        """Convert a non-None SQL value to Python."""


class IntColumn(Column):
    sql_type = "INTEGER"
    default_sql = "0"

    def _to_sql(self, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Expected int, got {type(value).__name__}")
        return value

    def _from_sql(self, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Expected int from SQL, got {type(value).__name__}")
        return value


class FloatColumn(Column):
    sql_type = "REAL"
    default_sql = "0.0"

    def _to_sql(self, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"Expected float, got {type(value).__name__}")
        return float(value)

    def _from_sql(self, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"Expected float from SQL, got {type(value).__name__}")
        return float(value)


class BoolColumn(Column):
    sql_type = "INTEGER"
    default_sql = "0"

    def _to_sql(self, value: Any) -> int:
        if not isinstance(value, bool):
            raise TypeError(f"Expected bool, got {type(value).__name__}")
        return 1 if value else 0

    def _from_sql(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return value == 1
        raise TypeError(f"Expected 0 or 1 from SQL, got {value!r}")


class TextColumn(Column):
    sql_type = "TEXT"
    default_sql = '""'

    def _to_sql(self, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError(f"Expected str, got {type(value).__name__}")
        return value

    def _from_sql(self, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError(f"Expected str from SQL, got {type(value).__name__}")
        return value


class FKColumn(TextColumn):
    """TEXT column storing a related model's primary key id string."""


class DateColumn(Column):
    sql_type = "TEXT"
    default_sql = '"0001-01-01"'
    _FORMAT = "%Y-%m-%d"

    def _to_sql(self, value: Any) -> str:
        if not isinstance(value, date) or isinstance(value, datetime):
            raise TypeError(f"Expected datetime.date, got {type(value).__name__}")
        return value.strftime(self._FORMAT)

    def _from_sql(self, value: Any) -> date:
        if not isinstance(value, str):
            raise TypeError(f"Expected str from SQL, got {type(value).__name__}")
        return datetime.strptime(value, self._FORMAT).date()


class TimeColumn(Column):
    sql_type = "TEXT"
    default_sql = '"00:00:00.000000"'
    _FORMAT = "%H:%M:%S.%f"

    def _to_sql(self, value: Any) -> str:
        if not isinstance(value, time):
            raise TypeError(f"Expected datetime.time, got {type(value).__name__}")
        if value.tzinfo is not None:
            raise TypeError("datetime.time values must be naive (no timezone)")
        return value.strftime(self._FORMAT)

    def _from_sql(self, value: Any) -> time:
        if not isinstance(value, str):
            raise TypeError(f"Expected str from SQL, got {type(value).__name__}")
        return datetime.strptime(value, self._FORMAT).time()


class DateTimeColumn(Column):
    sql_type = "TEXT"
    default_sql = '"0001-01-01T00:00:00.000000+00:00"'

    def _to_sql(self, value: Any) -> str:
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime.datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat(timespec="microseconds")

    def _from_sql(self, value: Any) -> datetime:
        if not isinstance(value, str):
            raise TypeError(f"Expected str from SQL, got {type(value).__name__}")
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result
