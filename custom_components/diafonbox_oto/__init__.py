"""The DiafonBox Oto integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MultitekAPI
from .const import CONF_PHONE_ID, DOMAIN
from .coordinator import MultitekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LOCK,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.CAMERA,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DiafonBox Oto from a config entry."""
    email = entry.data[CONF_EMAIL]
    phone_id = entry.data[CONF_PHONE_ID]

    _LOGGER.info("Setting up DiafonBox Oto integration for %s", email)

    session = async_get_clientsession(hass)
    api = MultitekAPI(
        email=email,
        password="",  # Not needed for invited users
        phone_id=phone_id,
        session=session,
    )


    # Test login
    if not await api.login():
        _LOGGER.error("Failed to authenticate with Multitek API")
        return False

    _LOGGER.info("Authentication successful")

    # Create coordinator
    coordinator = MultitekDataUpdateCoordinator(hass, api)

    # Fetch initial data
    _LOGGER.info("Fetching initial data...")
    await coordinator.async_config_entry_first_refresh()
    
    # Log data availability
    if coordinator.data:
        locations = coordinator.data.get("locations", [])
        _LOGGER.info(
            "Initial data loaded - Locations: %d, Coordinator data keys: %s",
            len(locations),
            list(coordinator.data.keys()),
        )
    else:
        _LOGGER.error("Coordinator data is empty!")
    
    # Setup Pushy push notifications (optional, falls back to polling)
    await coordinator.async_setup_pushy()

    # Store coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    _LOGGER.info("Forwarding setup to platforms...")
    
    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    _LOGGER.info("Platform setup complete")
    
    # Register open_door service
    async def async_open_door(call):
        """Open door service handler."""
        location_id = call.data.get("location_id")
        _LOGGER.info("=== OPEN DOOR SERVICE CALLED === location_id: %s", location_id)
        
        # Get first location if not specified
        if not location_id:
            locations = coordinator.data.get("locations", [])
            if locations:
                location_id = locations[0].get("location_id")
                device_sip = locations[0].get("location_devices", [{}])[0].get("sip")
            else:
                _LOGGER.error("No locations found!")
                return
        else:
            # Find device SIP for this location
            locations = coordinator.data.get("locations", [])
            device_sip = None
            for loc in locations:
                if loc.get("location_id") == location_id:
                    devices = loc.get("location_devices", [])
                    if devices:
                        device_sip = devices[0].get("sip")
                    break
        
        if not device_sip:
            _LOGGER.error("Device SIP not found!")
            return
        
        _LOGGER.info("Opening door - Location: %s, SIP: %s", location_id, device_sip)
        
        try:
            success = await coordinator.api.open_door(
                device_sip=device_sip,
                location_id=location_id,
            )
            if success:
                _LOGGER.info("Door opened successfully!")
            else:
                _LOGGER.error("Failed to open door!")
        except Exception as err:
            _LOGGER.error("Error opening door: %s", err, exc_info=True)
    
    hass.services.async_register(DOMAIN, "open_door", async_open_door)
    _LOGGER.info("Registered open_door service")
    
    # Register shutdown handler
    async def async_shutdown(event):
        """Handle shutdown."""
        await coordinator.async_shutdown()
    
    entry.async_on_unload(
        hass.bus.async_listen_once("homeassistant_stop", async_shutdown)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Shutdown coordinator
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_shutdown()
    
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

