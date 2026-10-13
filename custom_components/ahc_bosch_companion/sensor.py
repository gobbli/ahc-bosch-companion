"""Read-only status sensors for one Bosch Room Thermostat II.

Only mirrors entity states already held by Home Assistant.
No direct MQTT, climate, or AHC commands are sent by this integration.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_ROOM_CLIMATE, CONF_ROOM_MODE, DOMAIN, ROOM_MODES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[..., None],
) -> None:
    """Expose two diagnostic sensors for the configured room."""
    async_add_entities(
        [
            BoschCompanionSensor(entry, "mode"),
            BoschCompanionSensor(entry, "setpoint"),
        ]
    )


class BoschCompanionSensor(SensorEntity):
    """Mirror one value from an existing climate/select entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, kind: str) -> None:
        """Create a read-only diagnostic entity."""
        self._kind = kind
        self._climate_entity = entry.data[CONF_ROOM_CLIMATE]
        self._mode_entity = entry.data[CONF_ROOM_MODE]
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_name = (
            "Operating mode" if kind == "mode" else "Requested setpoint"
        )
        self._attr_icon = "mdi:thermostat"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"AHC Bosch Companion ({self._climate_entity})",
            manufacturer="AHC Bosch Companion",
            model="Read-only room diagnostics",
        )

        if kind == "setpoint":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Use the Home Assistant configured temperature unit."""
        if self._kind == "setpoint":
            return self.hass.config.units.temperature_unit
        return None

    @property
    def available(self) -> bool:
        """Avoid presenting stale or invalid values as valid."""
        state = self._get_source_state()
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return False
        if self._kind == "mode":
            return state.state in ROOM_MODES
        value = state.attributes.get("temperature")
        try:
            return math.isfinite(float(value)) and 5 <= float(value) <= 35
        except (TypeError, ValueError):
            return False

    @property
    def native_value(self) -> str | float | None:
        """Return the actual source value without commanding a device."""
        state = self._get_source_state()
        if not self.available or state is None:
            return None
        if self._kind == "mode":
            return state.state
        return float(state.attributes["temperature"])

    def _get_source_state(self) -> Any:
        """Read the selected underlying HA entity."""
        entity_id = (
            self._mode_entity if self._kind == "mode" else self._climate_entity
        )
        return self.hass.states.get(entity_id)

    async def async_added_to_hass(self) -> None:
        """Subscribe to source entity updates, with automatic cleanup."""
        await super().async_added_to_hass()
        entity_id = (
            self._mode_entity if self._kind == "mode" else self._climate_entity
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [entity_id],
                self._async_source_changed,
            )
        )

    @callback
    def _async_source_changed(self, event: Event) -> None:
        """Refresh state after the original HA entity changed."""
        self.async_write_ha_state()
