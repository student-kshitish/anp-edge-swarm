"""
core/self_improvement.py — Swarm self-improvement engine.

Tracks every decision the swarm makes and its outcome.
Periodically re-evaluates history and adjusts learned parameters
(anomaly thresholds, confidence floors, per-node trust scores)
so the swarm gets measurably smarter over time.
"""

import json
import math
import threading
import time
from collections import defaultdict


class SelfImprovementEngine:

    def __init__(self):
        self.decision_history = []
        self.outcome_tracking = {}   # decision_id -> outcome
        self.learned_params   = {
            "anomaly_threshold":  2.5,
            "confidence_min":     0.6,
            "action_cooldown":    30,
            "critical_threshold": 3.5,
            "trust_score":        {},
        }
        self.performance_log = []
        self.running         = False
        self._lock           = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self.running = True
        self._load_historical_learning()
        threading.Thread(
            target=self._learning_loop,
            daemon=True,
            name="self-improvement",
        ).start()
        print("[LEARN] Self-improvement engine started")

    def stop(self):
        self.running = False

    # ------------------------------------------------------------------
    # Decision recording
    # ------------------------------------------------------------------

    def record_decision(
        self,
        decision_id:   str,
        decision_type: str,
        inputs:        dict,
        action_taken:  dict,
    ) -> None:
        entry = {
            "decision_id": decision_id,
            "timestamp":   time.time(),
            "type":        decision_type,
            "inputs":      inputs,
            "action":      action_taken,
            "outcome":     None,
            "evaluated":   False,
        }
        with self._lock:
            self.decision_history.append(entry)
            if len(self.decision_history) > 1000:
                self.decision_history = self.decision_history[-1000:]

    def record_outcome(
        self,
        decision_id: str,
        was_correct: bool,
        feedback:    dict = None,
    ) -> None:
        with self._lock:
            for entry in self.decision_history:
                if entry["decision_id"] == decision_id:
                    entry["outcome"] = {
                        "correct":      was_correct,
                        "feedback":     feedback or {},
                        "evaluated_at": time.time(),
                    }
                    entry["evaluated"] = True
                    print(
                        f"[LEARN] Decision {decision_id[:8]} outcome: "
                        f"{'CORRECT' if was_correct else 'WRONG'}"
                    )
                    break

    # ------------------------------------------------------------------
    # Prediction quality
    # ------------------------------------------------------------------

    def evaluate_prediction_quality(
        self,
        prediction:    dict,
        actual_result: dict = None,
    ) -> dict:
        quality = {"accuracy": 0.0, "confidence": 0.0, "flags": []}

        if prediction.get("anomalies_found"):
            if actual_result and actual_result.get("was_real"):
                quality["accuracy"] = 1.0
            else:
                quality["flags"].append("false_positive")
                quality["accuracy"] = 0.0

        for field, t in prediction.get("trends", {}).items():
            if isinstance(t, dict):
                predicted = t.get("predicted_next", 0)
                actual    = (actual_result or {}).get(f"actual_{field}", 0)
                if actual and predicted:
                    error = abs(predicted - actual) / (abs(actual) + 0.001)
                    quality["confidence"] = max(0.0, 1.0 - error)

        return quality

    # ------------------------------------------------------------------
    # Core learning
    # ------------------------------------------------------------------

    def learn_from_history(self) -> dict:
        with self._lock:
            evaluated = [e for e in self.decision_history if e["evaluated"]]

        if len(evaluated) < 5:
            return {"insufficient_data": True, "count": len(evaluated)}

        correct  = sum(1 for e in evaluated if e["outcome"]["correct"])
        accuracy = correct / len(evaluated)

        anomaly_decisions = [e for e in evaluated if e["type"] == "anomaly"]
        false_positives   = [e for e in anomaly_decisions
                             if not e["outcome"]["correct"]]
        fp_rate = len(false_positives) / max(1, len(anomaly_decisions))

        adjustments = []

        if fp_rate > 0.3:
            old = self.learned_params["anomaly_threshold"]
            self.learned_params["anomaly_threshold"] = min(4.0, old + 0.2)
            adjustments.append(
                f"anomaly_threshold: {old} → "
                f"{self.learned_params['anomaly_threshold']:.1f} "
                f"(too many false positives)"
            )
        elif fp_rate < 0.1 and accuracy > 0.85:
            old = self.learned_params["anomaly_threshold"]
            self.learned_params["anomaly_threshold"] = max(1.5, old - 0.1)
            adjustments.append(
                f"anomaly_threshold: {old} → "
                f"{self.learned_params['anomaly_threshold']:.1f} "
                f"(system accurate, lowering)"
            )

        # Update per-node trust scores from contributing_nodes field
        node_performance: dict = defaultdict(lambda: {"correct": 0, "total": 0})
        for e in evaluated:
            for node in e.get("inputs", {}).get("contributing_nodes", []):
                node_performance[node]["total"] += 1
                if e["outcome"]["correct"]:
                    node_performance[node]["correct"] += 1

        for node, perf in node_performance.items():
            if perf["total"] >= 3:
                trust = perf["correct"] / perf["total"]
                self.learned_params["trust_score"][node] = round(trust, 2)

        result = {
            "total_decisions":     len(evaluated),
            "accuracy":            round(accuracy, 3),
            "false_positive_rate": round(fp_rate, 3),
            "adjustments":         adjustments,
            "learned_params":      self.learned_params,
            "trusted_nodes": {
                n: s for n, s in self.learned_params["trust_score"].items()
                if s > 0.8
            },
        }

        self.performance_log.append({"timestamp": time.time(), "stats": result})

        if adjustments:
            print(f"[LEARN] Applied {len(adjustments)} adjustments:")
            for a in adjustments:
                print(f"        {a}")

        self._save_learned_params()
        return result

    # ------------------------------------------------------------------
    # Parameter accessors
    # ------------------------------------------------------------------

    def get_adjusted_threshold(self, param: str, default: float) -> float:
        return self.learned_params.get(param, default)

    def should_trust_node(self, node_id: str, min_trust: float = 0.7) -> bool:
        trust = self.learned_params["trust_score"].get(node_id, 1.0)
        return trust >= min_trust

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _learning_loop(self):
        while self.running:
            time.sleep(300)
            try:
                self.learn_from_history()
            except Exception as e:
                print(f"[LEARN] Loop error: {e}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_historical_learning(self):
        try:
            with open(".learned_params.json") as f:
                saved = json.load(f)
            self.learned_params.update(saved)
            print("[LEARN] Loaded learned params from disk")
        except Exception:
            pass

    def _save_learned_params(self):
        try:
            with open(".learned_params.json", "w") as f:
                json.dump(self.learned_params, f, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        with self._lock:
            return {
                "total_decisions":     len(self.decision_history),
                "evaluated_decisions": sum(
                    1 for e in self.decision_history if e["evaluated"]
                ),
                "learned_params":      self.learned_params,
                "performance_logs":    len(self.performance_log),
            }
