"""Choosing the real kitchen for a video: fit first, real and reviewed preferred, never the last few again."""
import importlib.util
import sys
import types
from pathlib import Path

for name in ("app", "app.db", "app.embed"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["app"].__path__ = []
spec = importlib.util.spec_from_file_location("app.kitchens", Path(__file__).parents[1] / "app" / "kitchens.py")
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)


def row(i, sim, finish, source="render", reviewed=False):
    return {"id": i, "similarity": sim, "finish": finish, "source": source, "reviewed": reviewed}


def test_the_best_fit_comes_first():
    got = k.rank([row(1, .60, "CALM"), row(2, .75, "EARTH"), row(3, .70, "AMBER")], set(), set(), 3)
    assert [r["id"] for r in got] == [2, 3, 1]


def test_a_real_reviewed_photo_beats_a_slightly_closer_render():
    got = k.rank([row(1, .72, "CALM"), row(2, .66, "EARTH", source="real", reviewed=True)], set(), set(), 2)
    assert got[0]["id"] == 2


def test_recent_kitchens_are_left_out_and_recent_finishes_count_against():
    got = k.rank([row(1, .80, "CALM"), row(2, .70, "EARTH"), row(3, .66, "AMBER")], {1}, {"EARTH"}, 3)
    assert [r["id"] for r in got] == [3, 2]


def test_the_list_prefers_a_different_finish_on_each_line():
    got = k.rank([row(1, .80, "CALM"), row(2, .79, "CALM"), row(3, .60, "EARTH")], set(), set(), 2)
    assert [r["finish"] for r in got] == ["CALM", "EARTH"]


def test_the_brief_never_lets_the_finish_into_the_voice():
    text = k.as_brief({"layout": "island", "finish": "MAGPPIE CALM", "description": "A wide island kitchen."})
    assert "island" in text and "MAGPPIE CALM" in text and "never say it" in text
