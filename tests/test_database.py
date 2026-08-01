from supermodel.database import Database


def test_database_is_singleton():
    first = Database()
    second = Database()
    assert first is second
