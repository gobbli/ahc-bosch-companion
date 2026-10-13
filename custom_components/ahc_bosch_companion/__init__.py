"""AHC Bosch Companion integration: guarded virtual AHC climate interface."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .controller import BoschRoomController


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize subscriptions before exposing entities."""
    controller = BoschRoomController(hass, dict(entry.data))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    try:
        await controller.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await controller.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop physical output FIRST, then unload the virtual entities."""
    controller: BoschRoomController = hass.data[DOMAIN][entry.entry_id]
    controller.async_set_control_enabled(False)
    result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if result:
        await controller.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return result
