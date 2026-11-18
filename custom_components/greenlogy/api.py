"""API klient pre Greenlogy portál."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp
from yarl import URL

from .const import BASE_URL, CLIENT_ID, ORG_ID

_LOGGER = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "Accept": "*/*",
    "User-Agent": "curl/8.5.0",
}


class GreenlogyApiError(Exception):
    """Všeobecná chyba komunikácie s Greenlogy API."""


class GreenlogyAuthError(GreenlogyApiError):
    """Chyba prihlásenia (nesprávne meno alebo heslo)."""


class GreenlogyNoBatteryError(GreenlogyApiError):
    """Na účte nebola nájdená žiadna virtuálna batéria."""


class GreenlogyApiClient:
    """Klient na komunikáciu s Greenlogy API."""

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self._email = email
        self._password = password
        self._session = session
        self._logged_in = False

    async def async_login(self) -> None:
        """Prihlási používateľa a uloží session cookies."""
        url = f"{BASE_URL}/auth/login"
        payload = {
            "email": self._email,
            "password": self._password,
            "clientId": CLIENT_ID,
        }
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {**DEFAULT_HEADERS, "Content-Type": "application/json"}

        try:
            async with self._session.post(
                url, data=payload_bytes, headers=headers
            ) as response:
                if response.status in (401, 403):
                    self._logged_in = False
                    body = await response.text()
                    _LOGGER.warning(
                        "Greenlogy prihlásenie zlyhalo (HTTP %s): %s",
                        response.status,
                        body[:200],
                    )
                    raise GreenlogyAuthError("Nesprávny e-mail alebo heslo.")
                if response.status >= 400:
                    body = await response.text()
                    _LOGGER.error(
                        "Greenlogy login HTTP chyba %s: %s",
                        response.status,
                        body[:300],
                    )
                    raise GreenlogyApiError(f"HTTP {response.status}: {body[:300]}")
                self._logged_in = True
        except (GreenlogyAuthError, GreenlogyApiError):
            raise
        except aiohttp.ClientError as err:
            self._logged_in = False
            _LOGGER.error("Greenlogy chyba pripojenia pri prihlásení: %s", err)
            raise GreenlogyApiError(f"Chyba pripojenia pri prihlásení: {err}") from err

    async def _async_get(self, url: str | URL) -> Any:
        """Vykoná GET požiadavku s automatickým obnovením prihlásenia pri 401/403."""
        if not self._logged_in:
            await self.async_login()

        try:
            async with self._session.get(url, headers=DEFAULT_HEADERS) as response:
                if response.status in (401, 403):
                    _LOGGER.debug("Session expirovala, skúšam opätovné prihlásenie")
                    await self.async_login()
                    async with self._session.get(
                        url, headers=DEFAULT_HEADERS
                    ) as retry_response:
                        if retry_response.status in (401, 403):
                            raise GreenlogyAuthError("Autentifikácia zlyhala.")
                        retry_response.raise_for_status()
                        return await retry_response.json(content_type=None)

                if response.status >= 400:
                    body = await response.text()
                    _LOGGER.error(
                        "Greenlogy GET %s vrátil HTTP %s: %s",
                        url,
                        response.status,
                        body[:300],
                    )
                    raise GreenlogyApiError(f"HTTP {response.status}: {body[:300]}")
                return await response.json(content_type=None)
        except (GreenlogyAuthError, GreenlogyApiError):
            raise
        except aiohttp.ClientError as err:
            _LOGGER.error("Greenlogy chyba pri sťahovaní dát z %s: %s", url, err)
            raise GreenlogyApiError(f"Chyba pri sťahovaní dát z API: {err}") from err

    async def async_get_virtual_batteries(self) -> dict[str, dict[str, Any]]:
        """Stiahne dáta pre všetky aktívne virtuálne batérie na účte."""
        services_url = (
            f"{BASE_URL}/me/organizations/{ORG_ID}"
            "/customer_services?active=true&type=virtual_battery"
        )
        services = await self._async_get(services_url)

        if not isinstance(services, list):
            _LOGGER.error("Neočakávaný formát customer_services: %s", type(services))
            raise GreenlogyApiError("Neočakávaná odpoveď zo servera Greenlogy.")

        vb_services = [
            srv
            for srv in services
            if isinstance(srv, dict)
            and (srv.get("product") or {}).get("type") == "virtual_battery"
        ]

        if not vb_services:
            raise GreenlogyNoBatteryError(
                "Na tomto účte nebola nájdená žiadna aktívna virtuálna batéria."
            )

        results: dict[str, dict[str, Any]] = {}

        for srv in vb_services:
            service_id = srv["id"]
            product_name = (srv.get("product") or {}).get(
                "name", "Virtuálna batéria"
            )
            display_name = srv.get("description") or product_name

            detail_url = (
                f"{BASE_URL}/me/organizations/{ORG_ID}"
                f"/customer_services/virtual_battery/{service_id}"
            )
            detail = await self._async_get(detail_url)
            vb_data = (detail or {}).get("virtualBattery") or {}

            last_invoice_date: str | None = vb_data.get("lastInvoicing")
            accumulated = vb_data.get("accumulatedProduction") or {}

            consumption_val = None
            production_val = None

            if last_invoice_date and last_invoice_date != "null":
                encoded_date = last_invoice_date.replace(":", "%253A")

                cons_url = URL(
                    f"{BASE_URL}/me/organizations/{ORG_ID}"
                    f"/customer_services/virtual_battery/{service_id}"
                    f"/consumption?from={encoded_date}",
                    encoded=True,
                )
                prod_url = URL(
                    f"{BASE_URL}/me/organizations/{ORG_ID}"
                    f"/customer_services/virtual_battery/{service_id}"
                    f"/production?from={encoded_date}",
                    encoded=True,
                )

                try:
                    cons_data = await self._async_get(cons_url)
                    consumption_val = (cons_data or {}).get("value")
                except GreenlogyApiError as err:
                    _LOGGER.warning("Nepodarilo sa načítať consumption: %s", err)

                try:
                    prod_data = await self._async_get(prod_url)
                    production_val = (prod_data or {}).get("value")
                except GreenlogyApiError as err:
                    _LOGGER.warning("Nepodarilo sa načítať production: %s", err)

            results[service_id] = {
                "id": service_id,
                "name": display_name,
                "accumulated_production": accumulated.get("value"),
                "unit": accumulated.get("unit", "kWh"),
                "time": accumulated.get("time"),
                "last_invoicing": last_invoice_date,
                "consumption": consumption_val,
                "production": production_val,
            }

        return results
