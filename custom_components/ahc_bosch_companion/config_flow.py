"""User interface setup for read-only Bosch room thermostat diagnostics."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import CONF_ROOM_CLIMATE, CONF_ROOM_MODE, DOMAIN


class AHCBoschCompanionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure Bosch room readings from existing Zigbee2MQTT entities."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose existing HA room climate and operating-mode entities."""
        errors: dict[str, str] = {}

        if user_input is not None:
            room_climate = user_input[CONF_ROOM_CLIMATE]
            room_mode = user_input[CONF_ROOM_MODE]

            if (
                self.hass.states.get(room_climate) is None
                or self.hass.states.get(room_mode) is None
            ):
                errors["base"] = "entity_not_found"
            else:
                await self.async_set_unique_id(room_climate)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Bosch Companion – {self.hass.states.get(room_climate).name}",
                    data=user_input,
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ROOM_CLIMATE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Required(CONF_ROOM_MODE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="select")
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )
