"""
core/reflective_decision.py — Reflective decision-making layer.

Before acting, the system looks back at similar past situations,
votes on the strategy that historically worked best, and expresses
a calibrated confidence score. Low-confidence decisions fall back
to "investigate_further" rather than acting blindly.
"""

import time
from collections import defaultdict


class ReflectiveDecisionMaker:

    def __init__(self, improvement_engine):
        self.engine     = improvement_engine
        self.strategies = {
            "alert_supervisor":     {"success": 0, "total": 0},
            "auto_escalate":        {"success": 0, "total": 0},
            "create_workorder":     {"success": 0, "total": 0},
            "schedule_maintenance": {"success": 0, "total": 0},
            "log_only":             {"success": 0, "total": 0},
            "investigate_further":  {"success": 0, "total": 0},
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reflect_and_decide(
        self,
        current_input:  dict,
        historical_data: list = None,
    ) -> dict:
        similar_cases  = self._find_similar_cases(
            current_input, historical_data or [])
        best_strategy  = self._select_best_strategy(
            current_input, similar_cases)
        confidence     = self._calculate_confidence(
            similar_cases, best_strategy)

        threshold      = self.engine.get_adjusted_threshold(
            "anomaly_threshold", 2.5)
        min_confidence = self.engine.get_adjusted_threshold(
            "confidence_min", 0.6)

        decision = {
            "strategy":      best_strategy,
            "confidence":    confidence,
            "similar_cases": len(similar_cases),
            "reasoning":     self._build_reasoning(
                current_input, similar_cases, best_strategy),
            "thresholds_used": {
                "anomaly":    threshold,
                "confidence": min_confidence,
            },
            "timestamp": time.time(),
        }

        if confidence < min_confidence:
            decision["fallback_used"]       = True
            decision["original_strategy"]   = best_strategy
            decision["strategy"]            = "investigate_further"
            decision["reasoning"]          += " [confidence too low — investigating]"

        print(
            f"[REFLECT] Strategy: {decision['strategy']} "
            f"confidence={confidence:.2f} "
            f"based on {len(similar_cases)} similar cases"
        )
        return decision

    # ------------------------------------------------------------------
    # Similarity search
    # ------------------------------------------------------------------

    def _find_similar_cases(self, current: dict, history: list) -> list:
        if not history:
            return []

        current_status  = current.get("status", "OK")
        current_anomaly = current.get("anomaly_count", 0)
        current_urgency = current.get("urgency", "LOW")

        similar = []
        for past in history:
            past_inputs  = past.get("inputs", past)
            past_status  = past_inputs.get("status", "OK")
            past_anomaly = past_inputs.get("anomaly_count", 0)
            past_urgency = past_inputs.get("urgency", "LOW")

            similarity = 0.0
            if past_status  == current_status:                  similarity += 0.4
            if past_urgency == current_urgency:                 similarity += 0.3
            if abs(past_anomaly - current_anomaly) <= 1:        similarity += 0.3

            if similarity >= 0.5:
                similar.append({"case": past_inputs, "similarity": round(similarity, 2)})

        similar.sort(key=lambda x: x["similarity"], reverse=True)
        return similar[:10]

    # ------------------------------------------------------------------
    # Strategy selection
    # ------------------------------------------------------------------

    def _select_best_strategy(self, current: dict, similar_cases: list) -> str:
        urgency = current.get("urgency", "LOW")

        if urgency == "CRITICAL":
            return "auto_escalate"

        if not similar_cases:
            if urgency == "HIGH":
                return "alert_supervisor"
            elif urgency == "MEDIUM":
                return "create_workorder"
            else:
                return "log_only"

        strategy_votes: dict = defaultdict(float)
        for case in similar_cases:
            past_strategy = case["case"].get("strategy", "log_only")
            strategy_votes[past_strategy] += case["similarity"]

        return max(strategy_votes, key=strategy_votes.get)

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    def _calculate_confidence(
        self, similar_cases: list, chosen_strategy: str
    ) -> float:
        if not similar_cases:
            return 0.5

        top_similarity = similar_cases[0]["similarity"]
        case_count     = min(1.0, len(similar_cases) / 5)
        strategy_count = sum(
            1 for c in similar_cases
            if c["case"].get("strategy") == chosen_strategy
        )
        agreement  = strategy_count / len(similar_cases)
        confidence = (top_similarity * 0.4
                      + case_count     * 0.3
                      + agreement      * 0.3)
        return round(confidence, 3)

    # ------------------------------------------------------------------
    # Reasoning text
    # ------------------------------------------------------------------

    def _build_reasoning(
        self, current: dict, similar_cases: list, strategy: str
    ) -> str:
        if not similar_cases:
            return (
                f"No similar past cases. "
                f"Using default for {current.get('urgency', 'LOW')} urgency."
            )
        top = similar_cases[0]
        return (
            f"Found {len(similar_cases)} similar cases. "
            f"Top match: {top['similarity'] * 100:.0f}% similar. "
            f"Most common past strategy: {strategy}."
        )

    # ------------------------------------------------------------------
    # Outcome feedback
    # ------------------------------------------------------------------

    def learn_from_strategy_outcome(self, strategy: str, success: bool) -> None:
        if strategy in self.strategies:
            self.strategies[strategy]["total"] += 1
            if success:
                self.strategies[strategy]["success"] += 1

    def get_strategy_stats(self) -> dict:
        stats = {}
        for s, data in self.strategies.items():
            total        = data["total"]
            success_rate = data["success"] / total if total > 0 else 0.0
            stats[s] = {
                "total":        total,
                "success":      data["success"],
                "success_rate": round(success_rate, 3),
            }
        return stats
