from __future__ import annotations

from supermodel import Model, Database

db = Database()
db.path = ":memory:"


class Log(Model):
    title: str = ""

    """ Establish a one-to-many relationship to the QSO model.

    - This is a one-to-many relationship.
    - The qsos attribute is virtual - there is not a column in the database for it.
    - This is recorded by the Database when the model is registered.
    - The fetching of the list is lazy.
    - When the Log is subsequently hydrated, the list is loaded on first access.
    - The list of QSO objects will be those whose log FK points at this Log.
    """
    qsos: list[QSO]


class QSO(Model):
    comment: str = ""

    """ Establish a foreign key to the Log model.

    - This is a one-to-many relationship.
    - The log attribute gets mapped to a column storing the Log ID.
    - This is recorded by the Database when the model is registered.
    - When the QSO is subsequently hydrated, log is resolved lazily
      to the Log instance for that ID (via the identity cache).
    - save() requires log to be set to a Log that already has an id.
    - save() does not cascade; only this QSO row is written.
    - Removing a Log cascades to its QSOs.
    """
    log: Log


if __name__ == "__main__":
    log = Log()
    log.title = "Test Log"
    log.save()
    log_id = log.id
    print(f"Log ID: {log_id}, Title: {log.title}")

    qso1 = QSO()
    qso1.comment = "Test QSO 1"
    qso1.log = log
    qso1.save()

    qso2 = QSO()
    qso2.comment = "Test QSO 2"
    qso2.log = log
    qso2.save()

    print(f"QSOs on log: {[q.comment for q in log.qsos]}")
    print(f"Parent of qso1 is log: {qso1.log is log}")

    del log
    del qso1
    del qso2

    log = Log().get(log_id)
    print(f"Log ID: {log.id}, Title: {log.title}")
    print(f"QSOs on log: {[q.comment for q in log.qsos]}")
