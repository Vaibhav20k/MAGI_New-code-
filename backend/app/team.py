"""What each role of the marketing department is doing right now, for the office on the home screen.

Nothing here is invented: every state is read off the counts MAGI already keeps. A role is `working` while its
own job is in progress, `waiting` when something of its making needs a person's decision, and `idle` otherwise.
`opens` names the dashboard tab where that decision is taken.
"""


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def team_state(c: dict, crawling: bool, run_stats: dict | None = None, video_stage: str | None = None) -> dict:
    """The seven roles, keyed as the home screen keys them. `c` holds the counts; see magi.team for the query."""
    stats = run_stats or {}
    working = lambda line: {"state": "working", "line": line}
    waiting = lambda line, opens: {"state": "waiting", "line": line, "opens": opens}
    idle = lambda line: {"state": "idle", "line": line}

    out = {}
    out["crawler"] = (working(f"Reading the web now · {_n(int(stats.get('pages_seen') or 0), 'page')} this run")
                      if crawling else idle("Resting until 8 PM, when the night's reading starts"))
    out["filter"] = (working(f"Sorting what the crawler finds · {int(stats.get('pages_kept') or 0)} kept this run")
                     if crawling else idle("Nothing to sort until the crawler reads"))
    if crawling or c.get("pages_to_learn"):
        out["knowledge"] = working("Turning pages into learnings")
    elif c.get("held"):
        out["knowledge"] = waiting(f"{_n(c['held'], 'learning')} wait for the manager", "approvals")
    else:
        out["knowledge"] = idle("Every page read so far has been learned from")
    if c.get("idea_run") == "running":
        out["strategist"] = working("Choosing new ideas")
    elif c.get("ideas_proposed"):
        out["strategist"] = waiting(f"{_n(c['ideas_proposed'], 'idea')} wait for your approval", "ideas")
    else:
        out["strategist"] = idle("No idea run in progress")
    out["blog"] = (working(f"Writing {_n(c['blogs_writing'], 'blog')}") if c.get("blogs_writing")
                   else idle("No blog being written"))
    if c.get("creatives_making"):
        out["creative"] = working(f"Making {_n(c['creatives_making'], 'creative')}")
    elif c.get("creatives_ready"):
        out["creative"] = waiting(f"{_n(c['creatives_ready'], 'brief')} ready for you to generate", "content")
    else:
        out["creative"] = idle("No creative in progress")
    if c.get("videos_making"):
        out["video"] = working(video_stage or f"Working on {_n(c['videos_making'], 'video')}")
    elif c.get("videos_to_approve"):
        out["video"] = waiting(f"{_n(c['videos_to_approve'], 'video')} wait for your approval", "content")
    else:
        out["video"] = idle("No script or video in progress")
    return out
