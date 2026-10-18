"""UI configuration for a controlled Bosch/AHC test room."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er, selector

from .const import (
    CONF_AHC_AUTOMATION,
    CONF_AUTO_RESUME,
    CONF_RADIATORS,
    CONF_RADIATOR_MODES,
    CONF_ROOM_CLIMATE,
    CONF_ROOM_MODE,
    CONF_ROOM_TEMPERATURE,
    CONF_ROOM_TOPIC,
    CONF_SCHEDULE,
    DOMAIN,
)


class AHCBoschCompanionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Choose the real Bosch entities and the AHC instance."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            climate = user_input[CONF_ROOM_CLIMATE]
            trvs = user_input[CONF_RADIATORS]
            modes = user_input[CONF_RADIATOR_MODES]
            topic = user_input[CONF_ROOM_TOPIC].strip()
            ids = [
                climate,
                user_input[CONF_ROOM_MODE],
                user_input[CONF_ROOM_TEMPERATURE],
                *([user_input[CONF_AHC_AUTOMATION]] if user_input.get(CONF_AHC_AUTOMATION) else []),
                user_input[CONF_SCHEDULE],
                *trvs,
                *modes,
            ]
            if any(self.hass.states.get(eid) is None for eid in ids):
                errors["base"] = "entity_not_found"
            elif not topic or topic.endswith(("/set", "/get")) or any(
                symbol in topic for symbol in ("+", "#")
            ):
                errors["base"] = "invalid_topic"
            elif not trvs or len(trvs) != len(modes) or len(set(trvs)) != len(trvs):
                errors["base"] = "invalid_radiators"
            elif (
                climate in trvs
                or user_input[CONF_ROOM_MODE] in modes
                or len(set(modes)) != len(modes)
            ):
                errors["base"] = "invalid_radiators"
            elif not self._check_radiator_pairings(trvs, modes):
                errors["base"] = "pairing_mismatch"
            else:
                await self.async_set_unique_id(climate)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Bosch Companion – {self.hass.states.get(climate).name}",
                    data={**user_input, CONF_ROOM_TOPIC: topic},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_ROOM_CLIMATE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Required(CONF_ROOM_MODE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="select")
                ),
                vol.Required(CONF_ROOM_TEMPERATURE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(CONF_ROOM_TOPIC): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Optional(CONF_AHC_AUTOMATION): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="automation")
                ),
                vol.Required(CONF_SCHEDULE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="schedule")
                ),
                vol.Required(CONF_RADIATORS): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate", multiple=True)
                ),
                vol.Required(CONF_RADIATOR_MODES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="select", multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    def _check_radiator_pairings(self, trvs: list[str], modes: list[str]) -> bool:
        """Never risk sending an operating-mode command to the wrong device."""
        registry = er.async_get(self.hass)
        for climate_id, select_id in zip(trvs, modes, strict=True):
            c = registry.async_get(climate_id)
            m = registry.async_get(select_id)
            # Without registry data we cannot establish safe device pairing.
            if not c or not m or not c.device_id or c.device_id != m.device_id:
                return False
            state = self.hass.states.get(select_id)
            options = state.attributes.get("options", []) if state else []
            if not {"manual", "pause"}.issubset(set(options)):
                return False
        return True


    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AHCBoschOptionsFlow:
        """Allow the AHC automation to be selected AFTER creating the proxy."""
        return AHCBoschOptionsFlow()


class AHCBoschOptionsFlow(OptionsFlowWithReload):
    """Assign the AHC automation when its proxy-based configuration exists."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if self.hass.states.get(user_input[CONF_AHC_AUTOMATION]) is None:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(),
                    errors={"base": "entity_not_found"},
                )
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=self._schema())

    def _schema(self) -> vol.Schema:
        current = self.config_entry.options.get(
            CONF_AHC_AUTOMATION, self.config_entry.data.get(CONF_AHC_AUTOMATION)
        )
        return vol.Schema(
            {
                vol.Required(
                    CONF_AHC_AUTOMATION,
                    description={"suggested_value": current} if current else None,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="automation")
                ),
                vol.Optional(
                    CONF_AUTO_RESUME,
                    default=self.config_entry.options.get(CONF_AUTO_RESUME, False),
                ): selector.BooleanSelector(),
            }
        )
