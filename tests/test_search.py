from bot.forest import Audience
from bot.search import rank
from bot.storage import Document


def doc(doc_id: int, title: str, text: str) -> Document:
    return Document(doc_id, title, title, text, Audience(forest=True), "archive", None, None, "", "active", None, "")


DOCS = [
    doc(1, "Членські внески рукавички Під дубом", "Внесок — 4 жолуді з дорослого звіра на місяць."),
    doc(2, "Як утеплити рукавичку в хвойному лісі", "Утеплюйте рукавичку в жовтні мохом і хвоєю."),
    doc(3, "Що робити при пожежі", "Довгий безперервний крик означає пожежу. Біжіть до річки."),
    doc(4, "Правила співжиття в рукавичці Під ялиною", "Тиша настає після заходу сонця."),
]


def top(query: str) -> int:
    return rank(query, DOCS)[0][0].id


def test_inflected_forms_match():
    assert top("Скільки внесків треба здавати?") == 1
    assert top("коли утеплювати рукавички") == 2
    assert top("що робити, якщо пожежа") == 3
    assert top("коли в нас тиші?") == 4


def test_unrelated_query_scores_zero():
    assert all(score == 0 for _, score in rank("квантова фізика", DOCS))
