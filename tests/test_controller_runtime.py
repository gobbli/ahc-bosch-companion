"""AHC schedule and radiator retry regressions without a HA runtime."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import time
import types
import unittest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/ahc_bosch_companion"


def _module(name: str, package: bool = False):
    module = types.ModuleType(name)
    if package:
        module.__path__ = []
    sys.modules[name] = module
    return module


# Only the Home Assistant interfaces accessed by these controller tests are stubbed.
ha = _module("homeassistant", True)
ha.components = _module("homeassistant.components", True)
ha.components.mqtt = _module("homeassistant.components.mqtt")
ha.components.mqtt.ReceiveMessage = object
ha.const = _module("homeassistant.const")
ha.const.STATE_UNKNOWN = "unknown"
ha.const.STATE_UNAVAILABLE = "unavailable"
ha.core = _module("homeassistant.core")
ha.core.Event = object
ha.core.HomeAssistant = object
ha.core.State = object
ha.core.callback = lambda function: function
ha.helpers = _module("homeassistant.helpers", True)
ha.helpers.event = _module("homeassistant.helpers.event")
ha.helpers.event.async_track_state_change_event = lambda *args: (lambda: None)
ha.helpers.event.async_track_time_interval = lambda *args: (lambda: None)
ha.helpers.event.async_call_later = lambda *args: (lambda: None)

package = _module("companion_controller_regression", True)
package.__path__ = [str(COMPONENT)]
constants = _module(package.__name__ + ".const")
for key, value in {
    "CONF_AHC_AUTOMATION": "ahc_automation",
    "CONF_AUTO_RESUME": "auto_resume",
    "CONF_RADIATORS": "radiator_climates",
    "CONF_RADIATOR_MODES": "radiator_modes",
    "CONF_ROOM_CLIMATE": "room_climate",
    "CONF_ROOM_MODE": "room_operating_mode",
    "CONF_ROOM_TEMPERATURE": "room_temperature",
    "CONF_ROOM_TOPIC": "room_mqtt_topic",
    "CONF_SCHEDULE": "schedule_entity",
}.items():
    setattr(constants, key, value)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(package.__name__ + "." + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


policy = _load("policy", COMPONENT / "policy.py")
controller = _load("controller", COMPONENT / "controller.py")


def state(entity: str, value, temperature=None):
    return types.SimpleNamespace(
        entity_id=entity,
        state=value,
        attributes={} if temperature is None else {"temperature": temperature},
    )


class FakeServices:
    def __init__(self):
        self.calls = []
        self.on_call = None

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data))
        if self.on_call is not None:
            self.on_call(domain, service, data)


class FakeHass:
    def __init__(self):
        self.states = {
            "automation.ahc": state("automation.ahc", "on"),
            "schedule.room": state("schedule.room", "on"),
            "sensor.temp": state("sensor.temp", "22"),
            "select.room": state("select.room", "schedule"),
            "climate.room": state("climate.room", "heat", 22),
            "select.r1": state("select.r1", "manual"),
            "select.r2": state("select.r2", "manual"),
            "climate.r1": state("climate.r1", "heat", 22),
            "climate.r2": state("climate.r2", "heat", 22),
        }
        self.services = FakeServices()
        self.async_create_task = asyncio.create_task


def event(**data):
    return types.SimpleNamespace(data=data)


class ScheduleAndRetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hass = FakeHass()
        self.control = controller.BoschRoomController(self.hass, {
            "ahc_automation": "automation.ahc",
            "schedule_entity": "schedule.room",
            "room_climate": "climate.room",
            "room_operating_mode": "select.room",
            "room_temperature": "sensor.temp",
            "room_mqtt_topic": "zigbee2mqtt/Room",
            "radiator_climates": ["climate.r1", "climate.r2"],
            "radiator_modes": ["select.r1", "select.r2"],
        })
        self.control.enabled = True
        self.control.room_mode = "schedule"
        self.control.ahc_seen = True
        self.control.ahc_target = 22
        self.control.ahc_hvac_mode = "heat"

    async def _drain(self):
        task = self.control._reconcile_task
        if task is not None:
            await task

    async def test_schedule_edge_waits_for_fresh_ahc_before_writing(self):
        self.control.override_mode = "temporary"
        self.control.override_temperature = 23
        self.control._source_updated(event(
            old_state=state("schedule.room", "on"),
            new_state=state("schedule.room", "off"),
        ))
        self.hass.states["schedule.room"] = state("schedule.room", "off")
        await self._drain()
        self.assertTrue(self.control._pending_schedule_ahc)
        self.assertEqual(self.control.override_mode, "schedule")
        self.assertEqual(self.hass.services.calls, [])

        self.control._ahc_event(event(
            automation="automation.ahc",
            hvac_mode="heat",
            target_temperature=19,
            state=True,
        ))
        await self._drain()
        self.assertFalse(self.control._pending_schedule_ahc)
        writes = [d["temperature"] for domain, action, d in self.hass.services.calls
                  if (domain, action) == ("climate", "set_temperature")]
        self.assertEqual(writes, [19, 19])
        self.assertNotIn(22, writes)

    async def test_old_generation_cannot_continue_after_schedule_edge(self):
        self.hass.states["select.r1"] = state("select.r1", "schedule")

        def schedule_changed(domain, action, data):
            self.hass.services.on_call = None
            self.control._source_updated(event(
                old_state=state("schedule.room", "on"),
                new_state=state("schedule.room", "off"),
            ))

        self.hass.services.on_call = schedule_changed
        await self.control._async_apply(
            "climate.r1", "select.r1", policy.Desired("manual", 22),
            self.control._command_generation,
        )
        writes = [x for x in self.hass.services.calls
                  if x[0] == "climate" and x[1] == "set_temperature"]
        self.assertEqual(writes, [])
        self.assertTrue(self.control._pending_schedule_ahc)
        await self._drain()

    async def test_mismatched_state_retried_after_cooldown_not_90_seconds(self):
        desired = policy.Desired("manual", 19)
        self.control._last_sent["climate.r1"] = (desired, time.monotonic())
        await self.control._async_apply(
            "climate.r1", "select.r1", desired, self.control._command_generation,
        )
        self.assertEqual(self.hass.services.calls, [])
        self.assertIsNotNone(self.control._retry_unsub)

        self.control._last_sent["climate.r1"] = (desired, time.monotonic() - 26)
        await self.control._async_apply(
            "climate.r1", "select.r1", desired, self.control._command_generation,
        )
        self.assertEqual(len(self.hass.services.calls), 1)
        self.assertEqual(self.hass.services.calls[0][2]["temperature"], 19)

    async def test_matching_reported_state_not_written_again(self):
        self.hass.states["climate.r1"] = state("climate.r1", "heat", 19)
        await self.control._async_apply(
            "climate.r1", "select.r1", policy.Desired("manual", 19),
            self.control._command_generation,
        )
        self.assertEqual(self.hass.services.calls, [])


if __name__ == "__main__":
    unittest.main()
