"""Fail-closed opt-in auto-resume regression checks (mocked HA runtime).

The fake HA updates below are NOT Zigbee delivery confirmations. Hardware and
long-running reconnect tests are still required before an unattended release.
"""
from __future__ import annotations

import asyncio
import json
import time
import types
import unittest

from test_controller_runtime import FakeHass, controller, event, state


class AutoResumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hass = FakeHass()
        self.data = {
            "ahc_automation": "automation.ahc",
            "auto_resume": True,
            "schedule_entity": "schedule.room",
            "room_climate": "climate.room",
            "room_operating_mode": "select.room",
            "room_temperature": "sensor.temp",
            "room_mqtt_topic": "zigbee2mqtt/Room",
            "radiator_climates": ["climate.r1", "climate.r2"],
            "radiator_modes": ["select.r1", "select.r2"],
        }
        self.control = controller.BoschRoomController(self.hass, self.data)
        self.control.room_mode = "schedule"

    def ahc(self, *, automation="automation.ahc", target=19):
        self.control._ahc_event(event(
            automation=automation,
            hvac_mode="heat",
            target_temperature=target,
            state=True,
        ))

    def fresh_mqtt(self, *, retain=False):
        self.control._room_message(types.SimpleNamespace(
            payload=json.dumps({
                "occupied_heating_setpoint": 22,
                "setpoint_change_source": "externally",
            }).encode("utf-8"),
            retain=retain,
        ))

    def fresh_ha(self):
        for entity in ("sensor.temp", "climate.r1", "climate.r2"):
            previous = self.hass.states[entity]
            self.control._source_updated(event(
                old_state=previous,
                new_state=previous,
            ))

    async def drain(self):
        if self.control._reconcile_task is not None:
            await self.control._reconcile_task

    def test_default_is_still_manual_only(self):
        data = {k: v for k, v in self.data.items() if k != "auto_resume"}
        ctrl = controller.BoschRoomController(self.hass, data)
        self.assertFalse(ctrl.auto_resume_pending)
        self.assertFalse(ctrl.enabled)
        ctrl._attempt_auto_resume()
        self.assertFalse(ctrl.enabled)

    async def test_waits_for_fresh_matching_ahc_and_all_three_devices(self):
        self.assertFalse(self.control.enabled)
        self.ahc(automation="automation.another")
        self.fresh_mqtt()
        self.fresh_ha()
        self.control._attempt_auto_resume()
        self.assertFalse(self.control.enabled)
        self.assertIn("Waiting for a new matching AHC event", self.control.auto_resume_blockers)

        self.ahc()
        self.assertFalse(self.control.enabled)
        self.assertIsNotNone(self.control._auto_resume_ready_since)
        self.control._auto_resume_ready_since = (
            time.monotonic() - controller.AUTO_RESUME_STABLE_SECONDS - 1
        )
        self.control._attempt_auto_resume()
        await self.drain()
        self.assertTrue(self.control.enabled)
        self.assertTrue(self.control.auto_resumed)
        self.assertFalse(self.control.auto_resume_pending)
        targets = [
            data["temperature"]
            for domain, action, data in self.hass.services.calls
            if (domain, action) == ("climate", "set_temperature")
        ]
        self.assertEqual(targets, [19, 19])

    def test_retained_mqtt_not_accepted_as_fresh_room_message(self):
        self.ahc()
        self.fresh_ha()
        self.fresh_mqtt(retain=True)
        self.control._attempt_auto_resume()
        self.assertFalse(self.control.enabled)
        self.assertIn(
            "Waiting for non-retained Bosch room MQTT state",
            self.control.auto_resume_blockers,
        )

    def test_stale_radiator_report_blocks_auto_resume(self):
        self.ahc()
        self.fresh_mqtt()
        self.fresh_ha()
        self.control._source_updates_after_start["climate.r2"] = (
            time.monotonic() - controller.AUTO_RESUME_TELEMETRY_MAX_AGE_SECONDS - 1
        )
        self.control._attempt_auto_resume()
        self.assertFalse(self.control.enabled)
        self.assertIsNone(self.control._auto_resume_ready_since)

    def test_unavailable_radiator_blocks_auto_resume(self):
        self.ahc()
        self.fresh_mqtt()
        self.fresh_ha()
        self.hass.states["climate.r2"] = state("climate.r2", "unavailable")
        self.control._attempt_auto_resume()
        self.assertFalse(self.control.enabled)
        self.assertIn(
            "Waiting for valid AHC and Bosch entities",
            self.control.auto_resume_blockers,
        )

    def test_explicit_off_cancels_auto_resume_for_this_runtime(self):
        self.ahc()
        self.fresh_mqtt()
        self.fresh_ha()
        self.control.async_set_control_enabled(False)
        self.control._auto_resume_ready_since = (
            time.monotonic() - controller.AUTO_RESUME_STABLE_SECONDS - 1
        )
        self.control._attempt_auto_resume()
        self.assertFalse(self.control.enabled)
        self.assertFalse(self.control.auto_resume_pending)


if __name__ == "__main__":
    unittest.main()
