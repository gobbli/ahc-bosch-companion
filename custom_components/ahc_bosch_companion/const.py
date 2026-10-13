"""Constants for AHC Bosch Companion."""

from homeassistant.const import Platform

DOMAIN = "ahc_bosch_companion"

CONF_ROOM_CLIMATE = "room_climate"
CONF_ROOM_MODE = "room_operating_mode"

PLATFORMS: tuple[Platform, ...] = (Platform.SENSOR,)

ROOM_MODES: frozenset[str] = frozenset({"schedule", "manual", "pause"})
