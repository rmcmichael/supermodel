from .database import Database


class Model:
    _is_schema_checked: bool = False
    _db: Database = Database()

    def __init__(self, **kwargs):
        self._id: str | None = None
