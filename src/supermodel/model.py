import datetime
from uuid import uuid7
from .database import Database


class Model:
    _is_schema_checked: bool = False
    _db: Database = Database()

    def _init_(self, **kwargs):
        self._id: str = str(uuid7())
        self._created_at: datetime = datetime.now()
        self._updated_at: datetime = datetime.now()
