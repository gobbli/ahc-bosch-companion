"""Event-driven room controller: AHC owns normal targets, Bosch owns local input.

No radiator action can occur until an explicit in-HA enable switch is turned ON.
The switch always resets to OFF on each Home Assistant restart/reload.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.components import mqtt
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from .const import (
    CONF_AHC_AUTOMATION,
    CONF_RADIATORS,
    CONF_RADIATOR_MODES,
    CONF_ROOM_CLIMATE,
    CONF_ROOM_MODE,
    CONF_ROOM_TEMPERATURE,
    CONF_ROOM_TOPIC,
    CONF_SCHEDULE,
)
from .policy import Desired, decide, is_physical_schedule_change, valid_temp

_LOGGER = logging.getLogger(__name__)
UNKNOWN = {STATE_UNKNOWN, STATE_UNAVAILABLE, None}
RECONCILE_INTERVAL = timedelta(minutes=10)


def _is_true(value: object) -> bool:
    """Normalize AHC event boolean fields, without treating 'False' as true."""
    return value is True or value == "True" or value == "true"


class BoschRoomController:
    """Coordinates one AHC instance, one room control and N Bosch BTH-RAs."""

    def __init__(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        self.hass = hass
        self.data = data
        self.enabled = False  # Never persisted: fail-safe after any restart.
        self.room_mode = "unknown"
        self.override_mode = "schedule"
        self.override_temperature: float | None = None
        self.last_room_setpoint: float | None = None
        self.ahc_target: float | None = None
        self.ahc_hvac_mode = "unknown"
        self.ahc_protection = False
        self.ahc_seen = False
        self.last_ahc_trigger: str | None = None
        self.last_error: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._needs_reconcile = False
        self._reconcile_task: asyncio.Task[None] | None = None
        self._last_sent: dict[str, tuple[Desired, float]] = {}

    @property
    def device_ready(self) -> bool:
        """Require usable entities and an AHC event after integration startup."""
        if not self.ahc_seen or self.ahc_hvac_mode not in ("heat", "off"):
            return False
        if self.room_mode not in ("schedule", "manual", "pause"):
            return False
        if not self._valid_entity(self.data[CONF_ROOM_TEMPERATURE]):
            return False
        for entity in (
            self.data[CONF_ROOM_MODE],
            self.data[CONF_ROOM_CLIMATE],
            self.data[CONF_SCHEDULE],
        ):
            if not self._valid_entity(entity):
                return False
        if self.hass.states.get(self.data[CONF_SCHEDULE]).state not in ("on", "off"):
            return False
        for climate, mode in zip(
            self.data[CONF_RADIATORS], self.data[CONF_RADIATOR_MODES], strict=True
        ):
            if not self._valid_entity(climate) or not self._valid_entity(mode):
                return False
        return self.desired is not None

    @property
    def desired(self) -> Desired | None:
        """Compute the only desired output; zero device access here."""
        return decide(
            self.ahc_target,
            self.ahc_hvac_mode,
            self.room_mode,
            self.override_mode,
            self.override_temperature,
            ahc_protection=self.ahc_protection,
        )

    @property
    def current_temperature(self) -> float | None:
        """HA user-visible room temperature (Germany installation uses Celsius)."""
        state = self.hass.states.get(self.data[CONF_ROOM_TEMPERATURE])
        return valid_temp(state.state, 0, 35) if state else None

    def _valid_entity(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and state.state not in UNKNOWN

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe entity platform to controller notifications."""
        self._listeners.append(listener)

        @callback
        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    async def async_start(self) -> None:
        """Subscribe without enabling output."""
        self.room_mode = self._mode_from_entity()
        room = self.hass.states.get(self.data[CONF_ROOM_CLIMATE])
        if room is not None:
            self.last_room_setpoint = valid_temp(room.attributes.get("temperature"))
        self._unsubs.append(
            async_track_state_change_event(
                self.hass,
                [self.data[CONF_ROOM_MODE], self.data[CONF_SCHEDULE],
                 self.data[CONF_ROOM_TEMPERATURE], self.data[CONF_ROOM_CLIMATE],
                 *self.data[CONF_RADIATORS], *self.data[CONF_RADIATOR_MODES]],
                self._source_updated,
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen("ahc_event", self._ahc_event)
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._periodic_reconcile, RECONCILE_INTERVAL
            )
        )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass,
                self.data[CONF_ROOM_TOPIC],
                self._room_message,
                qos=1,
            )
        )
        self._notify()
        _LOGGER.info("AHC Bosch Companion loaded: output is OFF by default")

    async def async_stop(self) -> None:
        """Tear down callbacks; never issue commands on unload."""
        self.enabled = False
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._reconcile_task is not None:
            self._reconcile_task.cancel()
            try:
                await self._reconcile_task
            except asyncio.CancelledError:
                pass
        self._listeners.clear()

    def _mode_from_entity(self) -> str:
        state = self.hass.states.get(self.data[CONF_ROOM_MODE])
        if state is not None and state.state in ("schedule", "manual", "pause"):
            return state.state
        return "unknown"

    @callback
    def _source_updated(self, event: Event) -> None:
        """Handle entity status changes and a single schedule boundary."""
        old: State | None = event.data.get("old_state")
        new: State | None = event.data.get("new_state")
        if new is None:
            return
        if new.entity_id == self.data[CONF_SCHEDULE]:
            if (
                old is not None
                and old.state in ("on", "off")
                and new.state in ("on", "off")
                and old.state != new.state
                and self.override_mode == "temporary"
            ):
                self.override_mode = "schedule"
                self.override_temperature = None
                _LOGGER.info("Temporary room override ended at AHC schedule boundary")
        elif new.entity_id == self.data[CONF_ROOM_MODE]:
            self._handle_room_mode(self._mode_from_entity())
        self._notify()
        self.queue_reconcile()

    @callback
    def _handle_room_mode(self, mode: str) -> None:
        if mode not in ("schedule", "manual", "pause") or mode == self.room_mode:
            return
        self.room_mode = mode
        if mode == "schedule":
            self.override_mode = "schedule"
            self.override_temperature = None
        elif mode == "manual":
            self.override_mode = "manual"
            self.override_temperature = self.last_room_setpoint
        elif mode == "pause":
            self.override_mode = "pause"
            self.override_temperature = None

    @callback
    def _room_message(self, message: mqtt.ReceiveMessage) -> None:
        """Use the actual Zigbee2MQTT change source; no source = no new override."""
        if getattr(message, "retain", False):
            return  # A retained old 'manual' message is not a fresh adjustment.
        try:
            payload = json.loads(message.payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return

        candidate = payload.get("operating_mode")
        if candidate in ("schedule", "manual", "pause"):
            self._handle_room_mode(candidate)
        source = payload.get("setpoint_change_source")
        incoming = (
            valid_temp(payload["occupied_heating_setpoint"])
            if "occupied_heating_setpoint" in payload
            else None
        )
        if incoming is not None:
            if self.room_mode == "manual":
                self.override_mode = "manual"
                self.override_temperature = incoming
            elif (
                self.room_mode == "schedule"
                and is_physical_schedule_change(
                    source, self.last_room_setpoint, incoming
                )
            ):
                self.override_mode = "temporary"
                self.override_temperature = incoming
                _LOGGER.info("Bosch physical adjustment: temporary override %.1f °C", incoming)
            self.last_room_setpoint = incoming
        self._notify()
        self.queue_reconcile()

    @callback
    def _ahc_event(self, event: Event) -> None:
        """Read ONLY events from the configured AHC automation."""
        if event.data.get("automation") != self.data[CONF_AHC_AUTOMATION]:
            return
        mode = event.data.get("hvac_mode")
        if mode not in ("heat", "off"):
            self.ahc_seen = False
            self.last_error = f"Unsupported AHC HVAC mode: {mode!r}"
            self._notify()
            return
        target = valid_temp(event.data.get("target_temperature"))
        if mode == "heat" and target is None:
            self.ahc_seen = False
            self.last_error = "AHC did not report a valid setpoint"
            self._notify()
            return
        self.ahc_seen = True
        self.ahc_target = target
        self.ahc_hvac_mode = mode
        self.last_ahc_trigger = str(event.data.get("last_trigger_id", ""))
        self.ahc_protection = any(
            _is_true(event.data.get(key))
            for key in (
                "state_window", "is_frost_protection", "is_liming_protection",
                "is_force_eco_temperature", "is_force_max_temperature",
            )
        ) or event.data.get("active_party_entity") not in (None, "", "None", "none")
        self.last_error = None
        self._notify()
        self.queue_reconcile()

    @callback
    def _periodic_reconcile(self, now: Any) -> None:
        """Retry only outstanding changes, never without explicit enable."""
        self.queue_reconcile()

    @callback
    def queue_reconcile(self) -> None:
        if not self.enabled:
            return
        self._needs_reconcile = True
        if self._reconcile_task is None or self._reconcile_task.done():
            self._reconcile_task = self.hass.async_create_task(
                self._async_reconcile_loop()
            )

    async def _async_reconcile_loop(self) -> None:
        async with self._lock:
            while self._needs_reconcile and self.enabled:
                self._needs_reconcile = False
                if not self.device_ready:
                    self.last_error = "Waiting for valid Bosch entities and an AHC event"
                    self._notify()
                    return
                desired = self.desired
                if desired is None:
                    return
                for climate, mode in zip(
                    self.data[CONF_RADIATORS],
                    self.data[CONF_RADIATOR_MODES],
                    strict=True,
                ):
                    if not self.enabled:
                        break
                    try:
                        await self._async_apply(climate, mode, desired)
                    except Exception as err:  # HA/Z2M service layer errors vary
                        self.last_error = f"Command to {climate} failed: {err}"
                        _LOGGER.exception("Bosch radiator command failed")
                        self._notify()
                        # Retry on next scheduled check, not a busy loop.

    async def _async_apply(
        self, climate: str, mode_select: str, desired: Desired
    ) -> None:
        mode_state = self.hass.states.get(mode_select)
        climate_state = self.hass.states.get(climate)
        if (
            mode_state is None or mode_state.state in UNKNOWN
            or climate_state is None or climate_state.state in UNKNOWN
        ):
            self.last_error = f"Radiator {climate} unavailable"
            return
        previous = self._last_sent.get(climate)
        if previous and previous[0] == desired and monotonic() - previous[1] < 90:
            return  # Avoid flooding sleepy Zigbee TRVs awaiting their echo.

        if mode_state.state != desired.mode:
            await self.hass.services.async_call(
                "select", "select_option",
                {"entity_id": mode_select, "option": desired.mode},
                blocking=True,
            )
        if desired.mode == "manual" and desired.temperature is not None:
            current = valid_temp(climate_state.attributes.get("temperature"))
            # On a pause -> manual transition, always set the temperature.
            if mode_state.state != "manual" or current is None or abs(current - desired.temperature) >= 0.1:
                await self.hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": climate, "temperature": desired.temperature},
                    blocking=True,
                )
        self._last_sent[climate] = (desired, monotonic())
        self.last_error = None
        self._notify()

    @callback
    def async_set_control_enabled(self, enabled: bool) -> None:
        """Explicit user gate; turns OFF without modifying a physical valve."""
        self.enabled = enabled
        self._notify()
        if enabled:
            _LOGGER.warning("AHC Bosch Companion radiator output explicitly ENABLED")
            self.queue_reconcile()
        else:
            _LOGGER.warning("AHC Bosch Companion radiator output DISABLED; valves unchanged")
