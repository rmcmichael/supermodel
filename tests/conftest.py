import pytest

from supermodel import Database


@pytest.fixture
def db():
    database = Database()
    database.reset()
    database.path = ":memory:"
    yield database
    database.reset()
