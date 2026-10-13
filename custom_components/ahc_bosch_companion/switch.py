"""Explicit authorization switch for real radiator commands."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .controller import BoschRoomController


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    controller: BoschRoomController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BoschControlSwitch(entry, controller)])


class BoschControlSwitch(SwitchEntity):
    """Master switch OFF on every integration load or HA restart."""

    _attr_has_entity_name = True
    _attr_name = "Radiator output enabled"
    _attr_icon = "mdi:shield-lock"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, controller: BoschRoomController) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_output_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="AHC Bosch Companion",
            model="AHC bridge (test version)",
        )

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs) -> None:
        self._controller.async_set_control_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        self._controller.async_set_control_enabled(False)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._controller.async_add_listener(self.async_write_ha_state)
        )
