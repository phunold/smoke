"""Detector checks. No network, no keys: uv run python test_detect.py"""
import unicodedata

from smoke import canary, detect

c = canary(7)
zw = "\u200b".join(c)
tag = "".join(chr(0xE0000 + ord(ch)) for ch in c)
wrap = lambda s: f"# Title\n\nSome visible text. {s} More text.\n"

assert c.isascii() and c.islower() and "--" not in c and len(c) == 5 + 12 + 2

assert detect(c, wrap(c)) == ("reached", "exact")
assert detect(c, wrap(c[:9] + "\n" + c[9:])) == ("altered", "nowrap")
assert detect(c, wrap(zw)) == ("altered", "nocf")
# Asserts the pass NAME: stripping Cf before decoding tags would report "stripped" here.
assert detect(c, wrap(tag)) == ("altered", "untag")

# NFKC is a no-op on Cf payloads; a "just normalise" detector would miss these.
for form in ("NFKC", "NFKD"):
    assert unicodedata.normalize(form, zw) == zw
    assert unicodedata.normalize(form, tag) == tag
    assert detect(c, unicodedata.normalize(form, zw)) == ("altered", "nocf")

assert detect(c, wrap("nothing here")) == ("stripped", None)
assert detect(c, wrap(c[:-1])) == ("stripped", None)
assert detect(c, wrap(zw[:-1])) == ("stripped", None)

for empty in (None, "", "  \n"):
    assert detect(c, empty) == ("empty", None)

if __name__ == "__main__":
    print("ok")
