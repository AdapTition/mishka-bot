from bot.forest import Audience, Target
from bot.qa import Understanding, doc_kind, select_docs, strip_doc_refs
from bot.storage import Document


def doc(doc_id: int, title: str, text: str, audience: Audience) -> Document:
    return Document(doc_id, title, title, text, audience, "archive", None, None, "", "active", None, "")


def test_doc_references_are_removed_from_answer():
    for text in ("Гриби після дощу (Док.1, Док.20).", "Гриби після дощу (док. 77).", "Гриби після дощу (Документ 4)."):
        assert strip_doc_refs(text) == "Гриби після дощу."


def test_doc_references_without_brackets_are_removed():
    cases = {
        "За документом 15, внески здають у жовтні.": "Внески здають у жовтні.",
        "Внески здають у жовтні (див. документ №15).": "Внески здають у жовтні.",
        "Внески здають у жовтні, згідно з документом 15 і 16.": "Внески здають у жовтні.",
        "У документі 3 сказано, що тиша з полудня.": "Сказано, що тиша з полудня.",
        "Гриби після дощу. За док. 4, 7 та 9 ягоди теж.": "Гриби після дощу. Ягоди теж.",
    }
    for text, expected in cases.items():
        assert strip_doc_refs(text) == expected


def test_text_without_doc_references_is_unchanged():
    text = "Внески — 5 жолудів, здають до 15 жовтня. Документи приносьте Сові."
    assert strip_doc_refs(text) == text


DOCS = [
    doc(1, "Чергування в рукавичці Біля бобрової греблі", "Бобер лагодить греблю щоранку.",
        Audience(mittens=["Біля бобрової греблі"])),
    doc(2, "Як утеплити рукавичку біля річки", "Утеплюйте очеретом.", Audience(parts=["river"])),
    doc(3, "Календар сезонів", "Рукавички утеплюють у листопаді.", Audience(forest=True)),
    doc(4, "Правила співжиття в рукавичці Під дубом", "Тиша з полудня.", Audience(mittens=["Під дубом"])),
]


def understanding(question: str, target: Target, doc_ids=(), keywords=()) -> Understanding:
    return Understanding("question", "", question, target, list(keywords), list(doc_ids))


def test_other_place_document_is_not_filtered_out():
    # An animal from "Під вербою" asks about the dam: a document of another mitten must still reach the model.
    u = understanding("Хто ремонтує греблю?", Target(mittens=["Під вербою"]), keywords=["лагодить", "гребля"])
    assert 1 in [d.id for d in select_docs(u, DOCS)]


def test_documents_for_asker_place_come_first():
    u = understanding("Коли утеплювати рукавичку?", Target(mittens=["Під вербою"]), doc_ids=[3, 2, 4])
    ids = [d.id for d in select_docs(u, DOCS)]
    assert ids.index(2) < ids.index(3) < ids.index(4)


def test_archive_documents_group_into_kinds_of_eight():
    from pathlib import Path
    from collections import Counter
    from bot.forest import find_mittens

    titles = [p.stem for p in (Path(__file__).parent.parent / "data" / "archive").iterdir()]
    docs = [doc(i, t, "", Audience(mittens=find_mittens(t))) for i, t in enumerate(titles)]
    kinds = Counter(doc_kind(d) for d in docs if d.audience.mittens)
    assert len(kinds) == 7 and set(kinds.values()) == {8}


def test_comparison_brings_all_mittens_of_same_kind():
    mittens = ["Під ялиною", "У соснах", "Під дубом"]
    fees = [doc(10 + i, f"Членські внески рукавички {m}", "Внесок.", Audience(mittens=[m])) for i, m in enumerate(mittens)]
    u = Understanding("question", "", "У якій рукавичці найменші внески?", Target(), [], [10], compare=True)
    assert {d.id for d in select_docs(u, DOCS + fees)} >= {10, 11, 12}


def test_comparison_picks_kind_by_total_relevance_not_first_pick():
    mittens = ["Під ялиною", "У соснах", "Під дубом"]
    statutes = [doc(20 + i, f"Статут ОСМД {m}", "Збори мешканців щомісяця.", Audience(mittens=[m]))
                for i, m in enumerate(mittens)]
    rules = [doc(30 + i, f"Правила співжиття в рукавичці {m}", "Тиша вночі.", Audience(mittens=[m]))
             for i, m in enumerate(mittens)]
    # The model picked "Правила" first, but residents' meetings are covered by the statutes.
    u = Understanding("question", "", "Де збори мешканців найчастіше?", Target(), ["збори"], [30], compare=True)
    assert {20, 21, 22} <= {d.id for d in select_docs(u, statutes + rules)}


def test_forest_wide_question_is_not_flooded_with_mitten_documents():
    u = understanding("Коли утеплюють рукавички?", Target(), doc_ids=[3])
    assert select_docs(u, DOCS)[0].id == 3 and len(select_docs(u, DOCS)) <= 8


def test_catalog_choice_used_when_words_do_not_match():
    u = understanding("Хто чинить загату?", Target(), doc_ids=[1])
    assert [d.id for d in select_docs(u, DOCS)][0] == 1
