"""DataUpdateCoordinator pre Greenlogy."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GreenlogyApiClient, GreenlogyApiError, GreenlogyAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class GreenlogyDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Koordinátor na pravidelné sťahovanie dát z Greenlogy."""

    def __init__(self, hass: HomeAssistant, client: GreenlogyApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            return await self.client.async_get_virtual_batteries()
        except GreenlogyAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except GreenlogyApiError as err:
            raise UpdateFailed(err) from err
