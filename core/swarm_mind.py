"""
core/swarm_mind.py — Master autonomous controller.
Combines AutoTrigger + PipelineTrigger into one self-organising system.
Adds self-improvement, reflective decision-making, and goal management
as the final intelligence layer.
"""

import time
from core.auto_trigger import AutoTrigger
from core.pipeline_trigger import PipelineTrigger
from core.self_improvement import SelfImprovementEngine
from core.reflective_decision import ReflectiveDecisionMaker
from core.goal_manager import GoalManager

# Module-level reference so action_agent can reach the live mind instance
# without importing SwarmMind (avoids circular imports).
_mind: "SwarmMind | None" = None


class SwarmMind:

    def __init__(self, get_peers_fn, bus):
        global _mind

        self.get_peers = get_peers_fn
        self.bus       = bus

        # Intelligence layer — instantiated before pipeline so pipeline
        # can reference self.improvement / self.goals at startup.
        self.improvement = SelfImprovementEngine()
        self.reflection  = ReflectiveDecisionMaker(self.improvement)
        self.goals       = GoalManager(self.improvement)

        self.auto = AutoTrigger(
            get_peers_fn=get_peers_fn,
            run_pipeline_fn=None,
        )
        self.pipeline = PipelineTrigger(
            get_peers_fn=get_peers_fn,
            get_bus_fn=lambda: bus,
        )
        # Give pipeline a back-reference so it can call
        # self.mind.improvement and self.mind.goals.
        self.pipeline.mind = self

        self.running    = False
        self.start_time = None

        _mind = self

    def start(self):
        self.running    = True
        self.start_time = time.time()

        self.improvement.start()
        self.goals.start()
        self.auto.start()
        self.pipeline.start()

        print("[MIND] SwarmMind activated — fully autonomous mode")
        print("[MIND] Self-improvement and goal management online")
        print("[MIND] System will self-organize as devices join")

    def stop(self):
        self.running = False
        self.improvement.stop()
        self.goals.stop()
        self.auto.stop()
        self.pipeline.stop()
        print("[MIND] SwarmMind deactivated")

    def status(self) -> dict:
        uptime = int(time.time() - self.start_time) if self.start_time else 0
        peers  = self.get_peers()
        return {
            "uptime_seconds":  uptime,
            "known_devices":   len(peers),
            "pipeline_cycles": self.pipeline.cycle_count,
            "autonomous":      True,
        }

    def get_intelligence_status(self) -> dict:
        return {
            "learning":   self.improvement.get_status(),
            "goals":      self.goals.get_status(),
            "strategies": self.reflection.get_strategy_stats(),
        }
