"""Behavioral unit tests for the pure radiator arbitration rules."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


POLICY = Path(__file__).resolve().parents[1] / "custom_components/ahc_bosch_companion/policy.py"
spec = importlib.util.spec_from_file_location("companion_policy_test", POLICY)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)


class PolicyTests(unittest.TestCase):
    def check(self, *, target=21, ahc_mode="heat", room="schedule",
              override="schedule", user=23, protective=False):
        return policy.decide(
            target, ahc_mode, room, override, user, ahc_protection=protective
        )

    def test_automatic_schedule(self):
        self.assertEqual(self.check(), policy.Desired("manual", 21))

    def test_manual_override(self):
        self.assertEqual(
            self.check(room="manual", override="manual"),
            policy.Desired("manual", 23),
        )

    def test_temporary_override(self):
        self.assertEqual(
            self.check(room="schedule", override="temporary"),
            policy.Desired("manual", 23),
        )

    def test_pause_room(self):
        self.assertEqual(
            self.check(room="pause", override="pause"),
            policy.Desired("pause"),
        )

    def test_ahc_off_maps_to_manufacturer_pause_even_with_zero_target(self):
        self.assertEqual(
            self.check(target=0, ahc_mode="off"),
            policy.Desired("pause"),
        )

    def test_frost_or_window_ahc_wins_over_local_manual(self):
        self.assertEqual(
            self.check(room="manual", override="manual", protective=True),
            policy.Desired("manual", 21),
        )

    def test_frost_ahc_wins_over_local_pause(self):
        self.assertEqual(
            self.check(room="pause", override="pause", protective=True),
            policy.Desired("manual", 21),
        )

    def test_bad_ahc_target_never_operates_valves(self):
        for target in (None, "unknown", "unavailable", 0, -1, 31,
                       float("nan"), float("inf")):
            with self.subTest(value=target):
                self.assertIsNone(self.check(target=target))

    def test_invalid_override_falls_back_to_ahc(self):
        self.assertEqual(
            self.check(room="manual", override="manual", user="unknown"),
            policy.Desired("manual", 21),
        )

    def test_source_must_be_manual_and_setpoint_different(self):
        self.assertTrue(policy.is_physical_schedule_change("manual", 20, 21))
        self.assertFalse(policy.is_physical_schedule_change("manual", 20, 20))
        self.assertFalse(policy.is_physical_schedule_change("externally", 20, 21))
        self.assertFalse(policy.is_physical_schedule_change("manual", None, 21))

    def test_temperature_validation(self):
        self.assertIsNone(policy.valid_temp(True))
        self.assertIsNone(policy.valid_temp(float("inf")))
        self.assertIsNone(policy.valid_temp("invalid"))
        self.assertEqual(policy.valid_temp("22.54"), 22.5)


if __name__ == "__main__":
    unittest.main()
