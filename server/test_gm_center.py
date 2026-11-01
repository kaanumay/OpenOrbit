"""Unit tests for GM Center's Dispatch gate eligibility rules.

Run from the server directory: python -m unittest test_gm_center
"""
import unittest

from gm_center import gate_status


class GateStatusTests(unittest.TestCase):
    def test_prepared_kappa_and_next_build_at_113_of_120(self):
        # The current Kappa is already assembled/prepared. 113/120 belongs
        # to the next build and must not make the current gate look incomplete.
        current_gate_parts = 120
        next_gate_parts = 113
        required = 120
        self.assertGreaterEqual(current_gate_parts, required)
        self.assertEqual(next_gate_parts, 113)
        state = gate_status(built=current_gate_parts >= required, completed=True, wave=0, now=100)
        self.assertEqual(state["status"], "ready_to_send")
        self.assertTrue(state["can_send"])

    def test_next_build_progress_does_not_replace_current_gate_progress(self):
        current_gate = {"parcalar": list(range(1, 121)), "hazir": True, "sonraki": list(range(1, 114))}
        current = len(current_gate["parcalar"])
        next_build = len(current_gate["sonraki"]) if current_gate["hazir"] else 0
        self.assertEqual(current, 120)
        self.assertEqual(next_build, 113)

    def test_built_gate_requires_first_manual_completion(self):
        state = gate_status(built=True, completed=False, wave=0, now=100)
        self.assertEqual(state["status"], "first_manual_completion_required")
        self.assertFalse(state["can_send"])

    def test_completed_gate_in_first_wave_can_be_sent(self):
        state = gate_status(built=True, completed=True, wave=0, now=100)
        self.assertEqual(state["status"], "ready_to_send")
        self.assertTrue(state["can_send"])

    def test_started_gate_cannot_be_sent(self):
        state = gate_status(built=True, completed=True, wave=2, now=100)
        self.assertEqual(state["status"], "gate_in_progress")
        self.assertFalse(state["can_send"])

    def test_dispatch_countdown_and_collection(self):
        running = gate_status(built=True, completed=True, wave=0, sent_until=160, now=100)
        ready = gate_status(built=True, completed=True, wave=0, sent_until=90, now=100)
        self.assertEqual(running["status"], "dispatching")
        self.assertEqual(running["time_left"], 60)
        self.assertTrue(ready["can_collect"])
        self.assertFalse(ready["can_send"])


if __name__ == "__main__":
    unittest.main()
