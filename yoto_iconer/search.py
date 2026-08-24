"""Turn track titles into queries, and queries into ranked icon candidates."""

from __future__ import annotations

import math
import re
import sqlite3

# Words that never help identify a picture.
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "in", "on", "at", "to", "for",
    "with", "from", "by", "is", "are", "was", "be", "it", "its", "this", "that",
    "we", "you", "your", "my", "me", "i", "im", "id", "ill", "ive", "our", "us",
    "he", "she", "they", "them", "his", "her", "their", "do", "dont", "did",
    "so", "as", "if", "no", "not", "all", "up", "down", "out", "off", "then",
    "feat", "featuring", "ft", "version", "remix", "remastered", "live",
    "official", "audio", "video", "instrumental", "karaoke", "track", "song",
    "part", "pt", "vol", "edit", "mix", "extended", "radio", "single",
}

# Bracketed junk that is never about the subject of the song.
_NOISE_PARENS = re.compile(
    r"[\(\[]\s*(?:feat\.?|ft\.?|featuring|official[^)\]]*|live[^)\]]*|remaster[^)\]]*|"
    r"remix|radio edit|explicit|clean|bonus[^)\]]*|from [^)\]]*|hd|hq|lyrics?[^)\]]*)"
    r"[^)\]]*[\)\]]",
    re.I,
)
_LEADING_INDEX = re.compile(r"^\s*\d{1,3}\s*[-._)]\s+")
_EXTENSION = re.compile(r"\.(mp3|m4a|m4b|wav|flac|ogg|opus|aac|wma)\b", re.I)
_NONWORD = re.compile(r"[^a-z0-9' ]+")


def normalize_title(title: str) -> str:
    text = _EXTENSION.sub(" ", title or "")
    text = _NOISE_PARENS.sub(" ", text)
    text = _LEADING_INDEX.sub("", text)
    text = text.replace("&", " and ")
    return text.strip()


def tokenize(title: str) -> list[str]:
    """Content words from a track title, order preserved, duplicates dropped."""
    text = _NONWORD.sub(" ", normalize_title(title).lower()).replace("'", "")
    seen, out = set(), []
    for tok in text.split():
        if len(tok) < 2 or tok in STOPWORDS or tok.isdigit():
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


# Common in track titles, useless as a search term on their own.
WEAK_TOKENS = {
    "little", "big", "old", "new", "good", "best", "first", "last", "every",
    "always", "never", "one", "two", "three", "four", "five", "day", "night",
    "time", "away", "here", "there", "again", "goes", "went", "make", "made",
}


def live_terms(title: str, count: int = 2) -> list[str]:
    """The most distinctive tokens in a title, for a live yotoicons lookup.

    Length is a decent proxy for specificity, and demoting filler words keeps
    "Dinosaur Stomp" from being looked up as "little".
    """
    tokens = tokenize(title)
    ranked = sorted(tokens, key=lambda t: (t in WEAK_TOKENS, -len(t)))
    return ranked[:count]


def stem(token: str) -> str:
    """Crude singularizer, so `star` and `stars` count as the same word.

    FTS5 already stems with porter; this exists so the scoring boosts and the
    lexical-hit check agree with it.
    """
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es") and token[-3] in "sxzho":
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def stems(tokens) -> set[str]:
    return {stem(t) for t in tokens}


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()


def title_hit(candidate: dict, tokens: list[str]) -> bool:
    """True when the candidate's own name shares a content word with the query.

    A tag match is weaker evidence - a *Magic School Bus* icon tagged
    "dinosaurs" is not a dinosaur icon - so the name is what counts here.
    """
    return bool(stems(tokens) & stems(_words(candidate.get("title"))))


def has_lexical_hit(candidates: list[dict], tokens: list[str]) -> bool:
    """True when some candidate shares a content word with the query."""
    want = stems(tokens)
    for cand in candidates:
        if want & (stems(_words(cand.get("title"))) | stems((cand.get("tags") or "").split())):
            return True
    return False


def is_latin(title: str, threshold: float = 0.8) -> bool:
    """Whether a title is written mostly in the Latin alphabet.

    Both icon catalogs are tagged in English, so a Hebrew, Cyrillic or CJK
    title cannot be searched directly - it needs a translated query.
    """
    letters = [c for c in (title or "") if c.isalpha()]
    if not letters:
        return False
    ascii_letters = sum(1 for c in letters if c.isascii())
    return ascii_letters / len(letters) >= threshold


def query_for(title: str) -> str:
    toks = tokenize(title)
    if not toks:
        # Everything was noise; fall back to whatever letters exist.
        toks = [t for t in _NONWORD.sub(" ", (title or "").lower()).split() if t]
    return " ".join(toks)


def _fts_expr(tokens: list[str]) -> str:
    safe = [re.sub(r"[^a-z0-9]", "", t) for t in tokens]
    parts = [f'"{t}" OR {t}*' for t in safe if len(t) >= 2]
    return " OR ".join(parts)


def _score(row: sqlite3.Row, tokens: set[str], bm25: float) -> float:
    """Combine FTS relevance with cheap, explainable boosts."""
    score = -bm25  # bm25() is lower-is-better
    title_toks = stems(_words(row["title"]))
    tag_toks = stems((row["tags"] or "").split())

    overlap = len(tokens & title_toks)
    score += 3.0 * overlap
    if title_toks and title_toks <= tokens:
        score += 2.0  # the whole icon name appears in the track title
    score += 1.5 * len(tokens & tag_toks)

    if row["source"] == "official":
        score += 1.0  # already a mediaId: no upload needed
    elif row["source"] == "user":
        score += 1.5  # already in the user's own library
    score += 0.4 * math.log1p(row["downloads"] or 0)
    return score


def search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
    sources: tuple[str, ...] | None = None,
) -> list[dict]:
    tokens = [t for t in tokenize(query) or query.lower().split() if t]
    if not tokens:
        return []
    expr = _fts_expr(tokens)
    rows = []
    if expr:
        sql = """
            SELECT i.*, bm25(icons_fts) AS bm
            FROM icons_fts JOIN icons i ON i.key = icons_fts.key
            WHERE icons_fts MATCH ?
        """
        params: list = [expr]
        if sources:
            sql += " AND i.source IN (%s)" % ",".join("?" * len(sources))
            params += list(sources)
        sql += " ORDER BY bm LIMIT 400"
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            rows = []

    if not rows:  # FTS came up empty - fall back to substring matching
        like_sql = "SELECT *, 0.0 AS bm FROM icons WHERE (" + " OR ".join(
            ["title LIKE ? OR tags LIKE ?"] * len(tokens)
        ) + ")"
        params = []
        for t in tokens:
            params += [f"%{t}%", f"%{t}%"]
        if sources:
            like_sql += " AND source IN (%s)" % ",".join("?" * len(sources))
            params += list(sources)
        rows = conn.execute(like_sql + " LIMIT 400", params).fetchall()

    tokset = stems(tokens)
    scored = [(dict(r), _score(r, tokset, r["bm"])) for r in rows]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    out = []
    for row, score in scored[:limit]:
        row.pop("bm", None)
        row["score"] = round(score, 2)
        out.append(row)
    return out
