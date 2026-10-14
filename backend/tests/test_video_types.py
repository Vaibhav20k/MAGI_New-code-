"""The video type library: every type MAGI makes has a usable template, and choices fall back safely."""
import importlib.util
import json
import sys
import types
from pathlib import Path

INPUTS = Path(__file__).parents[2] / "inputs"
for name in ("app", "app.config"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["app"].__path__ = []
sys.modules["app.config"].get_settings = lambda: types.SimpleNamespace(inputs_dir=INPUTS)
spec = importlib.util.spec_from_file_location("app.video_types", Path(__file__).parents[1] / "app" / "video_types.py")
vt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vt)

STANDARD = ["0:00-0:05", "0:05-0:12", "0:12-0:20", "0:20-0:27", "0:27-0:30"]
OPENINGS = {"everyday-friction", "sensory-detail", "material-detail", "verified-stat", "demonstration", "contrast",
            "direct-statement", "historical-discovery"}
LIB = json.loads((INPUTS / "video-types.json").read_text(encoding="utf-8"))


def test_every_type_MAGI_makes_follows_the_engine_beats():
    made = [t for t in LIB["types"] if t["generate"]]
    assert len(made) >= 10
    for t in made:
        assert [b.split(" ")[0] for b in t["beats"]] == STANDARD, t["key"]
        assert t["length_seconds"] % 30 == 0
        assert set(t["opening_forms"]) <= OPENINGS, t["key"]
        for field in ("label", "best_for", "reach", "hook", "camera", "on_screen_text", "voice", "people", "cautions"):
            assert t[field].strip(), (t["key"], field)


def test_keys_are_unique_and_the_default_can_be_made():
    keys = [t["key"] for t in LIB["types"]]
    assert len(keys) == len(set(keys))
    assert vt.get(None)["key"] == LIB["default"] and vt.get(None)["generate"]


def test_types_needing_real_footage_are_never_handed_to_the_agents():
    assert vt.get("customer_story")["key"] == LIB["default"]
    assert vt.choose("talking_head", set()) != "talking_head"


def test_the_strategists_choice_is_kept_and_repeats_are_avoided():
    assert vt.choose("reveal", set()) == "reveal"
    assert vt.choose("unknown", {"story"}) != "story"


def test_the_brief_carries_the_beats_and_cautions():
    text = vt.brief(vt.get("before_after"))
    assert "0:12-0:20" in text and "never a named brand" in text and text.startswith("VIDEO TYPE: Before and after")
