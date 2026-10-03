"""
The production phases after SCRIPT_LOCKED: lookbook, lookbook approval, video prompts.

No model call and no API key: agents 4 and 5 run on their fixtures. What is tested is
the part that must never depend on a model: state boundaries, hashing, approval
invalidation, the exact parts of a prompt, and the artifacts on disk.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflows import production                                   # noqa: E402
from workflows.config import EngineConfig                          # noqa: E402
from workflows.content_pipeline import ContentPipeline             # noqa: E402

REQUEST = {
    "request_id": "REQ-TEST-01", "topic": "The Turmeric Test", "primary_objective": "Show that turmeric wipes off stone",
    "format": "short-form", "target_duration_seconds": 30, "target_audience": "Families building a home",
    "platform": "instagram_reels", "featured_product_category": "MAGPPIE Wellness Kitchen in SILVERSTONE engineered stone",
}


def directed(scenes: int = 1) -> dict:
    """A locked directed script in the shape the script phase leaves behind."""
    frames = [f"Frame {n}: a hand above the stone counter in morning light." for n in range(scenes + 1)]
    made = []
    for n in range(1, scenes + 1):
        lines = ["Turmeric stains for days.", "On stone it sits on the surface.", "One wipe lifts it.",
                 "No swelling, no staining.", "Built once, for generations."]
        made.append({
            "scene_number": n, "time_range": f"00:{(n - 1) * 30:02d} - 00:{n * 30:02d}" if n * 30 < 60 else f"00:{(n - 1) * 30:02d} - 01:00",
            "visual_direction": "A turmeric test on a stone counter.", "narration": " ".join(lines),
            "on_screen_text": "Go check your kitchen." if n == scenes else "", "audio_cues": "A quiet kitchen.",
            "entry_frame": frames[n - 1], "exit_frame": frames[n],
            "transition_to_next": "Camera continues moving",
            "directions": {"location": "Sun-lit kitchen, morning", "characters": "C1", "action": "She tests the stone with turmeric",
                           "emotion": "Her brow eases as the cloth lifts the paste", "shot_type": "close-up",
                           "camera_movement": "slow push-in", "lens": "35mm", "lighting": "Soft window light from the left",
                           "colour_grade": "Warm neutrals", "sound": "A quiet kitchen"},
            "beats": [{"beat_number": i + 1, "time_range": r, "action": f"Action {i + 1} on the stone counter.",
                       "camera": "Slow push-in.", "emotion": "Her eyes follow the cloth.", "narration": lines[i],
                       "delivery": "Unhurried, a short breath after the line."}
                      for i, r in enumerate(["0:00-0:05", "0:05-0:12", "0:12-0:20", "0:20-0:27", "0:27-0:30"])],
            "voice_direction": {"tone": "Low and close", "pace": "Easy", "pauses": "After the test", "emphasis": "stone"},
        })
    return {
        "title": "The Turmeric Test", "format": "short-form", "target_duration_seconds": scenes * 30,
        "hook": {"hook_text": "Turmeric stains for days."},
        "continuity_bible": {
            "characters": [{"continuity_id": "C1", "description": "Woman, mid-30s, cotton kurti, hair tied back"}],
            "set_location": "Sun-lit kitchen with a stone island", "lighting": "Soft window light from the left",
            "colour_grade": "Warm neutrals", "camera_language": "35mm, subtle gimbal",
            "voice": "A calm woman in her 30s, close to the microphone", "product": "MAGPPIE Wellness Kitchen in SILVERSTONE",
        },
        "scenes": made,
        "call_to_action": {"cta_text": "Book a free consultation."},
    }


@pytest.fixture
def pipeline(tmp_path):
    config = EngineConfig(
        project_root=ROOT, openrouter_api_key=None, model_provider="openrouter",
        model_name="nvidia/nemotron-3-super-120b-a12b:free", temperature=0.7, max_tokens=20000,
        timeout_seconds=10, max_retries=1, runs_dir=tmp_path / "runs", schemas_dir=ROOT / "schemas",
        agents_dir=ROOT / "agents", knowledge_dir=ROOT / "knowledge")
    return ContentPipeline(config)


def locked_run(pipeline, run_id="test_locked", scenes=1, approve=True) -> Path:
    """A run taken through the script phase on fixtures, with a directed script on file."""
    pipeline.run_pipeline(dict(REQUEST, target_duration_seconds=scenes * 30), run_id=run_id,
                          auto_approve=approve, mock_mode=True)
    run_dir = pipeline.config.runs_dir / run_id
    (run_dir / "directed-script.json").write_text(json.dumps(directed(scenes)), encoding="utf-8")
    return run_dir


def state_of(run_dir: Path) -> dict:
    return json.loads((run_dir / "run-state.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ lookbook phase

def test_lookbook_cannot_start_before_the_script_is_locked(pipeline):
    run_dir = locked_run(pipeline, approve=False)
    assert state_of(run_dir)["current_state"] == "HUMAN_APPROVAL_REQUIRED"
    with pytest.raises(ValueError, match="SCRIPT_LOCKED"):
        pipeline.run_lookbook_phase("test_locked", mock_mode=True)
    assert not (run_dir / "lookbook.json").exists()


def test_locked_script_creates_a_valid_lookbook(pipeline):
    run_dir = locked_run(pipeline, scenes=2)
    result = pipeline.run_lookbook_phase("test_locked", mock_mode=True)
    assert result["status"] == "LOOKBOOK_APPROVAL_REQUIRED"
    assert state_of(run_dir)["current_state"] == "LOOKBOOK_APPROVAL_REQUIRED"
    lookbook = json.loads((run_dir / "lookbook.json").read_text(encoding="utf-8"))
    pipeline.validator.assert_valid(lookbook, "lookbook.schema.json")
    assert lookbook["film_overview"]["scene_count"] == 2 and lookbook["film_overview"]["duration_seconds"] == 60
    assert 5 <= len(lookbook["film_overview"]["colour_palette"]) <= 6
    for scene in lookbook["scenes"]:
        assert all(scene[k] for k in ("entry_keyframe", "key_moment_keyframe", "exit_keyframe"))
    # Rule 3.1: scene 1's exit frame and scene 2's entry frame are one frame
    assert lookbook["scenes"][1]["entry_keyframe"] == lookbook["scenes"][0]["exit_keyframe"]
    html = (run_dir / "lookbook.html").read_text(encoding="utf-8")
    assert "Storyboard" in html and "#C77B4A" in html and "SCENE 1 EXIT" in html


def test_lookbook_never_carries_the_narration_as_its_own(pipeline):
    locked_run(pipeline)
    lookbook = pipeline.run_lookbook_phase("test_locked", mock_mode=True)["lookbook"]
    assert "narration" not in json.dumps(lookbook)


def test_invalid_lookbook_does_not_reach_approval(pipeline, monkeypatch):
    run_dir = locked_run(pipeline)
    broken = pipeline._mock_agent_4(REQUEST, directed())
    broken["scenes"] = []                                       # drops the script's only scene
    monkeypatch.setattr(pipeline, "_mock_agent_4", lambda request, script: broken)
    with pytest.raises(production.ProductionError):
        pipeline.run_lookbook_phase("test_locked", mock_mode=True)
    state = state_of(run_dir)
    assert state["current_state"] == "MVP_COMPLETE" and state["lookbook"]["error"]
    assert not (run_dir / "lookbook.json").exists()


def test_a_keyframe_may_not_ask_for_text_in_the_frame():
    script = directed()
    lookbook = production.finish_lookbook(ContentPipeline._mock_agent_4(REQUEST, script), script, REQUEST, "r", 1)
    assert production.check_lookbook(lookbook, script) == []
    lookbook["scenes"][0]["exit_keyframe"]["subject"] = "The counter, with the title text displayed across it."
    assert any(f["category"] == "Realism" for f in production.check_lookbook(lookbook, script))
    lookbook["scenes"][0]["exit_keyframe"]["subject"] = "The clean counter. No on-screen text in the frame."
    assert production.check_lookbook(lookbook, script) == []


def test_a_callers_own_rules_can_reject_a_lookbook(pipeline):
    locked_run(pipeline)
    pipeline.extra_checks = lambda kind, artifact: [
        {"severity": "CRITICAL", "category": "Brand", "description": f"{kind} breaks a brand rule"}]
    with pytest.raises(production.ProductionError, match="brand rule"):
        pipeline.run_lookbook_phase("test_locked", mock_mode=True)


# --------------------------------------------------------------- lookbook approval

def test_approval_records_the_hash_of_the_exact_lookbook(pipeline):
    run_dir = locked_run(pipeline)
    lookbook = pipeline.run_lookbook_phase("test_locked", mock_mode=True)["lookbook"]
    result = pipeline.apply_lookbook_decision("test_locked", "APPROVE", "Reviewer")
    assert result["status"] == "LOOKBOOK_APPROVED"
    record = json.loads((run_dir / "lookbook-approval.json").read_text(encoding="utf-8"))
    assert record["decision"] == "APPROVE" and record["run_id"] == "test_locked" and record["decided_at"]
    assert record["lookbook_hash"] == production.artifact_hash(lookbook)
    state = state_of(run_dir)
    assert state["current_state"] == "LOOKBOOK_APPROVED" and state["lookbook"]["approved_hash"] == record["lookbook_hash"]


def test_a_changed_lookbook_invalidates_its_approval(pipeline):
    run_dir = locked_run(pipeline)
    pipeline.run_lookbook_phase("test_locked", mock_mode=True)
    pipeline.apply_lookbook_decision("test_locked", "APPROVE", "Reviewer")
    lookbook = json.loads((run_dir / "lookbook.json").read_text(encoding="utf-8"))
    lookbook["film_overview"]["mood_words"] = ["loud", "busy", "bright"]
    (run_dir / "lookbook.json").write_text(json.dumps(lookbook), encoding="utf-8")
    with pytest.raises(ValueError, match="changed after it was approved"):
        pipeline.run_video_prompt_phase("test_locked", mock_mode=True)
    state = state_of(run_dir)
    assert state["current_state"] == "LOOKBOOK_APPROVAL_REQUIRED"
    assert state["lookbook"]["status"] == "APPROVAL_INVALIDATED" and state["lookbook"]["approved_hash"] is None
    assert not (run_dir / "video-prompts.json").exists()


def test_request_changes_returns_a_new_version_for_review(pipeline):
    run_dir = locked_run(pipeline)
    pipeline.run_lookbook_phase("test_locked", mock_mode=True)
    result = pipeline.apply_lookbook_decision("test_locked", "REQUEST_CHANGES", "Reviewer", "Darker stone", mock_mode=True)
    assert result["status"] == "LOOKBOOK_APPROVAL_REQUIRED" and result["lookbook"]["version"] == 2
    assert (run_dir / "lookbook-v1.json").exists()              # the reviewed version is kept
    state = state_of(run_dir)
    assert state["lookbook"]["revision_count"] == 1 and state["lookbook"]["approved_hash"] is None
    with pytest.raises(ValueError, match="revision limit"):     # no endless loop
        pipeline.apply_lookbook_decision("test_locked", "REQUEST_CHANGES", "Reviewer", "Again", mock_mode=True)
    assert pipeline.apply_lookbook_decision("test_locked", "APPROVE", "Reviewer")["status"] == "LOOKBOOK_APPROVED"


def test_a_lookbook_decision_needs_a_lookbook_awaiting_one(pipeline):
    locked_run(pipeline)
    with pytest.raises(ValueError, match="LOOKBOOK_APPROVAL_REQUIRED"):
        pipeline.apply_lookbook_decision("test_locked", "APPROVE", "Reviewer")
    pipeline.run_lookbook_phase("test_locked", mock_mode=True)
    with pytest.raises(ValueError, match="Invalid decision"):
        pipeline.apply_lookbook_decision("test_locked", "MAYBE", "Reviewer")


# --------------------------------------------------------------------- video phase

def test_video_prompts_cannot_run_without_an_approved_lookbook(pipeline):
    run_dir = locked_run(pipeline)
    with pytest.raises(ValueError, match="LOOKBOOK_APPROVED"):
        pipeline.run_video_prompt_phase("test_locked", mock_mode=True)
    pipeline.run_lookbook_phase("test_locked", mock_mode=True)
    with pytest.raises(ValueError, match="LOOKBOOK_APPROVED"):  # drafted, but nobody approved it
        pipeline.run_video_prompt_phase("test_locked", mock_mode=True)
    assert not (run_dir / "video-prompts.json").exists()


def complete(pipeline, scenes=1) -> Path:
    run_dir = locked_run(pipeline, scenes=scenes)
    pipeline.run_lookbook_phase("test_locked", mock_mode=True)
    pipeline.apply_lookbook_decision("test_locked", "APPROVE", "Reviewer")
    result = pipeline.run_video_prompt_phase("test_locked", mock_mode=True)
    assert result["status"] == "PRODUCTION_PACKAGE_COMPLETE"
    return run_dir


def test_a_full_run_reaches_production_package_complete(pipeline):
    run_dir = complete(pipeline, scenes=2)
    state = state_of(run_dir)
    assert state["current_state"] == "PRODUCTION_PACKAGE_COMPLETE" and state["production"]["gate"]["verdict"] == "PASS"
    pipeline.validator.assert_valid(state, "run-state.schema.json")
    for name in ("lookbook.json", "lookbook.html", "lookbook-approval.json", "video-prompts.json",
                 "video-prompts.md", "edit-sheet.md"):
        assert (run_dir / name).exists(), name
    package = json.loads((run_dir / "video-prompts.json").read_text(encoding="utf-8"))
    pipeline.validator.assert_valid(package, "video-prompts.schema.json")
    assert package["lookbook_hash"] == state["lookbook"]["approved_hash"]
    assert package["script_hash"] == json.loads((run_dir / "approval.json").read_text())["script_hash"]


def test_every_scene_prompt_carries_the_exact_parts(pipeline):
    run_dir = complete(pipeline, scenes=2)
    script = directed(2)
    package = json.loads((run_dir / "video-prompts.json").read_text(encoding="utf-8"))
    bible = production.continuity_text(script["continuity_bible"])
    negative = production.negative_prompt((ROOT / "SKILL.md").read_text(encoding="utf-8"))
    assert "plastic skin" in negative and "slow-motion overuse" in negative
    assert len(package["scene_prompts"]) == 2
    for prompt, scene in zip(package["scene_prompts"], script["scenes"]):
        assert prompt["continuity_bible"] == bible == package["continuity_bible"]      # word for word
        assert prompt["negative_prompt"] == negative
        assert [b["time_range"] for b in prompt["beats"]] == [b["time_range"] for b in scene["beats"]]
        assert prompt["start_frame"]["entry_frame"] == scene["entry_frame"]
        assert prompt["exit_frame"]["exit_frame"] == scene["exit_frame"]
        assert " ".join(l["line"] for l in prompt["vo"]["lines"]) == scene["narration"]   # the locked words
        assert prompt["shot"] and prompt["lens"] and prompt["movement"] and len(prompt["realism_cues"]) >= 3
        order = [prompt["prompt_text"].index(h) for h in (
            "CONTINUITY BIBLE", "START FRAME", "BEAT-BY-BEAT ACTION", "SHOT / LENS / MOVEMENT", "REALISM CUES",
            "EXIT FRAME", "NEGATIVE PROMPT", "AUDIO / VO", "TEXT FOR EDIT")]
        assert order == sorted(order)
    assert package["scene_prompts"][1]["text_overlays"][0]["text"] == "Go check your kitchen."
    assert "TEXT FOR EDIT" in package["scene_prompts"][1]["text_overlays"][0]["note"]


def test_the_edit_sheet_covers_every_scene(pipeline):
    run_dir = complete(pipeline, scenes=2)
    package = json.loads((run_dir / "video-prompts.json").read_text(encoding="utf-8"))
    rows = package["edit_sheet"]["scenes"]
    assert [r["scene_number"] for r in rows] == [1, 2] and all(r["duration_seconds"] == 30 for r in rows)
    assert rows[0]["exit_frame"] == rows[1]["entry_frame"]
    assert rows[0]["transition"] == "Camera continues moving" and rows[1]["transition"].startswith("End of film")
    sheet = (run_dir / "edit-sheet.md").read_text(encoding="utf-8")
    assert "## Scene 2" in sheet and "scene-01.mp4" in sheet and "Whole film" in sheet


def test_a_package_gate_catches_what_must_be_exact(pipeline):
    script = directed()
    lookbook = production.finish_lookbook(ContentPipeline._mock_agent_4(REQUEST, script), script, REQUEST, "r", 1)
    negative = production.negative_prompt((ROOT / "SKILL.md").read_text(encoding="utf-8"))
    package = production.build_package(ContentPipeline._mock_agent_5(script, lookbook), script, lookbook, REQUEST,
                                       "r", "a" * 64, "b" * 64, negative)
    assert production.check_video_prompts(package, script, "a" * 64, "b" * 64, negative) == []
    package["scene_prompts"][0]["continuity_bible"] = "A kitchen, more or less."
    package["scene_prompts"][0]["negative_prompt"] = "ugly"
    package["scene_prompts"][0]["beats"].pop()
    package["scene_prompts"][0]["vo"]["lines"][0]["line"] = "A new line nobody approved."
    found = {f["category"] for f in production.check_video_prompts(package, script, "a" * 64, "c" * 64, negative)}
    assert {"Continuity", "Realism", "Direction", "Voice-over", "Traceability"} <= found


def test_the_editors_words_reach_the_beats():
    beats = [{"beat_number": 1, "time_range": "0:00-0:15", "narration": "It resists water, heat and termites."},
             {"beat_number": 2, "time_range": "0:15-0:30", "narration": "Built once."}]
    fixed = production.align_beats("It resists water, and termites find nothing to eat. Built once.", beats)
    assert fixed[0]["narration"] == "It resists water, and termites find nothing to eat."
    assert fixed[1]["narration"] == "Built once."
    dropped = production.align_beats("One sentence only now.", beats)
    assert [b["narration"] for b in dropped] == ["", ""]
    three = beats + [{"beat_number": 3, "time_range": "0:27-0:30", "narration": "Old closing line."}]
    partly = production.align_beats("It resists water, heat and termites. Built once. It stays clean. Safe for the family.", three)
    assert [b["narration"] for b in partly] == ["It resists water, heat and termites.", "Built once.", "It stays clean. Safe for the family."]


# -------------------------------------------------------------------- state safety

@pytest.mark.parametrize("phase", ["run_lookbook_phase", "run_video_prompt_phase"])
def test_unknown_or_unsafe_run_ids_are_rejected(pipeline, phase):
    with pytest.raises(FileNotFoundError):
        getattr(pipeline, phase)("no_such_run", mock_mode=True)
    with pytest.raises(ValueError):
        getattr(pipeline, phase)("../outside", mock_mode=True)


def test_phases_cannot_be_replayed_out_of_order(pipeline):
    complete(pipeline)
    with pytest.raises(ValueError):                             # the package is complete: no second lookbook
        pipeline.run_lookbook_phase("test_locked", mock_mode=True)
    with pytest.raises(ValueError):
        pipeline.apply_lookbook_decision("test_locked", "APPROVE", "Reviewer")
    with pytest.raises(ValueError):
        pipeline.run_video_prompt_phase("test_locked", mock_mode=True)


def test_a_script_changed_after_locking_stops_production(pipeline):
    run_dir = locked_run(pipeline)
    review = json.loads((run_dir / "editorial-review.json").read_text(encoding="utf-8"))
    review["final_script"]["title"] = "A different film"
    (run_dir / "editorial-review.json").write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="changed after it was locked"):
        pipeline.run_lookbook_phase("test_locked", mock_mode=True)
