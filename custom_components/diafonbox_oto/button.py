"""Button platform for DiafonBox Oto - Inching door control."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
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
    """Set up Multitek button entities."""
    coordinator: MultitekDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    
    locations = coordinator.data.get("locations", [])
    _LOGGER.info("Setting up button entities for %d locations", len(locations))
    
    for location in locations:
        location_id = location.get("location_id")
        location_name = location.get("location_name")
        devices = location.get("location_devices", [])
        
        if devices:
            device = devices[0]
            _LOGGER.info(
                "Creating door open button: %s (SIP: %s)",
                location_name,
                device.get("sip"),
            )
            entities.append(
                MultitekDoorButton(
                    coordinator,
                    location_id,
                    location_name,
                    device,
                )
            )

    _LOGGER.info("Adding %d button entities", len(entities))
    async_add_entities(entities)


class MultitekDoorButton(CoordinatorEntity, ButtonEntity):
    """Button to open door (inching/momentary)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"

    def __init__(
        self,
        coordinator: MultitekDataUpdateCoordinator,
        location_id: str,
        location_name: str,
        device: dict[str, Any],
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        
        self._location_id = location_id
        self._location_name = location_name
        self._device = device
        
        self._attr_name = f"{location_name} Kapıyı Aç"
        self._attr_unique_id = f"{DOMAIN}_{location_id}_door_button"
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, location_id)},
            "name": location_name,
            "manufacturer": "Multitek",
            "model": "DiafonBox",
        }

    async def async_press(self) -> None:
        """Handle button press - open door."""
        device_sip = self._device.get("sip")
        
        _LOGGER.info(
            "=== DOOR OPEN BUTTON PRESSED ===\n"
            "Location: %s\n"
            "SIP: %s\n"
            "Location ID: %s",
            self._location_name,
            device_sip,
            self._location_id,
        )
        
        try:
            # Step 1: Check for active call
            _LOGGER.info("Step 1: Checking for active call...")
            active_call = await self.coordinator.api.ask_current_call()
            
            if active_call:
                call_id = active_call.get("call_id")
                _LOGGER.info("Active call found! call_id: %s", call_id)
                
                success = await self.coordinator.api.open_door_with_call(call_id)
                
                if success:
                    _LOGGER.info("Door opened via controlCurrentCall!")
                    self._fire_event(device_sip, "controlCurrentCall", call_id)
                    return
                else:
                    _LOGGER.warning("controlCurrentCall failed, trying addCall...")
            else:
                _LOGGER.info("No active call, using addCall method...")
            
            # Step 2: Use addCall + setCallDuration
            _LOGGER.info("Step 2: Using addCall + setCallDuration...")
            success = await self.coordinator.api.open_door(
                device_sip=device_sip,
                location_id=self._location_id,
            )
            
            if success:
                _LOGGER.info("Door opened successfully via addCall!")
                self._fire_event(device_sip, "addCall", None)
            else:
                _LOGGER.error("Failed to open door!")
                
        except Exception as err:
            _LOGGER.error("Error opening door: %s", err, exc_info=True)
    
    def _fire_event(self, device_sip: str, method: str, call_id: str | None) -> None:
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
