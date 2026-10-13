"""AHC Bosch Companion: read-only development integration.

The initial milestone creates diagnostic entities and deliberately does not
send commands to AHC, Zigbee2MQTT, or radiator thermostats.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one room from the UI configuration."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the read-only entities."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
