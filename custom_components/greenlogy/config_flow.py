"""Config flow pre integráciu Greenlogy."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    GreenlogyApiClient,
    GreenlogyApiError,
    GreenlogyAuthError,
    GreenlogyNoBatteryError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class GreenlogyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Spracovanie pridania integrácie cez UI."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            session = async_create_clientsession(
                self.hass,
                verify_ssl=False,
                cookie_jar=aiohttp.CookieJar(unsafe=True),
            )
            client = GreenlogyApiClient(email, password, session)

            try:
                await client.async_get_virtual_batteries()
            except GreenlogyAuthError:
                errors["base"] = "invalid_auth"
            except GreenlogyNoBatteryError:
                errors["base"] = "no_battery"
            except GreenlogyApiError as err:
                _LOGGER.error("Chyba pripojenia k Greenlogy: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Neočakávaná chyba pri nastavení Greenlogy")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Greenlogy ({email})",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
