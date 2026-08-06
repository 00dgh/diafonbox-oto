"""Data update coordinator for DiafonBox Oto."""
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MultitekAPI, MultitekAPIError
from .const import (
    CALL_STATE_MISSED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_DOORBELL_PRESSED,
)
from .pushy_client import PushyClient

_LOGGER = logging.getLogger(__name__)


class MultitekDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Multitek data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: MultitekAPI,
        enable_push: bool = True,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self._last_call_ids: set[str] = set()
        self.pushy_client: PushyClient | None = None
        self._enable_push = enable_push
        self._push_connected = False

    async def async_setup_pushy(self) -> bool:
        """Setup Pushy push notifications.
        
        Returns:
            True if Pushy was setup successfully, False otherwise
        """
        if not self._enable_push:
            _LOGGER.info("Push notifications disabled, using polling only")
            return False
        
        try:
            # Get Pushy credentials
            credentials = await self.api.get_pushy_credentials()
            if not credentials:
                _LOGGER.warning("Could not get Pushy credentials, using polling only")
                return False
            
            token, auth = credentials
            
            # Create Pushy client
            self.pushy_client = PushyClient(
                token=token,
                auth=auth,
                session=self.api.session,
                callback=self._handle_push_notification,
            )
            
            # Get location info for topics
            locations = await self.api.get_locations()
            if not locations:
                _LOGGER.warning("No locations found, cannot subscribe to topics")
                return False
            
            # Build topic list matching Proxyman format
            topics = []
            for location in locations:
                location_id = location.get("location_id")
                rooms = location.get("location_rooms", [])
                
                # Location topic (apartman zili)
                topics.append(f"{location_id}_LOCATION_TOPIC")
                
                # Room topics (daire zilleri)
                for room in rooms:
                    block_num = room.get("block_num", "")
                    room_num = room.get("room_num", "")
                    
                    if block_num and room_num:
                        # Room topic: {location_id}{block}{room}_ROOM_TOPIC
                        topics.append(f"{location_id}{block_num}{room_num}_ROOM_TOPIC")
                        
                        # Call update topic: {location_id}{block}{room}_CALL_UPDATE
                        topics.append(f"{location_id}{block_num}{room_num}_CALL_UPDATE")
                        
                        # Block topic: {location_id}{block}_BLOCK_TOPIC
                        topics.append(f"{location_id}{block_num}_BLOCK_TOPIC")
            
            # Add general topic
            topics.append("MULTITEK")
            
            # Remove duplicates
            topics = list(set(topics))
            
            _LOGGER.info("Subscribing to Pushy topics: %s", topics)
            
            # Connect and subscribe
            if await self.pushy_client.connect(topics):
                self._push_connected = True
                _LOGGER.info("Pushy push notifications enabled")
                return True
            else:
                _LOGGER.warning("Failed to connect to Pushy, using polling only")
                return False
                
        except Exception as err:
            _LOGGER.error("Error setting up Pushy: %s", err)
            return False

    async def _handle_push_notification(self, data: dict[str, Any]) -> None:
        """Handle incoming push notification.
        
        Args:
            data: Push notification data
        """
        _LOGGER.info("Received push notification: %s", data)
        
        # Fire doorbell event immediately
        self.hass.bus.fire(
            EVENT_DOORBELL_PRESSED,
            {
                "notification": data,
                "source": "pushy",
            },
        )
        
        # Trigger immediate data refresh
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Shutdown coordinator and cleanup."""
        if self.pushy_client:
            await self.pushy_client.disconnect()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API."""
        try:
            # Get locations and devices
            locations = await self.api.get_locations()
            _LOGGER.debug("Fetched %d locations", len(locations))
            
            # Get call records
            call_records = await self.api.get_call_records()
            _LOGGER.debug("Fetched %d call records", len(call_records))
            
            # Detect new doorbell rings
            self._detect_doorbell_events(call_records)
            
            # Get account info
            account = await self.api.get_account()
            _LOGGER.debug("Account SIP: %s", account.get("sip"))

            data = {
                "locations": locations,
                "call_records": call_records,
                "account": account,
            }
            
            # Log data structure for debugging
            _LOGGER.info(
                "Data update complete - Locations: %d, Calls: %d",
                len(locations),
                len(call_records),
            )
            
            return data

        except MultitekAPIError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    def _detect_doorbell_events(self, call_records: list[dict[str, Any]]) -> None:
        """Detect new doorbell rings and fire events."""
        for call in call_records:
            call_id = call.get("call_id")
            call_state = call.get("call_state")
            
            # Only process missed calls (doorbell rings)
            if call_state != CALL_STATE_MISSED:
                continue
            
            # Skip if we've already processed this call
            if call_id in self._last_call_ids:
                continue
            
            # Add to processed calls
            self._last_call_ids.add(call_id)
            
            # Fire doorbell event
            event_data = {
                "call_id": call_id,
                "call_from": call.get("call_from"),
                "call_to": call.get("call_to"),
                "location_id": call.get("location_id"),
                "timestamp": call.get("date"),
                "snapshot_path": call.get("path"),
            }
            
            self.hass.bus.fire(EVENT_DOORBELL_PRESSED, event_data)
            
            _LOGGER.info(
                "Doorbell pressed: from=%s to=%s",
                call.get("call_from"),
                call.get("call_to"),
            )

    def get_device_by_location(self, location_id: str) -> dict[str, Any] | None:
        """Get device for a location."""
        if not self.data:
            return None
        
        for location in self.data.get("locations", []):
            if location.get("location_id") == location_id:
                devices = location.get("location_devices", [])
                if devices:
                    return devices[0]  # Return first device
        
        return None

    def get_recent_calls(
        self,
        call_to: str | None = None,
        minutes: int = 1,
    ) -> list[dict[str, Any]]:
        """Get recent calls within specified minutes."""
        if not self.data:
            return []
        
        import time
        current_time = int(time.time() * 1000)
        cutoff_time = current_time - (minutes * 60 * 1000)
        
        recent_calls = []
        for call in self.data.get("call_records", []):
            call_date = int(call.get("date", 0))
            
            if call_date < cutoff_time:
                continue
            
            if call_to and call.get("call_to") != call_to:
                continue
            
            recent_calls.append(call)
        
        return recent_calls

    def get_today_call_count(self) -> int:
        """Get number of calls today."""
        if not self.data:
            return 0
        
        import time
        from datetime import datetime
        
        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp() * 1000
        
        count = 0
        for call in self.data.get("call_records", []):
            call_date = int(call.get("date", 0))
            if call_date >= today_start:
                count += 1
        
        return count
