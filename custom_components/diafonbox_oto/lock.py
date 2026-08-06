"""Lock platform for DiafonBox Oto."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DEVICE_MAC,
    ATTR_DEVICE_SIP,
    ATTR_LOCATION_ID,
    ATTR_LOCATION_NAME,
    DOMAIN,
    EVENT_DOOR_OPENED,
)
from .coordinator import MultitekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Multitek lock entities."""
    coordinator: MultitekDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    
    locations = coordinator.data.get("locations", [])
    _LOGGER.info("Setting up lock entities for %d locations", len(locations))
    
    # Create a lock entity for each location
    for location in locations:
        location_id = location.get("location_id")
        location_name = location.get("location_name")
        devices = location.get("location_devices", [])
        
        _LOGGER.debug(
            "Location: %s (%s) - Devices: %d",
            location_name,
            location_id,
            len(devices),
        )
        
        if devices:
            device = devices[0]  # Use first device
            _LOGGER.info(
                "Creating lock entity: %s (SIP: %s)",
                location_name,
                device.get("sip"),
            )
            entities.append(
                MultitekLock(
                    coordinator,
                    location_id,
                    location_name,
                    device,
                )
            )

    _LOGGER.info("Adding %d lock entities", len(entities))
    async_add_entities(entities)


class MultitekLock(CoordinatorEntity, LockEntity):
    """Representation of a Multitek door lock."""

    def __init__(
        self,
        coordinator: MultitekDataUpdateCoordinator,
        location_id: str,
        location_name: str,
        device: dict[str, Any],
    ) -> None:
        """Initialize the lock."""
        super().__init__(coordinator)
        
        self._location_id = location_id
        self._location_name = location_name
        self._device = device
        self._attr_name = f"{location_name} Kapı"
        self._attr_unique_id = f"{DOMAIN}_{location_id}_lock"
        
        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, location_id)},
            "name": location_name,
            "manufacturer": "Multitek",
            "model": "DiafonBox",
            "sw_version": device.get("version", "1.0"),
        }

    @property
    def is_locked(self) -> bool:
        """Return true if lock is locked."""
        # Door is always locked (can only be unlocked momentarily)
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {
            ATTR_LOCATION_ID: self._location_id,
            ATTR_LOCATION_NAME: self._location_name,
            ATTR_DEVICE_MAC: self._device.get("mac"),
            ATTR_DEVICE_SIP: self._device.get("sip"),
        }

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the door."""
        device_sip = self._device.get("sip")
        
        _LOGGER.info(
            "Unlocking door: %s (SIP: %s, Location: %s)",
            self._location_name,
            device_sip,
            self._location_id,
        )
        
        try:
            # Step 1: Check for active call using askCurrentCall
            _LOGGER.info("Step 1: Checking for active call...")
            active_call = await self.coordinator.api.ask_current_call()
            
            if active_call:
                # There's an active call, use controlCurrentCall
                call_id = active_call.get("call_id")
                _LOGGER.info("Active call found! Using controlCurrentCall with call_id: %s", call_id)
                
                success = await self.coordinator.api.open_door_with_call(call_id)
                
                if success:
                    _LOGGER.info("Door opened successfully via active call: %s", call_id)
                    self._fire_door_opened_event(device_sip, "controlCurrentCall", call_id)
                    await self.coordinator.async_request_refresh()
                    return
                else:
                    _LOGGER.warning("controlCurrentCall failed, trying addCall method...")
            
            # Step 2: No active call or controlCurrentCall failed
            # Use addCall + setCallDuration method
            _LOGGER.info("Step 2: Using addCall + setCallDuration method...")
            success = await self.coordinator.api.open_door(
                device_sip=device_sip,
                location_id=self._location_id,
            )
            
            if success:
                _LOGGER.info("Door opened successfully via addCall: %s", self._location_name)
                self._fire_door_opened_event(device_sip, "addCall", None)
                await self.coordinator.async_request_refresh()
            else:
                _LOGGER.error("Failed to open door: %s", self._location_name)
                
        except Exception as err:
            _LOGGER.error("Error opening door %s: %s", self._location_name, err, exc_info=True)
    
    def _fire_door_opened_event(self, device_sip: str, method: str, call_id: str | None) -> None:
        """Fire door opened event."""
        self.hass.bus.fire(
            EVENT_DOOR_OPENED,
            {
                ATTR_LOCATION_ID: self._location_id,
                ATTR_LOCATION_NAME: self._location_name,
                ATTR_DEVICE_SIP: device_sip,
                "method": method,
                "call_id": call_id,
            },
        )

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the door (not supported)."""
        # Door locks automatically, no action needed
        _LOGGER.debug("Lock action not supported (door auto-locks)")
