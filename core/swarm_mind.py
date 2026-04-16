"""
core/swarm_mind.py — Master autonomous controller.
Combines AutoTrigger + PipelineTrigger into one self-organising system.
"""

import time
from core.auto_trigger import AutoTrigger
from core.pipeline_trigger import PipelineTrigger


class SwarmMind:

    def __init__(self, get_peers_fn, bus):
        self.get_peers  = get_peers_fn
        self.bus        = bus
        self.auto       = AutoTrigger(
            get_peers_fn=get_peers_fn,
            run_pipeline_fn=None,
        )
        self.pipeline   = PipelineTrigger(
            get_peers_fn=get_peers_fn,
            get_bus_fn=lambda: bus,
        )
        self.running    = False
        self.start_time = None

    def start(self):
        self.running    = True
        self.start_time = time.time()
        self.auto.start()
        self.pipeline.start()
        print("[MIND] SwarmMind activated — fully autonomous mode")
        print("[MIND] System will self-organize as devices join")

    def stop(self):
        self.running = False
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
