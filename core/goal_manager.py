"""
core/goal_manager.py — Autonomous goal and operational-mode manager.

Evaluates recent decision history every 60 seconds and escalates
or de-escalates the swarm's operational mode automatically.
Higher modes increase sensor frequency and ML depth; the swarm
backs off again once the situation clears.
"""

import threading
import time


class GoalManager:

    MODES = {
        "idle":         {"priority": 0, "sensors": 1,  "ml_depth": "basic"},
        "monitoring":   {"priority": 1, "sensors": 3,  "ml_depth": "normal"},
        "alert":        {"priority": 2, "sensors": 5,  "ml_depth": "deep"},
        "surveillance": {"priority": 3, "sensors": 10, "ml_depth": "deep"},
        "emergency":    {"priority": 4, "sensors": 10, "ml_depth": "maximum"},
    }

    _INTERVALS = {
        "idle":         120,
        "monitoring":   30,
        "alert":        15,
        "surveillance": 10,
        "emergency":    5,
    }

    def __init__(self, improvement_engine):
        self.engine       = improvement_engine
        self.current_mode = "monitoring"
        self.mode_history = []
        self.running      = False
        self.auto_adjust  = True
        self._lock        = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self.running = True
        threading.Thread(
            target=self._adjust_loop,
            daemon=True,
            name="goal-manager",
        ).start()
        print(f"[GOAL] Goal manager started — mode: {self.current_mode}")

    def stop(self):
        self.running = False

    # ------------------------------------------------------------------
    # Mode control
    # ------------------------------------------------------------------

    def set_mode(self, mode: str, reason: str = "manual") -> bool:
        if mode not in self.MODES:
            return False

        old = self.current_mode
        with self._lock:
            self.current_mode = mode
            self.mode_history.append({
                "timestamp": time.time(),
                "from":      old,
                "to":        mode,
                "reason":    reason,
            })

        print(f"[GOAL] Mode changed: {old} → {mode} ({reason})")

        try:
            from bus.event_bus import get_event_bus
            get_event_bus().publish(
                "goal.mode_changed",
                {
                    "from":   old,
                    "to":     mode,
                    "reason": reason,
                    "config": self.MODES[mode],
                },
                priority="HIGH",
            )
        except Exception:
            pass

        return True

    # ------------------------------------------------------------------
    # Auto-adjustment loop
    # ------------------------------------------------------------------

    def _adjust_loop(self):
        while self.running:
            time.sleep(60)
            if self.auto_adjust:
                try:
                    self._evaluate_and_adjust()
                except Exception as e:
                    print(f"[GOAL] Adjust error: {e}")

    def _evaluate_and_adjust(self):
        history = self.engine.decision_history[-20:]
        if not history:
            return

        recent_anomalies = sum(
            1 for h in history
            if h.get("inputs", {}).get("anomaly_count", 0) > 0
        )
        critical_count = sum(
            1 for h in history
            if h.get("inputs", {}).get("urgency") == "CRITICAL"
        )
        high_count = sum(
            1 for h in history
            if h.get("inputs", {}).get("urgency") == "HIGH"
        )

        current_priority = self.MODES[self.current_mode]["priority"]

        # Escalate on sustained issues
        if critical_count >= 2:
            if current_priority < 4:
                self.set_mode(
                    "emergency",
                    f"{critical_count} critical events in last 20",
                )
        elif high_count >= 5:
            if current_priority < 3:
                self.set_mode(
                    "surveillance",
                    f"{high_count} high-priority events",
                )
        elif recent_anomalies >= 8:
            if current_priority < 2:
                self.set_mode(
                    "alert",
                    f"{recent_anomalies} anomalies detected",
                )

        # De-escalate when all-clear
        elif recent_anomalies < 2 and critical_count == 0 and high_count < 2:
            if self.current_mode == "emergency":
                self.set_mode("surveillance", "emergency cleared")
            elif self.current_mode == "surveillance":
                self.set_mode("alert", "surveillance period clean")
            elif self.current_mode == "alert":
                self.set_mode("monitoring", "alert cleared, returning to monitoring")

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_current_config(self) -> dict:
        return {
            "mode":   self.current_mode,
            "config": self.MODES[self.current_mode],
        }

    def get_recommended_interval(self) -> int:
        return self._INTERVALS.get(self.current_mode, 30)

    def get_status(self) -> dict:
        with self._lock:
            return {
                "current_mode":   self.current_mode,
                "mode_config":    self.MODES[self.current_mode],
                "mode_history":   len(self.mode_history),
                "auto_adjust":    self.auto_adjust,
                "recent_changes": self.mode_history[-5:],
            }
