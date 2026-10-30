from pathlib import Path

import docx
import fitz
import pytest

from bot.forest import CONIFER, DECIDUOUS, RIVER, Audience, Target, find_mittens, find_parts, strip_places
from bot.scope import classify_rules, normalize_title

ARCHIVE = Path(__file__).parent.parent / "data" / "archive"

FOREST_WIDE = {
    "Календар сезонів", "Карта лісу", "Правила толоки", "Що робити при пожежі", "Як кричати, коли бачиш мисливців",
    "Осінній путівник лісу", "Їстівне й отруйне",
}
PARTS = {
    "Броди і коли бобри відкривають греблю": [RIVER],
    "Грибний путівник біля річки": [RIVER],
    "Грибний путівник листяного лісу": [DECIDUOUS],
    "Грибний путівник хвойного лісу": [CONIFER],
    "Коли падають жолуді й горіхи": [DECIDUOUS],
    "Небезпеки біля річки": [RIVER],
    "Небезпеки листяного лісу": [DECIDUOUS],
    "Небезпеки хвойного лісу": [CONIFER],
    "Що їсти біля річки": [RIVER],
    "Що їсти в листяному лісі": [DECIDUOUS],
    "Що їсти в хвойному лісі": [CONIFER],
    "Як не заблукати серед однакових сосен": [CONIFER],
    "Як утеплити рукавичку біля річки": [RIVER],
    "Як утеплити рукавичку в листяному лісі": [DECIDUOUS],
    "Як утеплити рукавичку в хвойному лісі": [CONIFER],
}
MITTEN_NAMES = ["Під ялиною", "У соснах", "Біля мурашника", "Під дубом", "У ліщині", "Під вербою",
                "Біля бобрової греблі", "На узліссі"]


def quick_text(path: Path) -> str:
    """Text layer without OCR: for scans the title alone is enough."""
    if path.suffix == ".pdf":
        with fitz.open(path) as pdf:
            return "\n".join(page.get_text() for page in pdf)
    if path.suffix == ".docx":
        return "\n".join(p.text for p in docx.Document(path).paragraphs)
    return path.read_text(encoding="utf-8")


def expected(title: str) -> Audience:
    if title in FOREST_WIDE:
        return Audience(forest=True)
    if title in PARTS:
        return Audience(parts=PARTS[title])
    mittens = [m for m in MITTEN_NAMES if title.endswith(m)]
    assert len(mittens) == 1, title
    return Audience(mittens=mittens)


@pytest.mark.parametrize("path", sorted(ARCHIVE.iterdir()), ids=lambda p: p.stem)
def test_archive_document_audience(path: Path):
    audience = classify_rules(path.stem, quick_text(path))
    assert audience is not None
    assert audience.key() == expected(path.stem).key()


def test_ambiguous_document_is_not_guessed():
    text = "Малина\nМалина достигає в липні. Збирайте тільки стиглі ягоди, зелені лишайте."
    assert classify_rules("Малина", text) is None


def test_under_fir_trees_means_conifer_not_mitten():
    audience = classify_rules("Шишки", "Порада для тих, хто живе під ялинами: шишки збирайте після вітру.")
    assert audience.key() == Audience(parts=[CONIFER]).key()


def test_question_place_detection():
    assert find_mittens("Коли здавати внески під дубом?") == ["Під дубом"]
    assert find_mittens("а в соснах хто голова?") == ["У соснах"]
    assert find_parts("що їсти в хвойному лісі") == [CONIFER]
    assert find_mittens("коли утеплювати рукавичку?") == []


def test_strip_places_keeps_topic_words():
    assert strip_places("Коли утеплювати рукавичку під вербою?").split() == ["коли", "утеплювати", "рукавичку", "?"]
    assert "хвойн" not in strip_places("що їсти в хвойному лісі")


def test_audience_levels():
    willow = "Під вербою"
    assert Audience(mittens=[willow]).level_for_mitten(willow) == 3
    assert Audience(parts=[RIVER]).level_for_mitten(willow) == 2
    assert Audience(parts=[DECIDUOUS]).level_for_mitten(willow) == 2
    assert Audience(forest=True).level_for_mitten(willow) == 1
    assert Audience(parts=[CONIFER]).level_for_mitten(willow) == 0
    # "На узліссі" (At the Forest Edge) belongs to no part of the forest
    assert Audience(parts=[CONIFER, DECIDUOUS, RIVER]).level_for_mitten("На узліссі") == 0
    assert Audience(mittens=["Під дубом"]).level_for_mitten("На узліссі") == 0


def test_target_filters_foreign_advice():
    target = Target(mittens=["Під ялиною"])
    assert target.applies(Audience(forest=True))
    assert target.applies(Audience(parts=[CONIFER]))
    assert not target.applies(Audience(mittens=["Під дубом"]))
    assert not target.applies(Audience(parts=[DECIDUOUS]))


def test_normalize_title_ignores_version_marks():
    assert normalize_title("Членські внески рукавички «Під дубом» (оновлено 2026)") == \
        normalize_title("Членські внески рукавички Під дубом")
