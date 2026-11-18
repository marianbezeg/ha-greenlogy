"""Inicializácia integrácie Greenlogy."""

from __future__ import annotations

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import GreenlogyApiClient
from .coordinator import GreenlogyDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type GreenlogyConfigEntry = ConfigEntry[GreenlogyDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GreenlogyConfigEntry) -> bool:
    """Nastavenie Greenlogy z config entry."""
    session = async_create_clientsession(
        hass,
        verify_ssl=False,
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )

    client = GreenlogyApiClient(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        session=session,
    )

    coordinator = GreenlogyDataUpdateCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GreenlogyConfigEntry) -> bool:
    """Odstránenie integrácie."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
