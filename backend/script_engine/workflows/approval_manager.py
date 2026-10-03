import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Tuple
from workflows.schema_validator import SchemaValidator

class ApprovalManager:
    """Manages Human Approval Gate, Approval Brief rendering, and Immutable Script Locking."""

    def __init__(self, schemas_dir: Path):
        self.validator = SchemaValidator(schemas_dir)

    @staticmethod
    def compute_script_hash(script_data: Dict[str, Any]) -> str:
        """Computes a deterministic SHA-256 hash of the script content."""
        canonical_json = json.dumps(script_data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_lookbook_hash(lookbook: Dict[str, Any]) -> str:
        """The same canonical SHA-256 as the script lock, over the exact lookbook artifact."""
        canonical_json = json.dumps(lookbook, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def process_lookbook_decision(
        self,
        run_id: str,
        lookbook: Dict[str, Any],
        decision: str,
        decided_by: str,
        feedback_comments: str = ""
    ) -> Dict[str, Any]:
        """
        Processes the human decision on a lookbook: 'APPROVE' -> LOOKBOOK_APPROVED, or
        'REQUEST_CHANGES' -> LOOKBOOK_CHANGES_REQUESTED.

        The approval is bound to the exact artifact: the lookbook is validated, then
        hashed, and the hash is what is approved. A filename, a timestamp or a mutable
        reference is never enough, because Agent 5 must not run against a lookbook that
        changed after a person agreed to it.
        """
        if decision not in ["APPROVE", "REQUEST_CHANGES"]:
            raise ValueError(f"Invalid decision: '{decision}'. Must be 'APPROVE' or 'REQUEST_CHANGES'.")

        self.validator.assert_valid(lookbook, "lookbook.schema.json")
        version = int(lookbook.get("version") or 1)
        approval_data = {
            "approval_id": f"LKA-{run_id}-{version}",
            "run_id": run_id,
            "lookbook_id": lookbook.get("lookbook_id", ""),
            "lookbook_version": version,
            "lookbook_hash": self.compute_lookbook_hash(lookbook),
            "decision": decision,
            "decided_by": decided_by,
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "feedback_comments": feedback_comments,
            "status": "LOOKBOOK_APPROVED" if decision == "APPROVE" else "LOOKBOOK_CHANGES_REQUESTED",
        }
        self.validator.assert_valid(approval_data, "lookbook-approval.schema.json")
        return approval_data

    def generate_approval_brief_text(self, review_data: Dict[str, Any]) -> str:
        """Renders the human-readable Approval Brief."""
        brief = review_data.get("approval_brief", {})
        qa = review_data.get("qa_summary", {})
        script = review_data.get("final_script", {})
        issues = review_data.get("issues_detected", [])

        lines = [
            "=" * 70,
            "MAGPPIE CONTENT INTELLIGENCE — HUMAN APPROVAL BRIEF",
            "=" * 70,
            f"TITLE:             {brief.get('title', script.get('title', 'N/A'))}",
            f"FORMAT:            {brief.get('format', script.get('format', 'N/A'))}",
            f"DURATION:          {brief.get('duration', str(script.get('actual_duration_seconds', 0)) + 's')}",
            f"CORE IDEA:         {brief.get('core_idea', 'N/A')}",
            f"FEATURED PRODUCT:  {brief.get('featured_product', 'N/A')}",
            "-" * 70,
            "KEY CLAIMS VERIFIED:",
        ]
        for c in brief.get("key_claims_verified", []):
            lines.append(f"  • {c}")

        lines.extend([
            "-" * 70,
            f"EVIDENCE SUMMARY:  {brief.get('evidence_summary', 'N/A')}",
            f"PRODUCT SUMMARY:   {brief.get('product_claim_summary', 'N/A')}",
            "-" * 70,
            "QA SUMMARY:",
            f"  • Historical QA:    {qa.get('historical_qa', 'N/A')}",
            f"  • Scientific QA:    {qa.get('scientific_qa', 'N/A')}",
            f"  • Product Truth QA: {qa.get('product_truth_qa', 'N/A')}",
            f"  • Brand Voice QA:   {qa.get('brand_voice_qa', 'N/A')}",
            f"  • Pacing & Timing:  {qa.get('pacing_and_duration_qa', 'N/A')}",
            "-" * 70,
            "RISK FLAGS:",
        ])
        risk_flags = brief.get("risk_flags", [])
        if not risk_flags:
            lines.append("  • None detected.")
        else:
            for rf in risk_flags:
                lines.append(f"  [FLAG] {rf}")

        lines.extend([
            "-" * 70,
            "FINAL SCRIPT NARRATION & SCENES:",
        ])
        for scene in script.get("scenes", []):
            lines.append(f"\n[Scene {scene.get('scene_number')} | {scene.get('time_range')}]")
            lines.append(f"Visual: {scene.get('visual_direction')}")
            lines.append(f"Narration: \"{scene.get('narration')}\"")
            if scene.get("on_screen_text"):
                lines.append(f"On-Screen: {scene.get('on_screen_text')}")

        lines.extend([
            "-" * 70,
            f"CALL TO ACTION: {script.get('call_to_action', {}).get('cta_text', '')}",
            "=" * 70,
        ])
        return "\n".join(lines)

    def process_decision(
        self,
        run_id: str,
        script_id: str,
        script_version: int,
        final_script: Dict[str, Any],
        decision: str,
        decided_by: str,
        feedback_comments: str = ""
    ) -> Dict[str, Any]:
        """
        Processes human decision: 'APPROVE' -> SCRIPT_LOCKED or 'REQUEST_CHANGES' -> REVISION_REQUESTED.
        """
        if decision not in ["APPROVE", "REQUEST_CHANGES"]:
            raise ValueError(f"Invalid decision: '{decision}'. Must be 'APPROVE' or 'REQUEST_CHANGES'.")

        script_hash = self.compute_script_hash(final_script)
        status = "SCRIPT_LOCKED" if decision == "APPROVE" else "REVISION_REQUESTED"
        timestamp = datetime.now(timezone.utc).isoformat()

        approval_data = {
            "approval_id": f"APP-{run_id}-{script_version}",
            "run_id": run_id,
            "script_id": script_id,
            "script_version": script_version,
            "decision": decision,
            "decided_by": decided_by,
            "decided_at": timestamp,
            "feedback_comments": feedback_comments,
            "status": status,
            "script_hash": script_hash
        }

        self.validator.assert_valid(approval_data, "approval.schema.json")
        return approval_data
