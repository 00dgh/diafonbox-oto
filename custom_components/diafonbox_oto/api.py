"""API Client for Multitek DiafonBox."""
import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import BasicAuth

from .const import (
    API_BASE_URL,
    API_PASSWORD,
    API_USERNAME,
    ENDPOINT_ADD_CALL,
    ENDPOINT_ASK_CURRENT_CALL,
    ENDPOINT_CONTROL_CURRENT_CALL,
    ENDPOINT_GET_ACCOUNT,
    ENDPOINT_GET_CALLS,
    ENDPOINT_GET_LOCATIONS,
    ENDPOINT_LOGIN,
    ENDPOINT_RESUME_APP,
    ENDPOINT_SET_CALL_DURATION,
)

_LOGGER = logging.getLogger(__name__)


class MultitekAPIError(Exception):
    """Exception for Multitek API errors."""


class MultitekAuthError(MultitekAPIError):
    """Exception for authentication errors."""


def build_headers() -> dict[str, str]:
    """Return the request headers the cloud API expects.

    The upstream project found these by proxying the iOS app; the API rejects
    requests that do not look like the app, so keep them in one place.
    """
    return {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Accept-Language": "tr-TR;q=1.0, en-TR;q=0.9",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "User-Agent": (
            "Multitek Cloud/1.3.47 (com.multitek.MultitekCloud; build:1; "
            "iOS 26.2.1) Alamofire/5.9.1"
        ),
    }


@dataclass
class RawResponse:
    """Outcome of a probe request, including failures."""

    endpoint: str
    status: int
    text: str
    json: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return True when the server answered with 200."""
        return self.status == 200 and self.error is None


async def raw_post(
    session: aiohttp.ClientSession,
    endpoint: str,
    payload: dict[str, Any],
    timeout: int = 20,
) -> RawResponse:
    """POST without raising, so discovery can mine failures as well as successes."""
    url = f"{API_BASE_URL}/{endpoint}"
    try:
        async with session.post(
            url,
            json=payload,
            auth=BasicAuth(API_USERNAME, API_PASSWORD),
            headers=build_headers(),
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            text = await response.text()
            parsed: Any = None
            try:
                parsed = await response.json(content_type=None)
            except Exception:  # noqa: BLE001 - body may be plain text like "1"
                parsed = None
            return RawResponse(
                endpoint=endpoint,
                status=response.status,
                text=text,
                json=parsed,
            )
    except Exception as err:  # noqa: BLE001 - network errors are data here
        return RawResponse(endpoint=endpoint, status=0, text="", error=str(err))


class MultitekAPI:
    """API client for Multitek DiafonBox."""

    def __init__(
        self,
        email: str,
        password: str,
        phone_id: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the API client."""
        self.email = email
        self.password_hash = hashlib.md5(password.encode()).hexdigest()
        self.phone_id = phone_id
        self.session = session
        self.auth = BasicAuth(API_USERNAME, API_PASSWORD)
        self._user_sip: str | None = None

    async def _request(
        self,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """Make API request."""
        url = f"{API_BASE_URL}/{endpoint}"
        
        if data is None:
            data = {}
        
        # Add common fields
        data.setdefault("email", self.email)
        data.setdefault("phone_id", self.phone_id)
        data.setdefault("language", "tr-TR")

        # Headers matching Proxyman (critical for API to work!)
        headers = build_headers()

        try:
            _LOGGER.debug("API Request: %s - Data: %s", endpoint, data)
            
            async with self.session.post(
                url,
                json=data,
                auth=self.auth,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 401:
                    raise MultitekAuthError("Authentication failed")
                
                if response.status != 200:
                    raise MultitekAPIError(
                        f"API request failed with status {response.status}"
                    )

                content_type = response.headers.get("Content-Type", "")
                
                if "application/json" in content_type:
                    return await response.json()
                else:
                    # Some endpoints return plain text (e.g., "1")
                    text = await response.text()
                    return text

        except aiohttp.ClientError as err:
            raise MultitekAPIError(f"API request failed: {err}") from err

    async def login(self) -> bool:
        """Test login credentials."""
        try:
            # For invited users, userAccountControl returns "0"
            # Instead, we validate by trying to get account info
            # If it succeeds, the credentials are valid
            
            _LOGGER.debug("Attempting login for email: %s", self.email)
            
            try:
                account = await self.get_account()
                
                if account and "email" in account:
                    _LOGGER.info("Login successful for %s (invited user)", self.email)
                    self._user_sip = account.get("sip")
                    return True
                else:
                    _LOGGER.warning("Login failed for %s - Invalid response", self.email)
                    return False
                    
            except MultitekAPIError as err:
                _LOGGER.error("Login failed for %s: %s", self.email, err)
                return False

        except Exception as err:
            _LOGGER.error("Unexpected error during login: %s", err)
            return False

    async def get_account(self) -> dict[str, Any]:
        """Get user account information."""
        return await self._request(ENDPOINT_GET_ACCOUNT)

    async def get_pushy_credentials(self) -> tuple[str, str] | None:
        """Get Pushy token and auth from account info.
        
        Returns:
            Tuple of (token, auth) or None if not found
        """
        account = await self.get_account()
        phone_list = account.get("phone_list", [])
        
        if not phone_list:
            return None
        
        # Get token from first phone
        token = phone_list[0].get("token")
        
        if not token:
            return None
        
        # Auth key is hardcoded for now
        # TODO: Find where this comes from in the API
        auth = "401c2fe6e2730dd87b2c12c8afe36c11499f7141e9296f3c2cd03bb33a1b3992"
        
        return (token, auth)

    async def get_locations(self) -> list[dict[str, Any]]:
        """Get user locations and devices."""
        result = await self._request(ENDPOINT_GET_LOCATIONS)
        return result if isinstance(result, list) else []

    async def get_call_records(self) -> list[dict[str, Any]]:
        """Get call history records."""
        result = await self._request(ENDPOINT_GET_CALLS)
        return result if isinstance(result, list) else []

    async def ask_current_call(self) -> dict[str, Any] | None:
        """Ask for current active call.
        
        Returns:
            Call info dict if there's an active call, None otherwise.
            If call_id is "-1", there's no active call.
        """
        try:
            result = await self._request(ENDPOINT_ASK_CURRENT_CALL)
            
            if isinstance(result, dict):
                call_id = result.get("call_id", "-1")
                if call_id != "-1" and call_id:
                    _LOGGER.info("Active call found: %s", call_id)
                    return result
            
            return None
        except Exception as err:
            _LOGGER.debug("No active call: %s", err)
            return None

    async def open_door(self, device_sip: str, location_id: str) -> bool:
        """Open door by initiating a call.
        
        This uses the two-step process:
        1. addCall - Create an outgoing call record
        2. setCallDuration - Set duration to 6 seconds (triggers door unlock)
        
        This works without requiring an active doorbell ring.
        """
        try:
            if not self._user_sip:
                account = await self.get_account()
                self._user_sip = account.get("sip")

            if not self._user_sip:
                _LOGGER.error("User SIP number not available")
                raise MultitekAPIError("User SIP number not available")

            import time
            import uuid

            call_id = uuid.uuid4().hex  # 32 characters
            
            data = {
                "call_model": {
                    "call_id": call_id,
                    "call_from": self._user_sip,
                    "call_to": device_sip,
                    "date": str(int(time.time() * 1000)),
                    "call_state": "Outgoing",
                    "data": "New call",
                    "path": "",
                    "location_id": location_id,
                    "duration": "0",
                    "notification_id": 0,
                    "extra_data": "",
                    "call_type": "DEVICE_TYPE_GATEWAY_DOOR",
                    "selected": False,
                    "isRead": False,
                }
            }

            _LOGGER.info(
                "Opening door - From: %s, To: %s, Location: %s, call_id: %s",
                self._user_sip,
                device_sip,
                location_id,
                call_id,
            )

            # Step 1: Create call
            _LOGGER.info("Step 1: Calling addCall API...")
            result = await self._request(ENDPOINT_ADD_CALL, data)
            
            _LOGGER.info("addCall API response: %s (type: %s)", result, type(result))
            
            # Response is "1" for success
            success = result == "1" or result == 1
            
            if not success:
                _LOGGER.error("addCall failed - API returned: %s", result)
                return False
            
            # Step 2: Set call duration (this actually opens the door!)
            duration_data = {
                "call_id": call_id,
                "call_duration": "6",  # 6 seconds, same as app
            }
            
            _LOGGER.info("Step 2: Calling setCallDuration API for call_id: %s", call_id)
            
            duration_result = await self._request(ENDPOINT_SET_CALL_DURATION, duration_data)
            
            _LOGGER.info("setCallDuration API response: %s (type: %s)", duration_result, type(duration_result))
            
            duration_success = duration_result == "1" or duration_result == 1
            
            if not duration_success:
                _LOGGER.error(
                    "setCallDuration failed - call_id: %s, response: %s",
                    call_id,
                    duration_result,
                )
                return False
            
            _LOGGER.info("Door opened successfully with call_id: %s!", call_id)
            return True
            
        except MultitekAPIError:
            raise
        except Exception as err:
            _LOGGER.error("Exception in open_door: %s", err, exc_info=True)
            return False

    async def open_door_with_call(self, call_id: str) -> bool:
        """Open door using active call ID.
        
        This is the preferred method as it uses the controlCurrentCall endpoint
        which directly opens the door for an active call.
        
        Args:
            call_id: Active call ID from push notification or recent call records
        """
        data = {
            "call_id": call_id,
            "phone_id": self.phone_id,
            "language": "tr-TR",
            "email": self.email,
        }
        
        _LOGGER.info("Opening door with call_id: %s", call_id)
        
        result = await self._request(ENDPOINT_CONTROL_CURRENT_CALL, data)
        
        _LOGGER.info("Control current call response: %s (type: %s)", result, type(result))
        
        # Response is "1" for success
        success = result == "1" or result == 1
        
        if not success:
            _LOGGER.warning("Door open with call failed - API returned: %s", result)
        
        return success

    async def resume_app(self) -> dict[str, Any]:
        """Resume app session."""
        data = {
            "phoneInfo": "Home Assistant",
            "phoneOS": "Linux",
            "appVersion": "Home Assistant Integration v1.0.0",
            "locationLat": -1,
            "locationLong": -1,
            "locationCountry": "",
            "locationCity": "",
            "locationDistrict": "",
            "locationFindType": "",
            "locationLastUpdateTime": str(int(asyncio.get_event_loop().time() * 1000)),
            "pushyToken": "",
            "pushKitToken": "",
        }
        
        return await self._request(ENDPOINT_RESUME_APP, data)
