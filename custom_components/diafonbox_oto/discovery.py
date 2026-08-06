"""Automatic phone_id discovery for the Multitek cloud API.

Upstream required the user to obtain ``phone_id`` by hand: proxy the iOS app
with Proxyman, grep ``adb logcat`` on Android, or deliberately fail a setup and
read the value out of the Home Assistant debug log. This module does that work
for them.

The idea is that ``phone_id`` is only an identifier the app sends along; the
account itself is keyed by e-mail. So we call the API with throwaway
``phone_id`` values and mine whatever comes back -- successful bodies *and*
error bodies -- for the real one, then confirm our pick.

Deliberately free of Home Assistant imports so ``tools/discover_phone_id.py``
can run it against a plain Python install.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .api import RawResponse, raw_post
from .const import (
    BOOTSTRAP_PHONE_IDS,
    CONF_TIER_ERROR_BODY,
    CONF_TIER_EXPLICIT_KEY,
    CONF_TIER_PHONE_LIST,
    CONF_TIER_UUID_SCAN,
    DISCOVERY_ENDPOINTS,
    ENDPOINT_GET_ACCOUNT,
    ENDPOINT_GET_LOCATIONS,
    PHONE_ID_KEYS,
    PHONE_LABEL_KEYS,
    VERIFIED_BONUS,
)

_LOGGER = logging.getLogger(__name__)

# The app registers iOS-style upper-case UUIDs, e.g.
# 11111111-2222-3333-4444-555555555555
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

# Upper bound on confirmation requests, so a pathological response body cannot
# turn discovery into a flood of API calls.
MAX_VERIFY = 8

# Identifiers that are shaped like a phone_id but are definitely something
# else. Without this a call_id or a location_id can win the ranking.
DENY_KEYS = frozenset(
    {
        "call_id",
        "location_id",
        "notification_id",
        "room_id",
        "block_id",
        "device_id",
        "user_id",
        "account_id",
        "sip",
        "token",
    }
)


@dataclass
class PhoneIdCandidate:
    """A value that might be the account's phone_id."""

    value: str
    source: str
    tier: int
    label: str = ""
    verified: bool = False

    @property
    def score(self) -> int:
        """Rank candidates; verification dominates the tier."""
        return self.tier + (VERIFIED_BONUS if self.verified else 0)

    @property
    def display(self) -> str:
        """Human readable one-liner for the config-flow picker."""
        bits = [self.value]
        if self.label:
            bits.append(f"({self.label})")
        if self.verified:
            bits.append("✓")
        return " ".join(bits)


@dataclass
class DiscoveryResult:
    """Everything discovery learned, including why it failed."""

    candidates: list[PhoneIdCandidate] = field(default_factory=list)
    report: list[str] = field(default_factory=list)
    server_ignores_phone_id: bool = False
    # Set when the probes let us name the failure instead of guessing.
    diagnosis: str = ""

    @property
    def best(self) -> PhoneIdCandidate | None:
        """Highest ranked candidate, if any."""
        return self.candidates[0] if self.candidates else None

    @property
    def verified(self) -> list[PhoneIdCandidate]:
        """Candidates that produced a usable account response."""
        return [c for c in self.candidates if c.verified]

    def format_report(self) -> str:
        """Render the diagnostic trail as text for logs or the UI."""
        return "\n".join(self.report)


def _looks_like_id_key(key: str) -> bool:
    """Return True for keys that plausibly hold a phone identifier."""
    lowered = key.lower()
    if lowered in DENY_KEYS:
        return False
    return lowered in {"id", "uuid"} or lowered.endswith("_id") or "phone" in lowered


def _label_from(entry: dict[str, Any]) -> str:
    """Build a readable label from a phone_list entry so a human can pick."""
    parts = [
        str(entry[key]).strip()
        for key in PHONE_LABEL_KEYS
        if isinstance(entry.get(key), (str, int)) and str(entry[key]).strip()
    ]
    # Keep it short and free of duplicates while preserving order.
    seen: set[str] = set()
    unique = [p for p in parts if not (p in seen or seen.add(p))]
    return " · ".join(unique[:3])


def _mine(node: Any, source: str, *, in_phone_list: bool = False) -> list[PhoneIdCandidate]:
    """Walk a decoded JSON body collecting phone_id candidates."""
    found: list[PhoneIdCandidate] = []

    if isinstance(node, dict):
        # 1. An outright phone_id key is the strongest signal.
        for key in PHONE_ID_KEYS:
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                found.append(
                    PhoneIdCandidate(
                        value=value.strip(),
                        source=f"{source}:{key}",
                        tier=CONF_TIER_EXPLICIT_KEY,
                        label=_label_from(node),
                    )
                )

        # 2. Inside phone_list, an id-ish key is nearly as good.
        if in_phone_list:
            for key, value in node.items():
                if (
                    isinstance(value, str)
                    and value.strip()
                    and _looks_like_id_key(key)
                    and key not in PHONE_ID_KEYS
                ):
                    found.append(
                        PhoneIdCandidate(
                            value=value.strip(),
                            source=f"{source}:phone_list.{key}",
                            tier=CONF_TIER_PHONE_LIST,
                            label=_label_from(node),
                        )
                    )

        for key, value in node.items():
            found.extend(
                _mine(
                    value,
                    f"{source}.{key}",
                    in_phone_list=in_phone_list or key == "phone_list",
                )
            )

    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(
                _mine(item, f"{source}[{index}]", in_phone_list=in_phone_list)
            )

    return found


def _mine_text(text: str, source: str, tier: int) -> list[PhoneIdCandidate]:
    """Regex-scan a raw body for UUIDs, for bodies we could not decode."""
    return [
        PhoneIdCandidate(value=match, source=f"{source}:regex", tier=tier)
        for match in dict.fromkeys(UUID_RE.findall(text))
    ]


def _dedupe(candidates: list[PhoneIdCandidate]) -> list[PhoneIdCandidate]:
    """Collapse duplicate values, keeping the best-scoring occurrence."""
    best: dict[str, PhoneIdCandidate] = {}
    for candidate in candidates:
        existing = best.get(candidate.value)
        if existing is None or candidate.score > existing.score:
            if existing is not None and not candidate.label:
                candidate.label = existing.label
            best[candidate.value] = candidate
    return sorted(best.values(), key=lambda c: c.score, reverse=True)


def _payload(email: str, phone_id: str, endpoint: str) -> dict[str, Any]:
    """Build a probe body mirroring what the app sends.

    Probes stay read-only, so no endpoint needs extra fields; the signature
    keeps ``endpoint`` so that stays visible at the call site.
    """
    return {
        "email": email,
        "phone_id": phone_id,
        "language": "tr-TR",
    }


def _is_account_body(payload: Any) -> bool:
    """Return True when a body looks like a real account response."""
    if not isinstance(payload, dict):
        return False
    return any(key in payload for key in ("email", "sip", "phone_list", "user_name"))


async def _verify(
    session: aiohttp.ClientSession,
    email: str,
    phone_id: str,
) -> tuple[bool, RawResponse]:
    """Check whether a phone_id yields a usable account response."""
    response = await raw_post(
        session, ENDPOINT_GET_ACCOUNT, _payload(email, phone_id, ENDPOINT_GET_ACCOUNT)
    )
    return (response.ok and _is_account_body(response.json)), response


async def async_discover_phone_id(
    session: aiohttp.ClientSession,
    email: str,
    *,
    verify: bool = True,
) -> DiscoveryResult:
    """Discover the account's phone_id from its e-mail address.

    Probes the API with throwaway phone_id values, mines every response body for
    identifiers, then confirms each candidate. The returned report explains what
    was tried so a failure is actionable instead of silent.
    """
    result = DiscoveryResult()
    add = result.report.append
    add(f"phone_id discovery for {email}")

    raw_hits: list[PhoneIdCandidate] = []
    # Signals that let us name the failure. Observed against the live API: an
    # unknown e-mail gets HTTP 200 with a completely empty getAccount body,
    # an empty list from getUserLocations and "0" from userAccountControl --
    # so "no candidates" alone would be a misleading thing to report.
    reachable = False
    account_body_seen = False
    locations_seen = False

    for bootstrap in BOOTSTRAP_PHONE_IDS:
        shown = bootstrap or "<empty>"
        for endpoint in DISCOVERY_ENDPOINTS:
            response = await raw_post(
                session, endpoint, _payload(email, bootstrap, endpoint)
            )

            if response.error:
                add(f"  {endpoint} (phone_id={shown}): network error: {response.error}")
                continue

            reachable = True
            if endpoint == ENDPOINT_GET_ACCOUNT and _is_account_body(response.json):
                account_body_seen = True
            if endpoint == ENDPOINT_GET_LOCATIONS and response.json:
                locations_seen = True

            if response.ok:
                hits = _mine(response.json, endpoint) if response.json is not None else []
                if not hits:
                    hits = _mine_text(response.text, endpoint, CONF_TIER_UUID_SCAN)
                add(f"  {endpoint} (phone_id={shown}): HTTP 200, {len(hits)} candidate(s)")
            else:
                # Failures are useful too -- upstream's "Method 3" relied on the
                # rejected attempt revealing the expected value.
                hits = _mine_text(response.text, endpoint, CONF_TIER_ERROR_BODY)
                add(
                    f"  {endpoint} (phone_id={shown}): HTTP {response.status}, "
                    f"{len(hits)} candidate(s) from error body"
                )

            raw_hits.extend(hits)

        if raw_hits:
            add(f"  stopping probes early: {len(raw_hits)} raw hit(s) collected")
            break

    result.candidates = _dedupe(raw_hits)

    if not result.candidates:
        if not reachable:
            result.diagnosis = (
                "Could not reach the Multitek cloud API at all. Check the network "
                "connection and whether port 8096 is blocked."
            )
        elif not account_body_seen:
            # Live finding (2026-08): getAccount returns an empty 200 body for
            # every throwaway phone_id, so an empty body does NOT prove the
            # e-mail is unknown -- getAccount appears to be keyed by a real,
            # device-registered phone_id. Email-only discovery cannot bootstrap
            # past this. Say so honestly instead of blaming the address alone.
            result.diagnosis = (
                f"Could not read an account for {email} from the e-mail alone. "
                "Every getAccount call returned an empty body. Two things can "
                "cause this and they are indistinguishable from outside:\n"
                "  1. the e-mail is not the one registered in the Multitek Cloud "
                "app (an invite may have gone to a different address), or\n"
                "  2. this API only returns the account for a phone_id that the "
                "app already registered on the device -- in which case the "
                "phone_id must come from the app (Proxyman / adb) and cannot be "
                "derived from the e-mail.\n"
                "Confirm the exact app e-mail first; if it is correct, automatic "
                "discovery is not possible against this API and manual entry is "
                "required."
            )
        elif not locations_seen:
            result.diagnosis = (
                "The account exists but has no locations attached, so no DiafonBox "
                "is linked to it yet. Finish setup in the Multitek Cloud app first."
            )
        else:
            result.diagnosis = (
                "The account exists but no phone is registered on it. Open the "
                "Multitek Cloud app once on your phone, then retry."
            )
        add(result.diagnosis)
        return result

    add(f"{len(result.candidates)} unique candidate(s) before verification")

    if not verify:
        return result

    # Negative control: if a value that cannot possibly be right also verifies,
    # the server is ignoring phone_id and verification proves nothing.
    control_ok, _ = await _verify(session, email, "diafonbox-oto-control-value")
    result.server_ignores_phone_id = control_ok
    if control_ok:
        add(
            "NOTE: a deliberately bogus phone_id was also accepted, so the server "
            "ignores this field. Ranking by evidence instead of verification."
        )

    # A malformed body could yield dozens of UUIDs; verifying every one would
    # hammer the API. The list is already ranked, so the tail is not worth it.
    to_verify = result.candidates[:MAX_VERIFY]
    if len(result.candidates) > MAX_VERIFY:
        add(
            f"verifying the top {MAX_VERIFY} of {len(result.candidates)} candidates"
        )

    for candidate in to_verify:
        ok, response = await _verify(session, email, candidate.value)
        # When the server ignores phone_id, "it worked" is not evidence. Only
        # trust the candidate if the account body actually contains it.
        if ok and result.server_ignores_phone_id:
            ok = candidate.value in (response.text or "")
        candidate.verified = ok
        add(f"  verify {candidate.value}: {'ok' if ok else 'no'} ({candidate.source})")

    result.candidates = sorted(result.candidates, key=lambda c: c.score, reverse=True)

    if result.verified:
        add(f"Best: {result.best.value} via {result.best.source}")
    else:
        add("No candidate verified; the highest ranked one is still worth trying.")

    return result
