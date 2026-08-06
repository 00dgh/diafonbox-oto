"""Constants for the DiafonBox Oto integration."""
from typing import Final

DOMAIN: Final = "diafonbox_oto"

# API Configuration
API_BASE_URL: Final = "https://cloud.multitek.com.tr:8096/multitek_service/root"
API_USERNAME: Final = "multitek"
API_PASSWORD: Final = "Mlt.3838!"

# API Endpoints
ENDPOINT_LOGIN: Final = "userAccountControl"
ENDPOINT_GET_LOCATIONS: Final = "getUserLocations"
ENDPOINT_GET_CALLS: Final = "getCallAllRecords"
ENDPOINT_ADD_CALL: Final = "addCall"
ENDPOINT_GET_ACCOUNT: Final = "getAccount"
ENDPOINT_RESUME_APP: Final = "resumeApp"
ENDPOINT_ASK_CURRENT_CALL: Final = "askCurrentCall"
ENDPOINT_SET_CALL_DURATION: Final = "setCallDuration"
ENDPOINT_CONTROL_CURRENT_CALL: Final = "controlCurrentCall"

# Configuration
CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"
CONF_PHONE_ID: Final = "phone_id"

# Defaults
DEFAULT_SCAN_INTERVAL: Final = 5  # seconds (reduced for faster doorbell detection)
DEFAULT_PHONE_ID: Final = "home-assistant-integration"

# --- Automatic phone_id discovery -------------------------------------------
# The upstream project required the user to sniff phone_id out of the mobile
# app (Proxyman / adb logcat) or to read it from a failed setup's debug log.
# Discovery probes the cloud API with throwaway phone_id values and mines the
# responses for the real one. Bootstrap values are tried in this order.
BOOTSTRAP_PHONE_IDS: Final = (
    "",
    DEFAULT_PHONE_ID,
    "00000000-0000-0000-0000-000000000000",
)

# Endpoints probed during discovery, most-likely first.
# READ-ONLY ONLY. resumeApp and addCall are deliberately excluded: resumeApp
# re-registers the session's push tokens, so probing it with placeholder values
# would clobber the real phone's notification registration.
DISCOVERY_ENDPOINTS: Final = (
    ENDPOINT_GET_ACCOUNT,
    ENDPOINT_GET_LOCATIONS,
    ENDPOINT_GET_CALLS,
    ENDPOINT_LOGIN,
)

# JSON keys that hold a phone identifier outright.
PHONE_ID_KEYS: Final = ("phone_id", "phoneid", "phoneId", "phoneID", "phone_uuid")

# Keys inside a phone_list entry used to label a candidate for the user.
PHONE_LABEL_KEYS: Final = (
    "phone_name",
    "phone_model",
    "phone_brand",
    "phone_type",
    "phone_os",
    "os",
    "model",
    "name",
    "device_name",
)

# Discovery confidence tiers (higher wins).
CONF_TIER_EXPLICIT_KEY: Final = 100
CONF_TIER_PHONE_LIST: Final = 80
CONF_TIER_UUID_SCAN: Final = 60
CONF_TIER_ERROR_BODY: Final = 40
VERIFIED_BONUS: Final = 1000

# Device Types
DEVICE_TYPE_GATEWAY_DOOR: Final = "DEVICE_TYPE_GATEWAY_DOOR"

# Call States
CALL_STATE_MISSED: Final = "Missed"
CALL_STATE_OUTGOING: Final = "Outgoing"

# Platforms
PLATFORMS: Final = ["lock", "binary_sensor", "camera", "sensor"]

# Events
EVENT_DOORBELL_PRESSED: Final = f"{DOMAIN}_doorbell_pressed"
EVENT_DOOR_OPENED: Final = f"{DOMAIN}_door_opened"

# Attributes
ATTR_LOCATION_ID: Final = "location_id"
ATTR_LOCATION_NAME: Final = "location_name"
ATTR_DEVICE_MAC: Final = "device_mac"
ATTR_DEVICE_SIP: Final = "device_sip"
ATTR_LAST_RING_TIME: Final = "last_ring_time"
ATTR_SNAPSHOT_URL: Final = "snapshot_url"
ATTR_CALL_FROM: Final = "call_from"
ATTR_CALL_TO: Final = "call_to"
ATTR_CALL_DURATION: Final = "call_duration"
ATTR_TODAY_COUNT: Final = "today_count"
