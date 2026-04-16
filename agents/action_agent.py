"""
agents/action_agent.py — Reads decision output and executes real actions.
"""

import json
import os
from datetime import datetime
from agents.base_agent import BaseAgent

LOGS_DIR = "logs"
ACTIONS_LOG = "logs/actions.jsonl"
WORKORDERS_DIR = "logs/workorders"


class ActionAgent(BaseAgent):

    def __init__(self, agent_id="action-agent"):
        super().__init__(agent_id=agent_id, role="action")
        os.makedirs(LOGS_DIR, exist_ok=True)
        os.makedirs(WORKORDERS_DIR, exist_ok=True)

    def execute(self, decision: dict, sensor_summary: dict) -> dict:
        urgency = decision.get("action_urgency", "LOW")
        action  = decision.get("recommended_action", "")
        status  = decision.get("status", "OK")

        actions_taken = []

        # Always log to actions.jsonl
        self._log_action(decision, sensor_summary)
        actions_taken.append("logged to actions.jsonl")

        # Always create work order
        wo_path = self._create_work_order(decision, sensor_summary)
        actions_taken.append(f"work order: {wo_path}")

        # If WARNING or higher: print alert
        if status in ("WARNING", "CRITICAL") or urgency in ("HIGH", "CRITICAL"):
            self._send_alert(decision, sensor_summary)
            actions_taken.append("alert printed")

        # If CRITICAL: write emergency file
        if urgency == "CRITICAL" or status == "CRITICAL":
            self._emergency_escalation(decision, sensor_summary)
            actions_taken.append("emergency escalation")

        result = {
            "actions_taken":   actions_taken,
            "urgency":         urgency,
            "status":          status,
            "work_order_path": wo_path,
            "timestamp":       datetime.utcnow().isoformat(),
        }

        print(f"[ACTION] Executed {len(actions_taken)} actions for {urgency} event")
        return result

    def _log_action(self, decision: dict, summary: dict) -> dict:
        entry = {
            "timestamp":   datetime.utcnow().isoformat(),
            "status":      decision.get("status", "OK"),
            "urgency":     decision.get("action_urgency", "LOW"),
            "action":      decision.get("recommended_action", ""),
            "anomalies":   decision.get("anomalies_found", []),
            "sensor_data": summary,
        }
        with open(ACTIONS_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    def _create_work_order(self, decision: dict, summary: dict) -> str:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{WORKORDERS_DIR}/WO_{ts}.json"
        wo = {
            "work_order_id":    f"WO-{ts}",
            "created_at":       datetime.utcnow().isoformat(),
            "priority":         decision.get("action_urgency", "LOW"),
            "status":           "OPEN",
            "site_status":      decision.get("status", "OK"),
            "description":      decision.get("recommended_action", ""),
            "anomalies":        decision.get("anomalies_found", []),
            "trends":           decision.get("trends", {}),
            "sensor_snapshot":  summary,
            "assigned_to":      "site_supervisor",
            "actions_required": [
                decision.get("recommended_action", "Review site conditions")
            ],
        }
        with open(filename, "w") as f:
            json.dump(wo, f, indent=2)
        print(f"[ACTION] Work order created: {filename}")
        return filename

    def _send_alert(self, decision: dict, summary: dict):
        urgency = decision.get("action_urgency", "LOW")
        status  = decision.get("status", "OK")
        action  = decision.get("recommended_action", "")

        print()
        print("=" * 60)
        print(f"  !! ALERT — {urgency} PRIORITY !!")
        print("=" * 60)
        print(f"  Site Status:  {status}")
        print(f"  Action:       {action}")
        anomalies = decision.get("anomalies_found", [])
        if anomalies:
            print(f"  Anomalies:    {len(anomalies)} detected")
            for a in anomalies:
                print(f"    - {a.get('field', '?')}: {a.get('severity', '?')}")
        print("=" * 60)
        print()

    def _emergency_escalation(self, decision: dict, summary: dict):
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{LOGS_DIR}/EMERGENCY_{ts}.json"
        emergency = {
            "EMERGENCY":   True,
            "timestamp":   datetime.utcnow().isoformat(),
            "decision":    decision,
            "sensor_data": summary,
            "message":     "CRITICAL EVENT - IMMEDIATE ACTION REQUIRED",
        }
        with open(filename, "w") as f:
            json.dump(emergency, f, indent=2)
        print(f"[ACTION] EMERGENCY file written: {filename}")
