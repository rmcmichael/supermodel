"""Tests for one-to-many relations and the identity cache."""

from __future__ import annotations

import pytest

from supermodel import Model
from supermodel import ModelError
from supermodel.column import FKColumn


def test_fk_save_and_lazy_parent(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log

    log = Log().set({"title": "Test"}).save()
    qso = QSO()
    qso.comment = "cq"
    qso.log = log
    qso.save()

    loaded = QSO.get(qso.id)
    assert loaded.log is log
    assert loaded.log.title == "Test"
    assert loaded.to_dict() == {"comment": "cq", "log": log.id}


def test_virtual_collection_lazy_list(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log

    log = Log().set({"title": "Test"}).save()
    QSO().set({"comment": "one", "log": log}).save()
    QSO().set({"comment": "two", "log": log}).save()

    loaded = Log.get(log.id)
    assert {q.comment for q in loaded.qsos} == {"one", "two"}


def test_save_requires_fk_parent(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log

    qso = QSO()
    qso.comment = "orphan"
    with pytest.raises(ModelError, match="must be set before save"):
        qso.save()


def test_save_requires_parent_id(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log

    log = Log()
    log.title = "unsaved"
    qso = QSO()
    qso.comment = "cq"
    qso.log = log
    with pytest.raises(ModelError, match="parent must be saved"):
        qso.save()


def test_identity_cache_same_instance(db):
    class Thing(Model):
        label: str = ""

    thing = Thing().set({"label": "a"}).save()
    assert Thing.get(thing.id) is thing
    assert Thing.select()[0] is thing


def test_cascade_remove_children(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log

    log = Log().set({"title": "Test"}).save()
    q1 = QSO().set({"comment": "one", "log": log}).save()
    q2 = QSO().set({"comment": "two", "log": log}).save()

    log.remove()
    assert Log.count == 0
    assert QSO.count == 0
    with pytest.raises(ModelError, match="does not exist"):
        QSO.get(q1.id)
    with pytest.raises(ModelError, match="does not exist"):
        QSO.get(q2.id)


def test_cascade_remove_multi_level(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log
        notes: list[Note]

    class Note(Model):
        body: str = ""
        qso: QSO

    log = Log().set({"title": "Test"}).save()
    qso = QSO().set({"comment": "cq", "log": log}).save()
    Note().set({"body": "n1", "qso": qso}).save()
    Note().set({"body": "n2", "qso": qso}).save()

    log.remove()
    assert Log.count == 0
    assert QSO.count == 0
    assert Note.count == 0


def test_collection_assignment_raises(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log

    log = Log().set({"title": "Test"}).save()
    with pytest.raises(ModelError, match="virtual collection"):
        log.qsos = []


def test_from_dict_fk_as_id(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log

    log = Log().set({"title": "Test"}).save()
    qso = QSO.from_dict({"comment": "cq", "log": log.id})
    assert isinstance(qso, QSO)
    assert qso.log is log


def test_optional_fk_annotation_is_nullable(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log | None

    assert isinstance(QSO._columns["log"], FKColumn)
    assert QSO._columns["log"].nullable is True
    assert "DEFAULT NULL" in QSO._columns["log"].ddl


def test_optional_fk_unset_saves_null(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log | None

    qso = QSO()
    qso.comment = "orphan"
    qso.save()

    assert qso.log is None
    assert qso.to_dict() == {"comment": "orphan", "log": None}

    loaded = QSO.get(qso.id)
    assert loaded.log is None
    row = db.execute("SELECT LOG FROM QSO WHERE ID = ?", (qso.id,)).fetchone()
    assert row["LOG"] is None


def test_optional_fk_explicit_none_round_trip(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log | None

    log = Log().set({"title": "Test"}).save()
    qso = QSO().set({"comment": "cq", "log": None}).save()
    assert qso.log is None

    qso.log = log
    qso.save()
    assert QSO.get(qso.id).log is log

    qso.log = None
    qso.save()
    loaded = QSO.get(qso.id)
    assert loaded.log is None
    assert loaded.to_dict()["log"] is None


def test_optional_fk_from_dict_none(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log | None

    qso = QSO.from_dict({"comment": "cq", "log": None})
    assert isinstance(qso, QSO)
    assert qso.log is None


def test_required_fk_rejects_none_on_assign_and_set(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log

    qso = QSO()
    with pytest.raises(ModelError, match="got None"):
        qso.log = None
    with pytest.raises(ModelError, match="got None"):
        qso.set({"log": None})


def test_optional_fk_null_excluded_from_collection_and_cascade(db):
    class Log(Model):
        title: str = ""
        qsos: list[QSO]

    class QSO(Model):
        comment: str = ""
        log: Log | None

    log = Log().set({"title": "Test"}).save()
    attached = QSO().set({"comment": "linked", "log": log}).save()
    orphan = QSO().set({"comment": "orphan", "log": None}).save()

    loaded = Log.get(log.id)
    assert {q.comment for q in loaded.qsos} == {"linked"}

    log.remove()
    assert Log.count == 0
    with pytest.raises(ModelError, match="does not exist"):
        QSO.get(attached.id)
    surviving = QSO.get(orphan.id)
    assert surviving.comment == "orphan"
    assert surviving.log is None
