"""Sensor platform for DiafonBox Oto."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_LOCATION_ID, ATTR_TODAY_COUNT, DOMAIN
from .coordinator import MultitekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Multitek sensor entities."""
    coordinator: MultitekDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    
    # Create sensors for each location
    for location in coordinator.data.get("locations", []):
        location_id = location.get("location_id")
        location_name = location.get("location_name")
        
        # Last ring time sensor
        entities.append(
            MultitekLastRingSensor(
                coordinator,
                location_id,
                location_name,
            )
        )
        
        # Today's ring count sensor
        entities.append(
            MultitekTodayCountSensor(
                coordinator,
                location_id,
                location_name,
            )
        )
        
        # Total calls sensor
        entities.append(
            MultitekTotalCallsSensor(
                coordinator,
                location_id,
                location_name,
            )
        )

    async_add_entities(entities)


class MultitekLastRingSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing last doorbell ring time."""

    _attr_icon = "mdi:bell-ring"

    def __init__(
        self,
        coordinator: MultitekDataUpdateCoordinator,
        location_id: str,
        location_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        
        self._location_id = location_id
        self._attr_name = f"{location_name} Son Zil Zamanı"
        self._attr_unique_id = f"{DOMAIN}_{location_id}_last_ring"
        
        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, location_id)},
            "name": location_name,
            "manufacturer": "Multitek",
            "model": "DiafonBox",
        }

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        
        # Find most recent missed call
        calls = self.coordinator.data.get("call_records", [])
        missed_calls = [
            c for c in calls
            if c.get("call_state") == "Missed"
            and c.get("location_id") == self._location_id
        ]
        
        if not missed_calls:
            return None
        
        # Sort by date
        missed_calls.sort(key=lambda x: int(x.get("date", 0)), reverse=True)
        last_call = missed_calls[0]
        
        # Convert timestamp to datetime
        timestamp = int(last_call.get("date", 0)) / 1000
        dt = datetime.fromtimestamp(timestamp)
        
        return dt.isoformat()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {
            ATTR_LOCATION_ID: self._location_id,
        }


class MultitekTodayCountSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing today's doorbell ring count."""

    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "zil"

    def __init__(
        self,
        coordinator: MultitekDataUpdateCoordinator,
        location_id: str,
        location_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        
        self._location_id = location_id
        self._attr_name = f"{location_name} Bugün Zil Sayısı"
        self._attr_unique_id = f"{DOMAIN}_{location_id}_today_count"
        
        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, location_id)},
            "name": location_name,
            "manufacturer": "Multitek",
            "model": "DiafonBox",
        }

    @property
    def native_value(self) -> int:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return 0
        
        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp() * 1000
        
        count = 0
        for call in self.coordinator.data.get("call_records", []):
            if (
                call.get("call_state") == "Missed"
                and call.get("location_id") == self._location_id
                and int(call.get("date", 0)) >= today_start
            ):
                count += 1
        
        return count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {
            ATTR_LOCATION_ID: self._location_id,
            ATTR_TODAY_COUNT: self.native_value,
        }


class MultitekTotalCallsSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing total call count."""

    _attr_icon = "mdi:phone-log"
    _attr_native_unit_of_measurement = "arama"

    def __init__(
        self,
        coordinator: MultitekDataUpdateCoordinator,
        location_id: str,
        location_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        
        self._location_id = location_id
        self._attr_name = f"{location_name} Toplam Arama"
        self._attr_unique_id = f"{DOMAIN}_{location_id}_total_calls"
        
        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, location_id)},
            "name": location_name,
            "manufacturer": "Multitek",
            "model": "DiafonBox",
        }

    @property
    def native_value(self) -> int:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return 0
        
        count = 0
        for call in self.coordinator.data.get("call_records", []):
            if call.get("location_id") == self._location_id:
                count += 1
        
        return count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {
            ATTR_LOCATION_ID: self._location_id,
        }
