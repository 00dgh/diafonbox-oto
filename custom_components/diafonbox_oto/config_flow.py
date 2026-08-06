"""Config flow for DiafonBox Oto.

The user supplies an e-mail address; the phone_id is discovered automatically
(see discovery.py). Manual entry survives as a fallback for the case where
discovery comes up empty.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MultitekAPI, MultitekAPIError, MultitekAuthError
from .const import CONF_PHONE_ID, DOMAIN
from .discovery import DiscoveryResult, PhoneIdCandidate, async_discover_phone_id

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str})

# How much of the discovery trail to surface in the UI. The whole thing goes to
# the log; the form only needs enough to act on.
REPORT_TAIL_LINES = 12


async def validate_input(
    hass: HomeAssistant, email: str, phone_id: str
) -> dict[str, Any]:
    """Confirm the credentials work and derive a title for the entry."""
    session = async_get_clientsession(hass)

    api = MultitekAPI(
        email=email,
        password="",  # Not needed for invited users
        phone_id=phone_id,
        session=session,
    )

    if not await api.login():
        raise MultitekAuthError("Invalid email or phone_id")

    account = await api.get_account()
    title = " ".join(
        part
        for part in (account.get("user_name", ""), account.get("user_surname", ""))
        if part
    ).strip()

    return {"title": title or email, "phone_id": phone_id}


class DiafonBoxOtoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DiafonBox Oto."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise per-flow state."""
        self._email: str = ""
        self._candidates: list[PhoneIdCandidate] = []
        self._report: str = ""

    # -- helpers ------------------------------------------------------------

    def _report_tail(self) -> str:
        """Return the last few report lines for display in a form."""
        lines = self._report.splitlines()
        return "\n".join(lines[-REPORT_TAIL_LINES:])

    async def _async_finish(self, phone_id: str) -> FlowResult:
        """Validate a phone_id and create the entry, or fall back to manual."""
        try:
            info = await validate_input(self.hass, self._email, phone_id)
        except MultitekAuthError:
            return await self.async_step_manual(errors={"base": "invalid_auth"})
        except MultitekAPIError:
            return await self.async_step_manual(errors={"base": "cannot_connect"})
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error validating discovered phone_id")
            return await self.async_step_manual(errors={"base": "unknown"})

        await self.async_set_unique_id(self._email.lower())
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=info["title"],
            data={CONF_EMAIL: self._email, CONF_PHONE_ID: info["phone_id"]},
        )

    # -- steps --------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for the e-mail address, then discover phone_id automatically."""
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()

            session = async_get_clientsession(self.hass)
            try:
                result: DiscoveryResult = await async_discover_phone_id(
                    session, self._email
                )
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("phone_id discovery crashed")
                self._report = "Discovery raised an exception; see the log."
                return await self.async_step_manual(errors={"base": "discovery_failed"})

            self._report = result.format_report()
            self._candidates = result.candidates
            _LOGGER.info("phone_id discovery report:\n%s", self._report)

            verified = result.verified
            if len(verified) == 1:
                return await self._async_finish(verified[0].value)
            if verified:
                self._candidates = verified
                return await self.async_step_pick()
            if len(self._candidates) == 1:
                return await self._async_finish(self._candidates[0].value)
            if self._candidates:
                return await self.async_step_pick()

            return await self.async_step_manual(errors={"base": "no_candidates"})

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA
        )

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user choose when discovery found more than one phone."""
        if user_input is not None:
            return await self._async_finish(user_input[CONF_PHONE_ID])

        options = {c.value: c.display for c in self._candidates}

        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PHONE_ID, default=next(iter(options))
                    ): vol.In(options)
                }
            ),
            description_placeholders={"report": self._report_tail()},
        )

    async def async_step_manual(
        self,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        """Fallback: type the phone_id in by hand, as upstream required."""
        if user_input is not None:
            return await self._async_finish(user_input[CONF_PHONE_ID].strip())

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_PHONE_ID): str}),
            errors=errors or {},
            description_placeholders={"report": self._report_tail() or "-"},
        )
