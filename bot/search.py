"""BM25 search over documents with light Ukrainian stemming."""

import math
import re
from collections import Counter

from .forest import normalize
from .storage import Document

STOPWORDS = set(
    "і й та а але в у на з із зі до для що як коли де чи не ні це ти я ми ви він вона воно вони же би б по за від "
    "під біля мені нам вам їм його її їх можна треба є був була було буде хто який яка яке які чому скільки так".split()
)
ENDINGS = sorted(
    "ювати увати ювали ення ання юйте уйте юють ують ити ати яти іть йте ами ями ові еві ого ому ими іми ою ею ів "
    "їв ам ям ах ях ий ій ої ти ть ла ло ли ся а я о е і ї и у ю ь".split(),
    key=len,
    reverse=True,
)


def _stem(word: str) -> str:
    for ending in ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def features(text: str) -> list[str]:
    result = []
    for word in re.findall(r"[a-zа-щьюяґєії']+", normalize(text)):
        if word in STOPWORDS or len(word) < 3:
            continue
        result.append(_stem(word))
        if len(word) > 4:
            result.append("#" + word[:4])
    return result


def rank(query: str, docs: list[Document], k1: float = 1.5, b: float = 0.75) -> list[tuple[Document, float]]:
    if not docs:
        return []
    bags = [Counter(features(d.title) * 2 + features(d.text)) for d in docs]
    avg_len = sum(sum(bag.values()) for bag in bags) / len(bags)
    df = Counter(term for bag in bags for term in bag)
    terms = set(features(query))

    scored = []
    for doc, bag in zip(docs, bags):
        length = sum(bag.values())
        score = 0.0
        for term in terms:
            tf = bag.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg_len))
        scored.append((doc, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored
