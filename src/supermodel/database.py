class Database:
    _instance = None

    def __new__(cls, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, **kwargs):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
