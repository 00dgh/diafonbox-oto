"""Camera platform for DiafonBox Oto."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_LOCATION_ID, CALL_STATE_MISSED, DOMAIN
from .coordinator import MultitekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Multitek camera entities."""
    coordinator: MultitekDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    
    # Create a camera entity for each location
    for location in coordinator.data.get("locations", []):
        location_id = location.get("location_id")
        location_name = location.get("location_name")
        
        entities.append(
            MultitekCamera(
                coordinator,
                location_id,
                location_name,
            )
        )

    async_add_entities(entities)


class MultitekCamera(CoordinatorEntity, Camera):
    """Representation of a Multitek camera showing last doorbell snapshot."""

    def __init__(
        self,
        coordinator: MultitekDataUpdateCoordinator,
        location_id: str,
        location_name: str,
    ) -> None:
        """Initialize the camera."""
        super().__init__(coordinator)
        Camera.__init__(self)
        
        self._location_id = location_id
        self._location_name = location_name
        self._attr_name = f"{location_name} Son Zil Görüntüsü"
        self._attr_unique_id = f"{DOMAIN}_{location_id}_camera"
        self._last_image: bytes | None = None
        
        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, location_id)},
            "name": location_name,
            "manufacturer": "Multitek",
            "model": "DiafonBox",
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {
            ATTR_LOCATION_ID: self._location_id,
        }
        
        last_call = self._get_last_snapshot_call()
        if last_call:
            attrs["last_snapshot_time"] = last_call.get("date")
            attrs["call_from"] = last_call.get("call_from")
            attrs["call_to"] = last_call.get("call_to")
        
        return attrs

    def _get_last_snapshot_call(self) -> dict[str, Any] | None:
        """Get the most recent call with a snapshot."""
        if not self.coordinator.data:
            return None
        
        calls_with_snapshots = []
        
        for call in self.coordinator.data.get("call_records", []):
            if (
                call.get("call_state") == CALL_STATE_MISSED
                and call.get("location_id") == self._location_id
                and call.get("path")  # Has snapshot
            ):
                calls_with_snapshots.append(call)
        
        # Sort by date and return most recent
        if calls_with_snapshots:
            calls_with_snapshots.sort(
                key=lambda x: int(x.get("date", 0)),
                reverse=True,
            )
            return calls_with_snapshots[0]
        
        return None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return image response."""
        last_call = self._get_last_snapshot_call()
        
        if not last_call:
            return self._last_image
        
        snapshot_path = last_call.get("path")
        if not snapshot_path:
            return self._last_image
        
        # Try to fetch image from API
        # Note: The path is on the server, we need to construct the URL
        # Format: /tmp/MULTITEK_CALL_IMAGES/location_id/room/filename.jpeg
        
        try:
            # Extract filename from path
            import os
            filename = os.path.basename(snapshot_path)
            
            # Construct URL (this is a guess, might need adjustment)
            # The actual URL format needs to be determined from the API
            image_url = f"https://cloud.multitek.com.tr:8096{snapshot_path}"
            
            # Fetch image
            async with self.coordinator.api.session.get(
                image_url,
                auth=self.coordinator.api.auth,
            ) as response:
                if response.status == 200:
                    self._last_image = await response.read()
                    return self._last_image
                else:
                    _LOGGER.warning(
                        "Failed to fetch snapshot: %s (status: %d)",
                        snapshot_path,
                        response.status,
                    )
                    
        except Exception as err:
            _LOGGER.error("Error fetching camera image: %s", err)
        
        return self._last_image
