"""Senzory pre integráciu Greenlogy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import GreenlogyConfigEntry
from .const import DOMAIN
from .coordinator import GreenlogyDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class GreenlogySensorEntityDescription(SensorEntityDescription):
    """Popis Greenlogy senzora."""

    value_fn: Callable[[dict[str, Any]], Any]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _parse_timestamp(value: str | None) -> datetime | None:
    """Prevedie ISO reťazec na datetime s časovou zónou."""
    if not value:
        return None
    return dt_util.parse_datetime(value)


def _calc_net_balance(data: dict[str, Any]) -> float | None:
    """Vypočíta čistý zostatok virtuálnej batérie (uložené - odobraté)."""
    accumulated = data.get("accumulated_production")
    if accumulated is None:
        return None
    consumption = data.get("consumption") or 0
    return round(float(accumulated) - float(consumption), 3)


def _calc_sync_status(data: dict[str, Any]) -> str:
    """Zistí, či sú dáta z distribučky synchronizované (dátum aktualizácie == včera)."""
    parsed = _parse_timestamp(data.get("time"))
    if parsed is None:
        return "Oneskorené"
    last_update_date = dt_util.as_local(parsed).date()
    yesterday = (dt_util.now() - timedelta(days=1)).date()
    return "Synchronizované" if last_update_date == yesterday else "Oneskorené"


SENSORS: tuple[GreenlogySensorEntityDescription, ...] = (
    GreenlogySensorEntityDescription(
        key="net_balance",
        translation_key="net_balance",
        name="Zostatok virtuálnej batérie",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-heart-variant",
        value_fn=_calc_net_balance,
        attr_fn=lambda data: {
            "sync_status": _calc_sync_status(data),
            "time": data.get("time"),
            "unit": data.get("unit"),
        },
    ),
    GreenlogySensorEntityDescription(
        key="accumulated_production",
        translation_key="accumulated_production",
        name="Stav virtuálnej batérie",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-charging",
        value_fn=lambda data: data.get("accumulated_production"),
        attr_fn=lambda data: {
            "unit": data.get("unit"),
            "time": data.get("time"),
        },
    ),
    GreenlogySensorEntityDescription(
        key="consumption",
        translation_key="consumption",
        name="Odber od poslednej fakturácie",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:transmission-tower-export",
        value_fn=lambda data: data.get("consumption"),
    ),
    GreenlogySensorEntityDescription(
        key="production",
        translation_key="production",
        name="Dodávka od poslednej fakturácie",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-power",
        value_fn=lambda data: data.get("production"),
    ),
    GreenlogySensorEntityDescription(
        key="last_invoicing",
        translation_key="last_invoicing",
        name="Posledná fakturácia",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-clock",
        value_fn=lambda data: _parse_timestamp(data.get("last_invoicing")),
    ),
    GreenlogySensorEntityDescription(
        key="last_update",
        translation_key="last_update",
        name="Posledná aktualizácia",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check-outline",
        value_fn=lambda data: _parse_timestamp(data.get("time")),
    ),
    GreenlogySensorEntityDescription(
        key="sync_status",
        translation_key="sync_status",
        name="Stav synchronizácie",
        icon="mdi:cloud-sync",
        value_fn=_calc_sync_status,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreenlogyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Vytvorenie senzorov z config entry."""
    coordinator = entry.runtime_data

    entities: list[GreenlogySensor] = [
        GreenlogySensor(coordinator, service_id, description)
        for service_id in coordinator.data
        for description in SENSORS
    ]

    async_add_entities(entities)


class GreenlogySensor(
    CoordinatorEntity[GreenlogyDataUpdateCoordinator], SensorEntity
):
    """Reprezentácia jedného Greenlogy senzora."""

    entity_description: GreenlogySensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GreenlogyDataUpdateCoordinator,
        service_id: str,
        description: GreenlogySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._service_id = service_id

        service_data = coordinator.data.get(service_id, {})
        product_name = service_data.get("name", "Virtuálna batéria")

        self._attr_unique_id = f"{service_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, service_id)},
            name=f"Greenlogy {product_name}",
            manufacturer="Greenlogy",
            model=product_name,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> Any:
        service_data = self.coordinator.data.get(self._service_id, {})
        return self.entity_description.value_fn(service_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attr_fn is None:
            return None
        service_data = self.coordinator.data.get(self._service_id, {})
        return self.entity_description.attr_fn(service_data)
