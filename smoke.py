"""Smoke: does hidden text reach the model through LLM-ready extraction tools?"""
import secrets
import unicodedata

# --- detector ----------------------------------------------------------------


def canary(i):
    return "sm0ke" + secrets.token_hex(6) + f"{i:02d}"


def _nows(s):
    return "".join(s.split())


def _nocf(s):
    return "".join(c for c in s if unicodedata.category(c) != "Cf")


def _untag(s):
    return "".join(chr(ord(c) - 0xE0000) if 0xE0000 <= ord(c) <= 0xE007F else c for c in s)


# Ordered, first hit wins. nocf before untag: untag also drops Cf, so it would shadow nocf.
# Inside untag, tag chars are themselves Cf: decode them BEFORE dropping Cf.
PASSES = [
    ("exact", lambda s: s),
    ("nowrap", _nows),
    ("nocf", lambda s: _nows(_nocf(s))),
    ("untag", lambda s: _nows(_nocf(_untag(s)))),
]


def detect(needle, text):
    """-> (state, pass). Only the haystack is transformed; the canary is invariant."""
    if not text or not text.strip():
        return "empty", None
    for name, transform in PASSES:
        if needle in transform(text):
            return ("reached" if name == "exact" else "altered"), name
    return "stripped", None
