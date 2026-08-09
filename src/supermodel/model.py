from .database import Database


class Model:
    """Base class for persisted models.

    Subclasses register with the Database singleton on definition.
    Full persistence API is added in later design steps.
    """

    _is_schema_checked: bool = False
    _db: Database = Database()

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        # Each concrete subclass gets its own flag; do not share the base value.
        cls._is_schema_checked = False
        Database().register_model(cls)

    def __init__(self, **kwargs):
        self._id: str | None = None

    @classmethod
    def _check_schema(cls) -> None:
        """Ensure the backing table matches this model.

        Idempotent. Invoked by Database on first connection and on late
        registration while connected. Table create/alter logic is added
        in a later design step.
        """
        if cls._is_schema_checked:
            return
        cls._is_schema_checked = True
