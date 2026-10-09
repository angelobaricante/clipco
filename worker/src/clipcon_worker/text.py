"""Word matching shared by search and relationship suggestions."""

import re

# Words that carry no footage meaning in English or Tagalog/Taglish text.
STOPWORDS = frozenset("""
a an and are as at be but by do for from has have i in is it its me my of on or our so that the their them then
there these they this to was we were what when where which who will with you your
ang ng mga sa na at ay ito iyan yan yung iyong lang pa po ko mo niya nila namin natin si ni kay
""".split())


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def terms(text: str) -> list[str]:
    """Meaningful words; text made only of stopwords keeps them rather than matching nothing."""
    every = words(text)
    return [w for w in every if w not in STOPWORDS] or every


def matches(term: str, words: set[str]) -> bool:
    """Exact word, or one word extending the other for longer words ("filter" matches "filters")."""
    return term in words or (len(term) >= 4 and any(w.startswith(term) or (len(w) >= 4 and term.startswith(w))
                                                    for w in words))
