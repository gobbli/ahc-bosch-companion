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
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)

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
RETRY_DELAY_SECONDS = 25.0  # Retry mismatched device state without Zigbee flooding.


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
        self._room_stream_initialized = False
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
        # A schedule edge invalidates the cached AHC target until AHC replies.
        self._pending_schedule_ahc = False
        # Cancel obsolete commands between the two physical radiator updates.
        self._command_generation = 0
        self._retry_unsub: Callable[[], None] | None = None

    @property
    def device_ready(self) -> bool:
        """Require usable entities and an AHC event after integration startup."""
        if not self.ahc_seen or self.ahc_hvac_mode not in ("heat", "off"):
            return False
        if not self.data.get(CONF_AHC_AUTOMATION):
            return False
        ahc_entity = self.hass.states.get(self.data[CONF_AHC_AUTOMATION])
        if ahc_entity is None or ahc_entity.state != "on":
            return False  # Never actuate from a disabled AHC automation.
        if self.room_mode not in ("schedule", "manual", "pause"):
            return False
        if self.current_temperature is None:
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
        # Preserve an explicit physical Manual/Pause setting across HA restarts.
        # In schedule mode a missed boundary resets any temporary override.
        if self.room_mode == "manual":
            self.override_mode = "manual"
            self.override_temperature = self.last_room_setpoint
        elif self.room_mode == "pause":
            self.override_mode = "pause"
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
        self._cancel_retry()
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
        """Invalidate the previous AHC target at each schedule on/off edge."""
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
            ):
                # AHC may still be calculating its new target. Do NOT send the
                # former comfort target when clearing a temporary override.
                self._pending_schedule_ahc = True
                self._command_generation += 1
                if self.override_mode == "temporary":
                    self.override_mode = "schedule"
                    self.override_temperature = None
                _LOGGER.info(
                    "Schedule %s -> %s; suspending radiator commands until next "
                    "valid AHC event", old.state, new.state
                )
        elif new.entity_id == self.data[CONF_ROOM_MODE]:
            self._handle_room_mode(self._mode_from_entity())
        self._notify()
        self.queue_reconcile()

    @callback
    def _handle_room_mode(self, mode: str) -> None:
        if mode not in ("schedule", "manual", "pause") or mode == self.room_mode:
            return
        old_desired = self.desired
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
        if self.desired != old_desired:
            self._command_generation += 1

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

        old_desired = self.desired
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
                and self._room_stream_initialized
                and is_physical_schedule_change(
                    source, self.last_room_setpoint, incoming
                )
            ):
                self.override_mode = "temporary"
                self.override_temperature = incoming
                _LOGGER.info("Bosch physical adjustment: temporary override %.1f °C", incoming)
            self.last_room_setpoint = incoming
            self._room_stream_initialized = True
        if self.desired != old_desired:
            self._command_generation += 1
        self._notify()
        self.queue_reconcile()

    @callback
    def _ahc_event(self, event: Event) -> None:
        """Read ONLY events from the configured AHC automation."""
        if event.data.get("automation") != self.data.get(CONF_AHC_AUTOMATION):
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
        self.ahc_protection = (
            not _is_true(event.data.get("state"))  # AHC globally inactive.
            or any(
                _is_true(event.data.get(key))
                for key in (
                    "state_window", "is_frost_protection", "is_liming_protection",
                    "is_force_eco_temperature", "is_force_max_temperature",
                )
            )
            or event.data.get("active_party_entity") not in (None, "", "None", "none")
        )
        self.last_error = None
        self._command_generation += 1
        if self._pending_schedule_ahc:
            self._pending_schedule_ahc = False
            _LOGGER.info(
                "Fresh AHC event after schedule edge: mode=%s target=%s "
                "trigger=%s; radiator output resumed",
                mode, target, self.last_ahc_trigger,
            )
        else:
            _LOGGER.debug(
                "AHC event: mode=%s target=%s protection=%s trigger=%s",
                mode, target, self.ahc_protection, self.last_ahc_trigger,
            )
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

    @callback
    def _schedule_retry(self, delay: float = RETRY_DELAY_SECONDS) -> None:
        """Re-check real HA device state even if Zigbee never sends an echo."""
        if not self.enabled or self._retry_unsub is not None:
            return
        self._retry_unsub = async_call_later(self.hass, max(0.1, delay), self._retry_due)

    @callback
    def _retry_due(self, now: Any) -> None:
        self._retry_unsub = None
        self.queue_reconcile()

    @callback
    def _cancel_retry(self) -> None:
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

    def _command_is_current(self, generation: int) -> bool:
        return (
            self.enabled
            and not self._pending_schedule_ahc
            and generation == self._command_generation
        )

    async def _async_reconcile_loop(self) -> None:
        async with self._lock:
            while self._needs_reconcile and self.enabled:
                self._needs_reconcile = False
                if self._pending_schedule_ahc:
                    # Fail closed rather than send the preceding schedule target.
                    # The next matching AHC event will queue a fresh reconcile.
                    _LOGGER.debug("Waiting for post-schedule AHC event")
                    return
                if not self.device_ready:
                    self.last_error = "Waiting for valid Bosch entities and an AHC event"
                    self._notify()
                    return
                desired = self.desired
                if desired is None:
                    return
                generation = self._command_generation
                for climate, mode in zip(
                    self.data[CONF_RADIATORS],
                    self.data[CONF_RADIATOR_MODES],
                    strict=True,
                ):
                    if not self._command_is_current(generation):
                        break
                    try:
                        await self._async_apply(climate, mode, desired, generation)
                    except Exception as err:  # HA/Z2M service layer errors vary
                        self.last_error = f"Command to {climate} failed: {err}"
                        _LOGGER.exception("Bosch radiator command failed")
                        self._notify()
                        # Retry only on next event or interval.

    async def _async_apply(
        self, climate: str, mode_select: str, desired: Desired, generation: int
    ) -> None:
        if not self._command_is_current(generation):
            return
        mode_state = self.hass.states.get(mode_select)
        climate_state = self.hass.states.get(climate)
        if (
            mode_state is None or mode_state.state in UNKNOWN
            or climate_state is None or climate_state.state in UNKNOWN
        ):
            self.last_error = f"Radiator {climate} unavailable"
            self._notify()
            return

        current = valid_temp(climate_state.attributes.get("temperature"))
        mode_wrong = mode_state.state != desired.mode
        temperature_wrong = (
            desired.mode == "manual"
            and desired.temperature is not None
            and (current is None or abs(current - desired.temperature) >= 0.1)
        )
        if not mode_wrong and not temperature_wrong:
            return  # HA-reported state matches; avoid unnecessary Zigbee traffic.

        previous = self._last_sent.get(climate)
        if previous and previous[0] == desired:
            elapsed = monotonic() - previous[1]
            if elapsed < RETRY_DELAY_SECONDS:
                # Unlike b1's unconditional 90 s suppression, this only delays
                # a retry of a still-MISMATCHED device, then verifies again.
                self._schedule_retry(RETRY_DELAY_SECONDS - elapsed)
                _LOGGER.debug(
                    "Radiator %s still mismatched (%s/%s vs %s); retry in %.1fs",
                    climate, mode_state.state, current, desired,
                    RETRY_DELAY_SECONDS - elapsed,
                )
                return

        if mode_wrong:
            _LOGGER.info(
                "Sending Bosch mode to %s via %s: %s -> %s (requested)",
                climate, mode_select, mode_state.state, desired.mode,
            )
            await self.hass.services.async_call(
                "select", "select_option",
                {"entity_id": mode_select, "option": desired.mode},
                blocking=True,
            )
        # A schedule/room/target change may arrive during the first service call.
        if not self._command_is_current(generation):
            _LOGGER.debug("Discarding superseded setpoint command for %s", climate)
            return
        if desired.mode == "manual" and desired.temperature is not None:
            if mode_wrong or temperature_wrong:
                _LOGGER.info(
                    "Sending Bosch setpoint to %s: %s -> %.1f°C (requested)",
                    climate, current, desired.temperature,
                )
                await self.hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": climate, "temperature": desired.temperature},
                    blocking=True,
                )
        self._last_sent[climate] = (desired, monotonic())
        self._schedule_retry()
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
            self._needs_reconcile = False
            self._cancel_retry()
            _LOGGER.warning("AHC Bosch Companion radiator output DISABLED; valves unchanged")
