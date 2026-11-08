"""Free speech -> one action. A Python port of the app's IntentRouter
(spine/intent-router/.../IntentRouter.kt): one bilingual synonym table, never
two command sets, because people mix languages inside one sentence
("chair টা কোথায়").

Order matters and follows the Kotlin router: emergency first, then stop and
repeat, then everything else. Objects are matched last, so "find" plus an
object name, or an object name alone, starts a search.
"""

import difflib
import re

PUNCTUATION = re.compile(r"[.,!?;:।\"'()\[\]]")
WHITESPACE = re.compile(r"\s+")

# Copied from IntentRouter.kt; keep in step.
SOS_WORDS = ["sos", "emergency", "save me", "জরুরি", "বাঁচাও", "বিপদ"]
STOP_WORDS = ["stop", "quiet", "be quiet", "থামো", "চুপ", "বন্ধ করো"]
REPEAT_WORDS = ["repeat", "say that again", "আবার বলো", "পুনরায় বলো"]
WHAT_IS_AHEAD_WORDS = ["what is in front", "what is ahead", "describe", "সামনে কি", "সামনে কী", "বর্ণনা"]
BATTERY_WORDS = ["battery", "charge", "ব্যাটারি", "চার্জ"]
FASTER_WORDS = ["faster", "speed up", "দ্রুত", "তাড়াতাড়ি"]
SLOWER_WORDS = ["slower", "slow down", "ধীরে", "আস্তে"]
SWITCH_TO_BANGLA_WORDS = ["speak bangla", "bangla", "বাংলায় বলো", "বাংলা"]
SWITCH_TO_ENGLISH_WORDS = ["speak english", "english", "ইংরেজিতে বলো", "ইংরেজি"]
HELP_WORDS = ["help", "what can you do", "সাহায্য", "কি করতে পারো"]
READ_WORDS = ["read this", "read it", "read", "পড়ো", "পড়ে শোনাও", "পড়ে দাও"]
PAUSE_READING_WORDS = ["pause", "hold on", "বিরতি", "একটু থামাও"]
RESUME_READING_WORDS = ["continue", "resume", "চালিয়ে যাও", "আবার শুরু"]
NEXT_PARAGRAPH_WORDS = ["next paragraph", "next page", "next", "পরের অনুচ্ছেদ", "পরের পাতা", "পরের"]
PREVIOUS_PARAGRAPH_WORDS = ["previous paragraph", "previous page", "previous", "আগের অনুচ্ছেদ", "আগের পাতা", "আগের"]

# Lab additions for the camera modes.
IDENTIFY_WORDS = ["what is this", "what's this", "identify", "এটা কী", "এটা কি", "কী এটা", "কি এটা", "এইটা কী", "চেনো"]
COLOUR_WORDS = ["colour", "color", "রং", "রঙ"]
WARNINGS_OFF_WORDS = ["warnings off", "turn off warnings", "সতর্কতা বন্ধ"]
WARNINGS_ON_WORDS = ["warnings on", "turn on warnings", "সতর্কতা চালু"]
OBJECT_WORDS = {
    "person": ["person", "people", "man", "woman", "মানুষ", "লোক"],
    "chair": ["chair", "চেয়ার", "চেয়ার"],
    "door": ["door", "দরজা"],
    "table": ["table", "desk", "টেবিল"],
    "bottle": ["bottle", "বোতল"],
    "toilet": ["toilet", "bathroom", "টয়লেট", "টয়লেট", "বাথরুম"],
    "rickshaw": ["rickshaw", "রিকশা", "রিক্সা"],
    "cng": ["cng", "auto rickshaw", "সিএনজি", "অটো"],
}

# Common things people ask to find, Bangla -> English for YOLO-World. Anything
# else goes through NLLB.
OBJECTS_BN_EN = {
    "চাবি": "key", "মোবাইল": "mobile phone", "ফোন": "phone", "ব্যাগ": "bag", "চশমা": "glasses",
    "কাপ": "cup", "গ্লাস": "glass", "বোতল": "bottle", "প্লেট": "plate", "জানালা": "window",
    "দরজা": "door", "চেয়ার": "chair", "টেবিল": "table", "বিছানা": "bed", "খাট": "bed",
    "সিঁড়ি": "stairs", "লিফট": "elevator", "টয়লেট": "toilet", "বাথরুম": "toilet", "বেসিন": "sink",
    "ফ্যান": "fan", "লাইট": "lamp", "সুইচ": "switch", "ঘড়ি": "clock", "বই": "book",
    "খাতা": "notebook", "কলম": "pen", "জুতা": "shoe", "স্যান্ডেল": "sandal", "ছাতা": "umbrella",
    "টাকা": "money", "মানিব্যাগ": "wallet", "ল্যাপটপ": "laptop", "টিভি": "television", "রিমোট": "remote control",
    "মানুষ": "person", "রিকশা": "cycle rickshaw", "সিএনজি": "auto rickshaw", "গাড়ি": "car", "বাস": "bus",
    "মোটরসাইকেল": "motorcycle", "সাইকেল": "bicycle", "কুকুর": "dog", "বিড়াল": "cat", "গাছ": "tree",
    "ডাস্টবিন": "trash can", "বালতি": "bucket", "চামচ": "spoon", "বাটি": "bowl", "ওষুধ": "medicine box",
}


ORDERED = [
    ("emergency", SOS_WORDS), ("stop", STOP_WORDS), ("repeat", REPEAT_WORDS),
    # Reading controls before the modes, as in the Kotlin router.
    ("pause", PAUSE_READING_WORDS), ("resume", RESUME_READING_WORDS),
    ("next", NEXT_PARAGRAPH_WORDS), ("previous", PREVIOUS_PARAGRAPH_WORDS),
    ("identify", IDENTIFY_WORDS), ("colour", COLOUR_WORDS),
    ("warnings_off", WARNINGS_OFF_WORDS), ("warnings_on", WARNINGS_ON_WORDS),
    ("ahead", WHAT_IS_AHEAD_WORDS), ("battery", BATTERY_WORDS),
    ("faster", FASTER_WORDS), ("slower", SLOWER_WORDS),
    ("bangla", SWITCH_TO_BANGLA_WORDS), ("english", SWITCH_TO_ENGLISH_WORDS),
    ("help", HELP_WORDS), ("read", READ_WORDS),
]


def normalise(text):
    return WHITESPACE.sub(" ", PUNCTUATION.sub(" ", text.lower())).strip()


# Speech recognition spells Bangla inconsistently: শ/ষ/স, ি/ী, য/জ, ড়/র and
# a dropped hasanta are the usual swaps. Both sides are folded the same way
# before comparing, so "শামনে কিআছে" still meets "সামনে কি আছে".
_FOLD = str.maketrans({
    "শ": "স", "ষ": "স",   # শ ষ -> স
    "ী": "ি", "ূ": "ু",   # ী -> ি, ূ -> ু
    "য": "জ", "য়": "জ",   # য য় -> জ
    "ড়": "র", "ঢ়": "র",   # ড় ঢ় -> র
    "ণ": "ন", "ৎ": "ত",   # ণ -> ন, ৎ -> ত
    "ঈ": "ই", "ঊ": "উ",   # ঈ -> ই, ঊ -> উ
    "ং": "ঙ",                       # ং -> ঙ
    "ঁ": None, "্": None, "়": None,  # ঁ, hasanta, nukta: dropped
})
# Decomposed forms (base + nukta) folded like the precomposed letters.
_PRE = {"ড়": "ড়", "ঢ়": "ঢ়", "য়": "য়"}


def fold(text):
    for a, b in _PRE.items():
        text = text.replace(a, b)
    return text.translate(_FOLD)


def _first_match(words, text):
    flat = text.replace(" ", "")
    for w in sorted(words, key=len, reverse=True):  # "say that again" before "again"
        fw = fold(w)
        if fw in text or fw.replace(" ", "") in flat:
            return w
    return None


def _similarity(phrase, tokens):
    """Best match of a phrase against any run of tokens, spaces ignored."""
    target = fold(phrase).replace(" ", "")
    n = max(1, phrase.count(" ") + 1)
    best = 0.0
    for size in {n - 1, n, n + 1} - {0}:
        for i in range(0, max(1, len(tokens) - size + 1)):
            chunk = "".join(tokens[i:i + size])
            if chunk:
                best = max(best, difflib.SequenceMatcher(None, chunk, target).ratio())
    return best


FIND_MARKERS = ["find", "where", "খুঁজ", "খোঁজ", "কোথায়", "কই", "koi"]
FILLER = {"the", "a", "my", "is", "for", "me", "please", "দাও", "দিন", "করো", "আমার", "টা", "টি", "তো", "প্লিজ"}


def route(utterance, fuzzy=0.72, fuzzy_find=0.55):
    """("intent", detail) — detail is the object name for ("find", obj).

    1. exact (after folding), in the Kotlin router's order, emergency first;
    2. fuzzy, for everything except emergency: a false siren in public is
       worse than asking again, so emergency needs the words or the button;
    3. with a "find/where/খুঁজো/কোথায়" word present, a looser match on the
       object name: a wrong search only looks, it does nothing.
    """
    text = fold(normalise(utterance))
    if not text:
        return ("unknown", utterance)
    for intent, words in ORDERED:
        if _first_match(words, text):
            return (intent, None)
    for obj, words in OBJECT_WORDS.items():
        if _first_match(words, text):
            return ("find", obj)

    tokens = text.split()
    best, best_score = None, fuzzy
    for intent, words in ORDERED[1:]:
        for w in words:
            sc = _similarity(w, tokens)
            if sc > best_score:
                best, best_score = (intent, None), sc
    for obj, words in OBJECT_WORDS.items():
        for w in words:
            sc = _similarity(w, tokens)
            if sc > best_score:
                best, best_score = ("find", obj), sc
    if best:
        return best

    if any(fold(m) in text for m in FIND_MARKERS):
        marker_free = [t for t in tokens if not any(fold(m) in t for m in FIND_MARKERS)]
        what = " ".join(t for t in normalise(utterance).split()
                        if not any(fold(m) in fold(t) for m in FIND_MARKERS) and t not in FILLER)
        # A known everyday object ("ব্যাগ", "চাবি") is searched for as said,
        # never loosely matched onto one of the eight.
        if any(fold(bn) in fold(what) for bn in OBJECTS_BN_EN) and not any(
                _first_match(ws, fold(what)) for ws in OBJECT_WORDS.values()):
            return ("find_text", what)
        scored = [(max(_similarity(w, marker_free) for w in ws), obj) for obj, ws in OBJECT_WORDS.items()]
        sc, obj = max(scored)
        if sc >= fuzzy_find:
            return ("find", obj)
        # Not one of the eight: "find my keys" -> ("find_text", "keys").
        if what:
            return ("find_text", what)
    return ("unknown", utterance)


def all_phrases():
    """Every phrase the router knows: a hint list for the recogniser."""
    out = [w for _, ws in ORDERED for w in ws]
    out += [w for ws in OBJECT_WORDS.values() for w in ws]
    return out

