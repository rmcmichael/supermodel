import pytest

from supermodel import Database


@pytest.fixture
def db():
    database = Database()
    database.reset()
    yield database
    database.reset()
