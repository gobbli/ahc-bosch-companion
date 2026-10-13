"""Constants for AHC Bosch Companion."""

from homeassistant.const import Platform

DOMAIN = "ahc_bosch_companion"
CONF_ROOM_CLIMATE = "room_climate"
CONF_ROOM_MODE = "room_operating_mode"
CONF_ROOM_TOPIC = "room_mqtt_topic"
CONF_ROOM_TEMPERATURE = "room_temperature"
CONF_AHC_AUTOMATION = "ahc_automation"
CONF_SCHEDULE = "schedule_entity"
CONF_RADIATORS = "radiator_climates"
CONF_RADIATOR_MODES = "radiator_modes"

PLATFORMS: tuple[Platform, ...] = (Platform.CLIMATE, Platform.SENSOR, Platform.SWITCH)
ROOM_MODES = frozenset({"schedule", "manual", "pause"})
DEFAULT_MIN = 5.0
DEFAULT_MAX = 30.0
