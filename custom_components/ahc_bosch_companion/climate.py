"""Virtual climate target for the original AHC blueprint.

AHC MUST target this entity, never the real BTH-RA climate entities in parallel.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .controller import BoschRoomController
from .policy import valid_temp


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    controller: BoschRoomController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AHCBoschClimate(entry, controller)])


class AHCBoschClimate(ClimateEntity):
    """AHC-compatible heat/off proxy, NO internal thermostat algorithm."""

    _attr_has_entity_name = True
    _attr_name = "AHC controlled heating"
    _attr_should_poll = False
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5
    _attr_max_temp = 30

    def __init__(self, entry: ConfigEntry, controller: BoschRoomController) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_virtual_climate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="AHC Bosch Companion",
            model="AHC bridge (test version)",
        )

    @property
    def available(self) -> bool:
        """Visible to AHC when the physical room sensor is readable."""
        return self._controller.current_temperature is not None

    @property
    def current_temperature(self) -> float | None:
        return self._controller.current_temperature

    @property
    def target_temperature(self) -> float | None:
        """Report AHC's requested target, not the local override.

        This prevents AHC from interpreting a Bosch manual override as a
        physical change of a radiator target temperature.
        """
        return self._controller.ahc_target

    @property
    def hvac_mode(self) -> HVACMode:
        mode = self._controller.ahc_hvac_mode
        return HVACMode.OFF if mode == "off" else HVACMode.HEAT

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        desired = self._controller.desired
        return {
            "bosch_room_mode": self._controller.room_mode,
            "bosch_override_mode": self._controller.override_mode,
            "bosch_override_temperature": self._controller.override_temperature,
            "ahc_event_received": self._controller.ahc_seen,
            "ahc_protection": self._controller.ahc_protection,
            "bosch_desired_mode": desired.mode if desired else None,
            "bosch_desired_temperature": desired.temperature if desired else None,
            "radiator_output_enabled": self._controller.enabled,
            "auto_resume_configured": self._controller.auto_resume_configured,
            "auto_resume_pending": self._controller.auto_resume_pending,
            "auto_resume_blockers": self._controller.auto_resume_blockers,
            "auto_resumed": self._controller.auto_resumed,
            "last_error": self._controller.last_error,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Receive AHC setpoint without immediately bypassing safety gates."""
        target = valid_temp(kwargs.get(ATTR_TEMPERATURE))
        if target is None:
            raise ValueError("AHC Bosch Companion requires 5-30 °C target")
        self._controller.ahc_target = target
        self._controller._notify()
        self._controller.queue_reconcile()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Receive AHC HEAT or OFF state."""
        actual_mode = str(getattr(hvac_mode, "value", hvac_mode))
        if actual_mode not in ("heat", "off"):
            raise ValueError("Only HEAT and OFF are supported by the AHC proxy")
        self._controller.ahc_hvac_mode = actual_mode
        self._controller._notify()
        self._controller.queue_reconcile()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._controller.async_add_listener(self.async_write_ha_state)
        )
