"""Binary sensor platform for DiafonBox Oto."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_LAST_RING_TIME,
    ATTR_LOCATION_ID,
    ATTR_SNAPSHOT_URL,
    CALL_STATE_MISSED,
    DOMAIN,
)
from .coordinator import MultitekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Multitek binary sensor entities."""
    coordinator: MultitekDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    
    locations = coordinator.data.get("locations", [])
    _LOGGER.info("Setting up binary sensors for %d locations", len(locations))
    
    # Create doorbell sensors for each location
    for location in locations:
        location_id = location.get("location_id")
        location_name = location.get("location_name")
        
        # Get room info
        rooms = location.get("location_rooms", [])
        
        _LOGGER.debug(
            "Location: %s (%s) - Rooms: %d",
            location_name,
            location_id,
            len(rooms),
        )
        
        # Apartment entrance doorbell
        _LOGGER.info("Creating apartment doorbell sensor: %s", location_name)
        entities.append(
            MultitekDoorbellSensor(
                coordinator,
                location_id,
                location_name,
                "apartman",
                None,  # Apartment entrance has no specific room
            )
        )
        
        # Room doorbells
        for room in rooms:
            room_number = f"{room.get('block_num')}{room.get('room_num')}"
            if room_number:
                _LOGGER.info(
                    "Creating room doorbell sensor: %s - Room %s",
                    location_name,
                    room_number,
                )
                entities.append(
                    MultitekDoorbellSensor(
                        coordinator,
                        location_id,
                        location_name,
                        "daire",
                        room_number,
                    )
                )

    _LOGGER.info("Adding %d binary sensor entities", len(entities))
    async_add_entities(entities)


class MultitekDoorbellSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Multitek doorbell sensor."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MultitekDataUpdateCoordinator,
        location_id: str,
        location_name: str,
        sensor_type: str,  # "apartman" or "daire"
        room_number: str | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        
        self._location_id = location_id
        self._location_name = location_name
        self._sensor_type = sensor_type
        self._room_number = room_number
        
        if sensor_type == "apartman":
            self._attr_name = f"{location_name} Apartman Zili"
            self._attr_unique_id = f"{DOMAIN}_{location_id}_doorbell_entrance"
        else:
            self._attr_name = f"{location_name} Daire Zili"
            self._attr_unique_id = f"{DOMAIN}_{location_id}_doorbell_apartment"
        
        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, location_id)},
            "name": location_name,
            "manufacturer": "Multitek",
            "model": "DiafonBox",
        }

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def is_on(self) -> bool:
        """Return true if doorbell was pressed recently."""
        if not self.available:
            return False
        # Check for recent calls (within last 30 seconds)
        if self._sensor_type == "apartman":
            # Apartment entrance: calls from device to any room
            recent_calls = self.coordinator.get_recent_calls(minutes=0.5)  # 30 seconds
            for call in recent_calls:
                if (
                    call.get("call_state") == CALL_STATE_MISSED
                    and call.get("location_id") == self._location_id
                    and not call.get("call_to", "").startswith("0")  # Not to a specific room
                ):
                    return True
        else:
            # Apartment door: calls to specific room
            if self._room_number:
                recent_calls = self.coordinator.get_recent_calls(
                    call_to=self._room_number,
                    minutes=0.5,  # 30 seconds
                )
                for call in recent_calls:
                    if call.get("call_state") == CALL_STATE_MISSED:
                        return True
        
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {
            ATTR_LOCATION_ID: self._location_id,
        }
        
        # Get last ring info
        last_call = self._get_last_call()
        if last_call:
            attrs[ATTR_LAST_RING_TIME] = last_call.get("date")
            if last_call.get("path"):
                attrs[ATTR_SNAPSHOT_URL] = last_call.get("path")
        
        return attrs

    def _get_last_call(self) -> dict[str, Any] | None:
        """Get the most recent call for this sensor."""
        if not self.coordinator.data:
            return None
        
        calls = []
        
        if self._sensor_type == "apartman":
            # Get all missed calls for this location
            for call in self.coordinator.data.get("call_records", []):
                if (
                    call.get("call_state") == CALL_STATE_MISSED
                    and call.get("location_id") == self._location_id
                ):
                    calls.append(call)
        else:
            # Get missed calls to specific room
            if self._room_number:
                for call in self.coordinator.data.get("call_records", []):
                    if (
                        call.get("call_state") == CALL_STATE_MISSED
                        and call.get("call_to") == self._room_number
                    ):
                        calls.append(call)
        
        # Sort by date and return most recent
        if calls:
            calls.sort(key=lambda x: int(x.get("date", 0)), reverse=True)
            return calls[0]
        
        return None
