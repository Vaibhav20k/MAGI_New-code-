"""The office on the home screen shows only what is really happening. These pin the reading of the counts."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("team", Path(__file__).parents[1] / "app" / "team.py")
team = importlib.util.module_from_spec(spec)
spec.loader.exec_module(team)

QUIET = dict(pages_to_learn=0, held=0, idea_run="ready", ideas_proposed=0, blogs_writing=0, creatives_making=0,
             creatives_ready=0, videos_making=0, videos_to_approve=0)
ROLES = {"crawler", "filter", "knowledge", "strategist", "blog", "creative", "video"}


def test_a_quiet_system_has_everyone_idle():
    out = team.team_state(QUIET, crawling=False)
    assert set(out) == ROLES
    assert {r["state"] for r in out.values()} == {"idle"}


def test_a_crawl_puts_the_reading_line_to_work_and_nobody_else():
    out = team.team_state(QUIET, crawling=True, run_stats={"pages_seen": 41, "pages_kept": 9})
    assert [k for k, r in out.items() if r["state"] == "working"] == ["crawler", "filter", "knowledge"]
    assert "41 pages" in out["crawler"]["line"] and "9 kept" in out["filter"]["line"]


def test_work_in_progress_wins_over_something_waiting():
    out = team.team_state(QUIET | dict(videos_making=1, videos_to_approve=2), False, video_stage="Agent 2 of 5 · writing")
    assert out["video"] == {"state": "working", "line": "Agent 2 of 5 · writing"}


def test_waiting_roles_say_where_the_decision_is_taken():
    out = team.team_state(QUIET | dict(held=3, ideas_proposed=6, creatives_ready=1, videos_to_approve=1), False)
    assert {k: r.get("opens") for k, r in out.items() if r["state"] == "waiting"} == {
        "knowledge": "approvals", "strategist": "ideas", "creative": "content", "video": "content"}
    assert out["creative"]["line"].startswith("1 brief ") and out["knowledge"]["line"].startswith("3 learnings ")


def test_pages_still_to_learn_from_keep_knowledge_working_after_the_crawl():
    assert team.team_state(QUIET | dict(pages_to_learn=5, held=2), False)["knowledge"]["state"] == "working"
