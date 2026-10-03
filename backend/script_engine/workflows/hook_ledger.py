"""
Hook & Angle Memory Ledger.

One rolling file records what the engine has already said and, more importantly,
*how* it said it: the angle family and the opening construction. String-level
memory was not enough — three runs on the same topic produced three different
sentences that all argued the same point, because nothing remembered the angle.

Pure file I/O. No model calls, so this is directly unit-testable.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("MagppieEngine.HookLedger")

LEDGER_DIRNAME = "_memory"
LEDGER_FILENAME = "hook-ledger.json"
MAX_ENTRIES = 40

# Run-id prefixes whose output is fixture data, not editorial history. These must
# never influence a live run's diversity decisions.
FIXTURE_PREFIXES = ("test_", "bench_", "demo")


def _is_fixture_run(run_id: str) -> bool:
    return run_id.startswith(FIXTURE_PREFIXES)


class HookLedger:
    """Append-only, newest-first record of accepted hooks and their angles."""

    def __init__(self, runs_dir: Path):
        self.path = Path(runs_dir) / LEDGER_DIRNAME / LEDGER_FILENAME

    # ---------------- reads ----------------

    def read(self, limit: int = MAX_ENTRIES) -> List[Dict[str, Any]]:
        """Newest-first entries. A missing or corrupt ledger reads as empty."""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Hook ledger at %s is unreadable; treating as empty.", self.path)
            return []
        if not isinstance(data, list):
            return []
        entries = [e for e in data if isinstance(e, dict) and e.get("hook_text")]
        return entries[:limit]

    def recent_hook_texts(self, limit: int = 20) -> List[str]:
        return [e["hook_text"] for e in self.read(limit)]

    def used_combinations(
        self, topic: Optional[str] = None, same_topic_depth: int = 3, global_depth: int = 2
    ) -> Set[Tuple[str, str]]:
        """
        The banned set: (angle_family, opening_form) pairs the engine should not
        reuse. Same-topic history is weighted harder than global history, because
        repetition on one topic is what a viewer actually notices.
        """
        entries = self.read()
        banned: Set[Tuple[str, str]] = set()

        def pair(entry: Dict[str, Any]) -> Optional[Tuple[str, str]]:
            family, form = entry.get("angle_family"), entry.get("opening_form")
            return (family, form) if family and form else None

        for entry in entries[:global_depth]:
            found = pair(entry)
            if found:
                banned.add(found)

        if topic:
            key = topic.strip().lower()
            same = [e for e in entries if (e.get("topic") or "").strip().lower() == key]
            for entry in same[:same_topic_depth]:
                found = pair(entry)
                if found:
                    banned.add(found)
        return banned

    def used_families(self, topic: Optional[str] = None, depth: int = 3) -> Set[str]:
        """Angle families recently used, so a prompt can name what to avoid."""
        entries = self.read()
        if topic:
            key = topic.strip().lower()
            entries = [e for e in entries if (e.get("topic") or "").strip().lower() == key]
        return {e["angle_family"] for e in entries[:depth] if e.get("angle_family")}

    # ---------------- writes ----------------

    def append(
        self,
        hook_text: str,
        run_id: str,
        topic: str = "",
        angle_family: Optional[str] = None,
        opening_form: Optional[str] = None,
        claim_ids_used: Optional[List[str]] = None,
    ) -> bool:
        """
        Record an accepted hook. Fixture runs are skipped so tests and benchmarks
        never poison real editorial memory. Returns True when something was written.
        """
        if not hook_text or not hook_text.strip():
            return False
        if _is_fixture_run(run_id):
            return False

        entries = self.read(MAX_ENTRIES)
        # Re-recording the same run (e.g. after a revision loop) replaces it
        # rather than stacking duplicates.
        entries = [e for e in entries if e.get("run_id") != run_id]

        entries.insert(0, {
            "hook_text": hook_text.strip(),
            "angle_family": angle_family,
            "opening_form": opening_form,
            "claim_ids_used": claim_ids_used or [],
            "topic": topic,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(entries[:MAX_ENTRIES], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
