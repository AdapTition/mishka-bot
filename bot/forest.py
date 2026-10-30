"""Forest map: mittens, forest parts and who a piece of advice is written for."""

import json
import re
from dataclasses import dataclass, field

CONIFER, DECIDUOUS, RIVER = "conifer", "deciduous", "river"

PART_NAMES = {
    CONIFER: "хвойний ліс",
    DECIDUOUS: "листяний ліс",
    RIVER: "біля річки",
}


@dataclass(frozen=True)
class Mitten:
    name: str
    parts: tuple[str, ...]
    pattern: re.Pattern


def _p(regex: str) -> re.Pattern:
    return re.compile(regex)


# Order and membership come from the "Карта лісу" (Forest map) document.
MITTENS: tuple[Mitten, ...] = (
    Mitten("Під ялиною", (CONIFER,), _p(r"під\s+ялин(?:ою|ой)\b")),
    Mitten("У соснах", (CONIFER,), _p(r"\b[ув]\s+соснах\b")),
    Mitten("Біля мурашника", (CONIFER,), _p(r"біля\s+мурашника\b")),
    Mitten("Під дубом", (DECIDUOUS,), _p(r"під\s+дубом\b")),
    Mitten("У ліщині", (DECIDUOUS,), _p(r"\b[ув]\s+ліщині\b")),
    Mitten("Під вербою", (DECIDUOUS, RIVER), _p(r"під\s+вербою\b")),
    Mitten("Біля бобрової греблі", (RIVER,), _p(r"(?:біля\s+)?бобров\w*\s+греблі\b|біля\s+греблі\b")),
    Mitten("На узліссі", (), _p(r"на\s+узліссі\b")),
)
MITTEN_BY_NAME = {m.name: m for m in MITTENS}

PART_PATTERNS = {
    CONIFER: _p(r"хвойн\w*|під\s+ялинами\b|серед\s+(?:\w+\s+)?сосен\b"),
    DECIDUOUS: _p(r"листян\w*"),
    RIVER: _p(r"біля\s+річки\b|прибережж\w*|на\s+березі\s+річки\b"),
}

FOREST_WIDE = _p(r"[ув]сіх\s+мешканц\w*\s+лісу|для\s+всього\s+лісу|[ув]сім\s+мешканцям\s+лісу")


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("ʼ", "'").replace("`", "'")
    return re.sub(r"\s+", " ", text)


def find_mittens(text: str) -> list[str]:
    t = normalize(text)
    return [m.name for m in MITTENS if m.pattern.search(t)]


def find_parts(text: str) -> list[str]:
    t = normalize(text)
    return [part for part, rx in PART_PATTERNS.items() if rx.search(t)]


def strip_places(text: str) -> str:
    """Removes place names from the question: the filter already accounts for them and they only hurt search."""
    t = normalize(text)
    for rx in [m.pattern for m in MITTENS] + list(PART_PATTERNS.values()):
        t = rx.sub(" ", t)
    return t


def is_forest_wide(text: str) -> bool:
    return bool(FOREST_WIDE.search(normalize(text)))


@dataclass
class Audience:
    """Who the advice is for: the whole forest, forest parts or individual mittens."""

    forest: bool = False
    parts: list[str] = field(default_factory=list)
    mittens: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.forest or self.parts or self.mittens)

    def to_json(self) -> str:
        return json.dumps(
            {"forest": self.forest, "parts": self.parts, "mittens": self.mittens},
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str | None) -> "Audience":
        data = json.loads(raw) if raw else {}
        return cls(
            forest=bool(data.get("forest")),
            parts=[p for p in data.get("parts", []) if p in PART_NAMES],
            mittens=[m for m in data.get("mittens", []) if m in MITTEN_BY_NAME],
        )

    def key(self) -> tuple:
        return (self.forest, tuple(sorted(self.parts)), tuple(sorted(self.mittens)))

    def describe(self) -> str:
        if self.forest:
            return "увесь ліс"
        items = [PART_NAMES[p] for p in self.parts]
        items += [f"рукавичка «{m}»" for m in self.mittens]
        return ", ".join(items) if items else "не визначено"

    def level_for_mitten(self, mitten: str) -> int:
        """3: advice for this very mitten, 2: for its forest part, 1: for the whole forest, 0: not applicable."""
        if mitten in self.mittens:
            return 3
        if set(self.parts) & set(MITTEN_BY_NAME[mitten].parts):
            return 2
        return 1 if self.forest else 0

    def applies_to_part(self, part: str) -> bool:
        if self.forest or part in self.parts:
            return True
        return any(part in MITTEN_BY_NAME[m].parts for m in self.mittens)


@dataclass
class Target:
    """Which place the animal is asking about (from the question text)."""

    mittens: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.mittens or self.parts)

    def applies(self, audience: Audience) -> bool:
        if self.mittens:
            return any(audience.level_for_mitten(m) for m in self.mittens)
        if self.parts:
            return any(audience.applies_to_part(p) for p in self.parts)
        return True

    def describe(self) -> str:
        if self.mittens:
            items = []
            for m in self.mittens:
                parts = MITTEN_BY_NAME[m].parts
                where = ", ".join(PART_NAMES[p] for p in parts) if parts else "не належить до жодної частини лісу"
                items.append(f"рукавичка «{m}» ({where})")
            return "; ".join(items)
        if self.parts:
            return ", ".join(PART_NAMES[p] for p in self.parts)
        return "не назване"


MAP_TEXT = "\n".join(
    f"- «{m.name}»: " + (", ".join(PART_NAMES[p] for p in m.parts) if m.parts else "не належить до жодної частини лісу")
    for m in MITTENS
)
