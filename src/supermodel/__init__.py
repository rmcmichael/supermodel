"""SuperModel: persist plain Python classes in SQLite."""

from supermodel.database import Database
from supermodel.model import Model
from supermodel.model import ModelError

__version__ = "0.1.0"

__all__ = [
    "Database",
    "Model",
    "ModelError",
    "__version__",
]
