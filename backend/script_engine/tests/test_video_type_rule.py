"""Rule 7: a video type travels with the request, reaches agent 5, and a revised script is gated like the first."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflows.config import EngineConfig                          # noqa: E402
from workflows.content_pipeline import ContentPipeline             # noqa: E402

REQUEST = {
    "request_id": "REQ-TEST-07", "topic": "Why termites find nothing to eat", "primary_objective": "Show stone gives pests nothing",
    "format": "short-form", "target_duration_seconds": 30, "target_audience": "Families building a home",
    "platform": "instagram_reels", "video_type": "before_after",
    "video_type_brief": "VIDEO TYPE: Before and after (before_after). Beats: 0:00-0:05 the before ...",
}


@pytest.fixture
def pipeline(tmp_path):
    config = EngineConfig(
        project_root=ROOT, openrouter_api_key=None, model_provider="openrouter",
        model_name="nvidia/nemotron-3-super-120b-a12b:free", temperature=0.7, max_tokens=20000,
        timeout_seconds=10, max_retries=1, runs_dir=tmp_path / "runs", schemas_dir=ROOT / "schemas",
        agents_dir=ROOT / "agents", knowledge_dir=ROOT / "knowledge")
    return ContentPipeline(config)


def test_a_request_with_a_video_type_is_accepted_and_kept(pipeline):
    pipeline.validator.assert_valid(REQUEST, "content-request.schema.json")
    pipeline.run_pipeline(dict(REQUEST), run_id="test_type", mock_mode=True)
    saved = json.loads((pipeline.config.runs_dir / "test_type" / "request.json").read_text(encoding="utf-8"))
    assert saved["video_type"] == "before_after" and saved["video_type_brief"].startswith("VIDEO TYPE")


def test_agent_5_is_told_the_video_type(pipeline, monkeypatch):
    seen = {}

    def fake_call(*a, **k):
        seen["prompt"] = json.dumps([a, k], default=str)
        raise RuntimeError("stop after the brief")
    monkeypatch.setattr(pipeline.client, "call_model", fake_call)
    with pytest.raises(Exception):
        pipeline._execute_agent_5(REQUEST, {"scenes": []}, {}, "test_type", mock_mode=False)
    assert "before_after" in seen.get("prompt", "") and "VIDEO TYPE" in seen["prompt"]


def test_a_revised_script_passes_the_production_gate_again(pipeline):
    pipeline.run_pipeline(dict(REQUEST), run_id="test_rev", mock_mode=True)
    run_dir = pipeline.config.runs_dir / "test_rev"
    before = json.loads((run_dir / "run-state.json").read_text(encoding="utf-8"))
    before.pop("continuity", None)
    (run_dir / "run-state.json").write_text(json.dumps(before), encoding="utf-8")
    pipeline.apply_approval_decision("test_rev", "REQUEST_CHANGES", "tester", "Make the before more humid.", mock_mode=True)
    after = json.loads((run_dir / "run-state.json").read_text(encoding="utf-8"))
    assert after["current_state"] == "HUMAN_APPROVAL_REQUIRED"
    assert "continuity" in after                                     # the gate ran on the revision
