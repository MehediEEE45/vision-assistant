"""The app's safety-language rule, applied to text a model generates.

Recorded prompts are checked at build time. A caption or a translation is
written at run time, so each sentence is checked before it is spoken and
dropped if it promises safety ("the path is clear", "নিরাপদ").
"""

import re

from . import config

# The app's list, plus phrasings a caption model tends to produce that amount
# to the same promise.
EXTRA = ["path is clear", "way is clear", "clear path", "no obstacles", "nothing in the way",
         "safe to walk", "পথ পরিষ্কার", "কোনো বাধা নেই"]


def banned():
    words = list(EXTRA)
    if config.BANNED_PHRASES.exists():
        for line in config.BANNED_PHRASES.read_text(encoding="utf-8").splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                words.append(line)
    return words


_BANNED = banned()
_SPLIT = re.compile(r"(?<=[.!?।])\s+")


def sentences(text):
    return [s.strip() for s in _SPLIT.split(text or "") if s.strip()]


def violations(text):
    t = (text or "").lower()
    return [b for b in _BANNED if b in t]


def clean(text):
    """The text minus any sentence that promises safety."""
    return " ".join(s for s in sentences(text) if not violations(s))


def check_fixed(texts):
    bad = [(t, violations(t)) for t in texts if violations(t)]
    if bad:
        raise ValueError(f"fixed phrases promise safety: {bad}")
