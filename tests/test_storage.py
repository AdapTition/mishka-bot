from bot.forest import Audience
from bot.storage import Store


def add(store: Store, title: str, source: str = "archive") -> int:
    return store.add(title=title, filename=title, text="Текст.", audience=Audience(mittens=["Під дубом"]),
                     source=source, sha256=title, status="active", uploader_id=1 if source == "user" else None)


def test_deleting_new_version_brings_back_the_old_one(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    old = add(store, "Членські внески рукавички Під дубом")
    new = add(store, "Членські внески рукавички Під дубом 2027", source="user")
    store.set_status(old, "replaced", replaced_by=new)

    restored = store.delete(new)

    # An archive document cannot be deleted, not even by replacing it and deleting the replacement.
    assert restored is not None and restored.id == old
    assert [d.id for d in store.active()] == [old]


def test_deleting_document_without_previous_version(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    doc = add(store, "Малина", source="user")
    assert store.delete(doc) is None
    assert store.active() == []
