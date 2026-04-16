"""
core/action_planner.py — Scores urgency from ML decision output and
routes to the appropriate action category.
"""


def plan_actions(ml_result: dict, decision_text: str) -> dict:
    """
    Decide what actions to take based on the assembled ML result.

    Args:
        ml_result:     Final output dict from ResultAssembler.
        decision_text: Human-readable assessment string from make_decision.

    Returns:
        Action plan dict.
    """
    status        = ml_result.get("status", "OK")
    urgency       = ml_result.get("action_urgency", "LOW")
    anomaly_count = len(ml_result.get("anomalies_found", []))

    plan = {
        "urgency":          urgency,
        "status":           status,
        "anomaly_count":    anomaly_count,
        "actions":          [],
        "escalate":         False,
        "create_workorder": True,
    }

    if status == "CRITICAL" or urgency == "CRITICAL":
        plan["actions"].append("emergency_escalation")
        plan["actions"].append("alert_supervisor")
        plan["escalate"] = True

    elif status == "WARNING" or urgency in ("HIGH", "MEDIUM"):
        plan["actions"].append("alert_supervisor")
        plan["actions"].append("schedule_inspection")

    else:
        plan["actions"].append("log_and_monitor")

    return plan
