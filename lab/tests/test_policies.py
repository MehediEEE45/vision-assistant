import pytest

from va_lab import config, intent, safety
from va_lab.obstacle import ObstaclePolicy


@pytest.mark.parametrize("phrase,result", [("stop", ("stop", None)), ("থামো", ("stop", None)),
    ("emergency", ("emergency", None)), ("সামনে কী আছে", ("ahead", None)),
    ("read this", ("read", None)), ("chair টা কোথায়", ("find", "chair"))])
def test_bilingual_intents(phrase, result):
    assert intent.route(phrase) == result


def test_generated_safety_promises_are_removed():
    assert safety.clean("A chair is ahead. The path is clear.") == "A chair is ahead."
    assert safety.clean("একটি চেয়ার আছে। পথ পরিষ্কার।") == "একটি চেয়ার আছে।"
    safety.check_fixed([t for p in config.load_prompts().values() for t in p.values()])


def test_obstacles_require_confirmation_and_escalate():
    policy = ObstaclePolicy()
    assert policy.on_sample("ahead", 1000, 1000) is None
    assert policy.on_sample("ahead", 1000, 1050) is None
    assert policy.on_sample("ahead", 1000, 1100).band == "near"
    assert policy.on_sample("ahead", 1000, 1150) is None
    assert policy.on_sample("ahead", 500, 1200) is None
    assert policy.on_sample("ahead", 500, 1250) is None
    assert policy.on_sample("ahead", 500, 1300).band == "immediate"
