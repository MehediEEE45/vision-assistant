"""Fixed sentences the laptop modes say, in both languages.

Unlike prompts.csv these are laptop-only and are synthesised (tts.py) rather
than recorded. Every one is checked against the banned-phrase list at import
(safety.py): the rule that the app never promises safety applies here too.
"""

P = {
    # modes
    "mode_read": ("পড়ার মোড। পাতাটা ক্যামেরার সামনে ধরুন।", "Read mode. Hold the page in front of the camera."),
    "mode_find": ("খোঁজার মোড।", "Find mode."),
    "mode_describe": ("দেখছি।", "Looking."),
    "mode_identify": ("চেনার মোড। জিনিসটা ক্যামেরার মাঝখানে ধরুন।", "Identify mode. Hold the object in the middle of the camera."),
    "mode_idle": ("মোড বন্ধ।", "Mode off."),
    "ask_find": ("কী খুঁজবেন? টোনের পরে বলুন।", "What should I find? Say it after the tone."),
    "help": ("চারটি মোড আছে। পড়তে আর, খুঁজতে এফ, বর্ণনার জন্য ডি, চিনতে আই চাপুন। অথবা স্পেস চেপে বলুন: পড়ো, দরজা খোঁজো, সামনে কী আছে, এটা কী।",
             "There are four modes. Press R to read, F to find, D to describe, I to identify. Or press space and say: read, find the door, what is ahead, what is this."),
    # capture assistance
    "cap_no_text": ("কোনো লেখা দেখছি না।", "I see no text."),
    "cap_move_left": ("পাতাটা বামে সরান।", "Move the page to the left."),
    "cap_move_right": ("পাতাটা ডানে সরান।", "Move the page to the right."),
    "cap_move_up": ("পাতাটা উপরে তুলুন।", "Move the page up."),
    "cap_move_down": ("পাতাটা নিচে নামান।", "Move the page down."),
    "cap_closer": ("আরো কাছে আনুন।", "Bring it closer."),
    "cap_farther": ("একটু দূরে সরান।", "Move it a little further away."),
    "cap_steady": ("স্থির রাখুন।", "Hold steady."),
    "cap_dark": ("আলো কম। আলোর দিকে ধরুন।", "The light is low. Turn towards the light."),
    "cap_ok": ("ঠিক আছে, পড়ছি।", "Good, reading."),
    "ocr_warning": ("অফলাইন পড়া, ভুল থাকতে পারে।", "Offline reading; there may be mistakes."),
    "read_none": ("পড়ার মতো লেখা পাওয়া যায়নি।", "No readable text found."),
    "read_done": ("পড়া শেষ।", "Finished reading."),
    "read_paused": ("বিরতি।", "Paused."),
    "read_first": ("এটাই প্রথম অনুচ্ছেদ।", "This is the first paragraph."),
    # find
    "find_lost": ("হারিয়ে গেছে, ধীরে ঘুরুন।", "Lost it. Turn slowly."),
    "find_unknown": ("এই জিনিসটা চিনতে পারছি না, অন্য নাম বলুন।", "I don't know that object. Try another name."),
    # describe / identify
    "low_light": ("আলো কম, বর্ণনা ভুল হতে পারে।", "The light is low; this may be wrong."),
    "nothing_centre": ("মাঝখানে কিছু দেখছি না। জিনিসটা ক্যামেরার মাঝখানে ধরুন।", "Nothing in the middle. Hold the object in the middle of the camera."),
    "it_seems": ("মনে হচ্ছে", "It looks like"),
    "colour": ("রং", "Colour"),
    "text_on_it": ("লেখা আছে", "The text says"),
    "no_text_on_it": ("কোনো লেখা পড়া গেল না।", "No text could be read."),
    "follow_up": ("আরো জানতে বলুন: রং কী, লেখা পড়ো।", "Ask: what colour, or read the text."),
    "working": ("একটু অপেক্ষা করুন।", "One moment."),
}

COLOURS = {
    "red": ("লাল", "red"), "orange": ("কমলা", "orange"), "yellow": ("হলুদ", "yellow"),
    "green": ("সবুজ", "green"), "blue": ("নীল", "blue"), "purple": ("বেগুনি", "purple"),
    "pink": ("গোলাপি", "pink"), "brown": ("বাদামি", "brown"), "black": ("কালো", "black"),
    "white": ("সাদা", "white"), "grey": ("ধূসর", "grey"),
}


def text(key, bangla):
    bn, en = P[key]
    return (bn, "bn") if bangla else (en, "en")


def all_texts():
    out = []
    for bn, en in P.values():
        out += [(bn, "bn"), (en, "en")]
    return out
