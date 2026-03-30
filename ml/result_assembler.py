"""
ml/result_assembler.py — Merges TaskResults into a single final output dict.
"""

import datetime
import json
import os
from ml.task_types import TaskResult, TASKS

HISTORY_PATH = "logs/history.jsonl"

# Severity ordering for status escalation
_SEVERITY_RANK = {"OK": 0, "UNKNOWN": 1, "LOW": 2, "MEDIUM": 3,
                  "WARNING": 4, "HIGH": 5, "CRITICAL": 6}


class ResultAssembler:
    """Combines all TaskResults into a structured final output."""

    def assemble(self, results: dict) -> dict:
        """
        Args:
            results: dict mapping task_type (str) -> TaskResult

        Returns:
            final_output dict
        """
        clean_res   = results.get("clean")
        anomaly_res = results.get("anomaly")
        trend_res   = results.get("trend")
        history_res = results.get("history")
        action_res  = results.get("action")

        # ----------------------------------------------------------
        # Extract sub-fields safely
        # ----------------------------------------------------------
        anomaly_data   = anomaly_res.result  if anomaly_res  and anomaly_res.success  else {}
        trend_data     = trend_res.result    if trend_res    and trend_res.success    else {}
        history_data   = history_res.result  if history_res  and history_res.success  else {}
        action_data    = action_res.result   if action_res   and action_res.success   else {}
        clean_data     = clean_res.result    if clean_res    and clean_res.success    else {}

        anomalies_list = anomaly_data.get("anomalies", [])
        anomaly_status = anomaly_data.get("status", "UNKNOWN")
        action_urgency = action_data.get("urgency", "UNKNOWN")

        # Overall status = highest of anomaly status and action urgency
        status = self._highest_status(anomaly_status, action_urgency)

        # Tally successes / failures
        failed_tasks = [
            t for t in TASKS
            if t in results and not results[t].success
        ]
        nodes_contributed = sum(
            1 for t in TASKS
            if t in results and results[t].success
        )

        final_output = {
            "status":              status,
            "clean_data":          clean_data,
            "anomalies_found":     anomalies_list,
            "trends":              trend_data.get("trends", {}),
            "historical_match":    history_data,
            "recommended_action":  action_data.get("action", ""),
            "action_urgency":      action_urgency,
            "nodes_contributed":   nodes_contributed,
            "failed_tasks":        failed_tasks,
            "assembled_at":        datetime.datetime.utcnow().isoformat() + "Z",
        }

        # ----------------------------------------------------------
        # Print summary
        # ----------------------------------------------------------
        total = len(TASKS)
        print(f"[ASSEMBLER] Status:              {status}")
        print(f"[ASSEMBLER] Anomalies:           {len(anomalies_list)}")
        print(f"[ASSEMBLER] Action:              {action_data.get('action', 'N/A')} "
              f"[{action_urgency}]")
        print(f"[ASSEMBLER] Nodes contributed:   {nodes_contributed}/{total}")
        if failed_tasks:
            print(f"[ASSEMBLER] Failed tasks:        {', '.join(failed_tasks)}")

        # ----------------------------------------------------------
        # Append to history.jsonl
        # ----------------------------------------------------------
        self._append_history(clean_data, status, action_data.get("action", ""))

        return final_output

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _highest_status(*statuses: str) -> str:
        """Return the most severe status string from the given set."""
        return max(statuses, key=lambda s: _SEVERITY_RANK.get(s, 0))

    @staticmethod
    def _append_history(sensor_data: dict, outcome: str, action_taken: str) -> None:
        """Append one JSON line to logs/history.jsonl."""
        os.makedirs("logs", exist_ok=True)
        entry = {
            "timestamp":    datetime.datetime.utcnow().isoformat() + "Z",
            "sensor_data":  sensor_data,
            "outcome":      outcome,
            "action_taken": action_taken,
        }
        try:
            with open(HISTORY_PATH, "a") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            pass   # history write failure must not crash the pipeline
