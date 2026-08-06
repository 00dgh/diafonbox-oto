"""Offline tests for phone_id discovery.

No network and no Home Assistant: these exercise the parts that decide *which*
value wins, against synthetic API bodies. Run with pytest, or directly:

    python tests/test_discovery.py
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "diafonbox_oto"
)
_PKG = "diafonbox_oto_test"


def _load():
    """Load the HA-free modules under a synthetic package."""
    if _PKG in sys.modules:
        return sys.modules[f"{_PKG}.discovery"]

    package = types.ModuleType(_PKG)
    package.__path__ = [str(COMPONENT_DIR)]
    sys.modules[_PKG] = package

    def load(name: str):
        spec = importlib.util.spec_from_file_location(
            f"{_PKG}.{name}", COMPONENT_DIR / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{_PKG}.{name}"] = module
        spec.loader.exec_module(module)
        return module

    load("const")
    load("api")
    return load("discovery")


discovery = _load()

REAL_ID = "11111111-2222-3333-4444-555555555555"
OTHER_ID = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"

ACCOUNT_BODY = {
    "email": "user@example.com",
    "user_name": "Seran",
    "user_surname": "Yilmaz",
    "sip": "01001",
    "phone_list": [
        {
            "phone_id": REAL_ID,
            "token": "3f9c2a1b8e7d6c5b4a39281706f5e4d3",
            "phone_name": "iPhone",
            "phone_model": "iPhone15,3",
            "phone_os": "iOS 26.2.1",
        }
    ],
}


def test_explicit_phone_id_wins():
    """An outright phone_id key is picked and labelled."""
    hits = discovery._mine(ACCOUNT_BODY, "getAccount")
    ranked = discovery._dedupe(hits)

    assert ranked, "expected at least one candidate"
    assert ranked[0].value == REAL_ID
    assert ranked[0].tier == discovery.CONF_TIER_EXPLICIT_KEY
    assert "iPhone" in ranked[0].label


def test_sip_and_token_are_not_candidates():
    """Account identifiers that are not phone ids must be ignored."""
    values = {c.value for c in discovery._mine(ACCOUNT_BODY, "getAccount")}

    assert "01001" not in values, "SIP number leaked into candidates"
    assert ACCOUNT_BODY["phone_list"][0]["token"] not in values, "token leaked"


def test_phone_list_uuid_key_is_found_without_explicit_key():
    """Fall back to an id-ish key inside phone_list."""
    body = {
        "email": "user@example.com",
        "phone_list": [{"uuid": REAL_ID, "phone_name": "Pixel", "token": "zz"}],
    }
    ranked = discovery._dedupe(discovery._mine(body, "getAccount"))

    assert ranked[0].value == REAL_ID
    assert ranked[0].tier == discovery.CONF_TIER_PHONE_LIST
    assert "Pixel" in ranked[0].label


def test_call_id_does_not_win():
    """A call_id is UUID-shaped but must never outrank the real phone_id."""
    body = {
        "call_id": OTHER_ID,
        "location_id": "VZG20250517204814978sem",
        "phone_list": [{"phone_id": REAL_ID}],
    }
    ranked = discovery._dedupe(discovery._mine(body, "getAccount"))

    assert ranked[0].value == REAL_ID
    assert OTHER_ID not in {c.value for c in ranked}, "call_id became a candidate"


def test_error_body_regex_mining():
    """Upstream's 'read it from the failed attempt' trick, automated."""
    text = f'{{"error":"unknown phone_id, expected {REAL_ID}"}}'
    hits = discovery._mine_text(text, "getAccount", discovery.CONF_TIER_ERROR_BODY)

    assert [h.value for h in hits] == [REAL_ID]
    assert hits[0].tier == discovery.CONF_TIER_ERROR_BODY


def test_verified_beats_higher_tier():
    """Verification must dominate the evidence tier when ranking."""
    weak = discovery.PhoneIdCandidate(
        value=OTHER_ID, source="s", tier=discovery.CONF_TIER_ERROR_BODY, verified=True
    )
    strong = discovery.PhoneIdCandidate(
        value=REAL_ID, source="s", tier=discovery.CONF_TIER_EXPLICIT_KEY
    )
    ranked = sorted([strong, weak], key=lambda c: c.score, reverse=True)

    assert ranked[0] is weak


def test_dedupe_keeps_best_and_preserves_label():
    """The same value seen twice collapses to its strongest sighting."""
    low = discovery.PhoneIdCandidate(
        value=REAL_ID, source="regex", tier=discovery.CONF_TIER_UUID_SCAN, label="iPhone"
    )
    high = discovery.PhoneIdCandidate(
        value=REAL_ID, source="key", tier=discovery.CONF_TIER_EXPLICIT_KEY
    )
    ranked = discovery._dedupe([low, high])

    assert len(ranked) == 1
    assert ranked[0].tier == discovery.CONF_TIER_EXPLICIT_KEY
    assert ranked[0].label == "iPhone", "label from the weaker sighting was lost"


def test_empty_body_yields_nothing():
    """A body with no identifiers must not invent one."""
    assert discovery._mine({"status": "ok", "count": 0}, "getAccount") == []


# -- end-to-end over a fake server -------------------------------------------


def _fake_server(*, strict: bool, calls: list[tuple[str, str]]):
    """Return a raw_post stand-in.

    strict=True models a server that validates phone_id (wrong value -> 403).
    strict=False models one that ignores it, which is what the negative control
    in discovery exists to detect.
    """
    api = sys.modules[f"{_PKG}.api"]

    async def raw_post(session, endpoint, payload, timeout=20):
        phone_id = payload.get("phone_id", "")
        calls.append((endpoint, phone_id))

        if strict and phone_id != REAL_ID:
            return api.RawResponse(
                endpoint=endpoint,
                status=403,
                text=f'{{"message":"invalid phone_id, expected {REAL_ID}"}}',
            )

        return api.RawResponse(
            endpoint=endpoint, status=200, text=str(ACCOUNT_BODY), json=ACCOUNT_BODY
        )

    return raw_post


def _discover(fake, email="user@example.com"):
    """Run discovery against a fake transport."""
    import asyncio

    original = discovery.raw_post
    discovery.raw_post = fake
    try:
        return asyncio.run(discovery.async_discover_phone_id(None, email))
    finally:
        discovery.raw_post = original


def test_end_to_end_strict_server():
    """A validating server: the id is mined from the rejection, then verified."""
    calls: list[tuple[str, str]] = []
    result = _discover(_fake_server(strict=True, calls=calls))

    assert result.best is not None
    assert result.best.value == REAL_ID
    assert result.best.verified, "should verify once the right id is tried"
    assert not result.server_ignores_phone_id


def test_end_to_end_permissive_server():
    """A server that ignores phone_id must be detected, not blindly trusted."""
    calls: list[tuple[str, str]] = []
    result = _discover(_fake_server(strict=False, calls=calls))

    assert result.server_ignores_phone_id, "negative control failed to fire"
    assert result.best is not None
    assert result.best.value == REAL_ID


def test_unknown_email_is_named_not_guessed():
    """Reproduces the live API's answer for an e-mail it does not know.

    Observed against cloud.multitek.com.tr: HTTP 200 everywhere, an empty
    getAccount body, [] from getUserLocations and "0" from userAccountControl.
    Reporting only "no candidates" would send the user hunting for a phone_id
    that was never the problem.
    """
    api = sys.modules[f"{_PKG}.api"]
    bodies = {
        "getAccount": ("", None),
        "getUserLocations": ("[]", []),
        "getCallAllRecords": ("[]", []),
        "userAccountControl": ("0", 0),
    }

    async def raw_post(session, endpoint, payload, timeout=20):
        text, parsed = bodies.get(endpoint, ("", None))
        return api.RawResponse(
            endpoint=endpoint, status=200, text=text, json=parsed
        )

    result = _discover(raw_post)

    assert not result.candidates
    # The message must name both possibilities (wrong e-mail OR phone_id-keyed
    # API) rather than blaming the address alone -- that was the live finding.
    lowered = result.diagnosis.lower()
    assert "empty body" in lowered
    assert "phone_id" in result.diagnosis
    assert "user@example.com" in result.diagnosis


def test_unreachable_api_is_named():
    """A network failure must not be reported as 'no phone_id found'."""
    api = sys.modules[f"{_PKG}.api"]

    async def raw_post(session, endpoint, payload, timeout=20):
        return api.RawResponse(
            endpoint=endpoint, status=0, text="", error="Cannot connect"
        )

    result = _discover(raw_post)

    assert not result.candidates
    assert "reach" in result.diagnosis.lower()


def test_account_without_registered_phone_is_named():
    """Account and location exist, but no phone has ever opened the app."""
    api = sys.modules[f"{_PKG}.api"]
    body = {"email": "user@example.com", "sip": "01001", "phone_list": []}

    async def raw_post(session, endpoint, payload, timeout=20):
        if endpoint == "getUserLocations":
            return api.RawResponse(
                endpoint=endpoint, status=200, text="[{}]", json=[{"location_id": "X"}]
            )
        return api.RawResponse(
            endpoint=endpoint, status=200, text=str(body), json=body
        )

    result = _discover(raw_post)

    assert not result.candidates
    assert "no phone is registered" in result.diagnosis.lower()


def test_discovery_never_calls_write_endpoints():
    """Probing must stay read-only; resumeApp/addCall would mutate the account."""
    calls: list[tuple[str, str]] = []
    _discover(_fake_server(strict=True, calls=calls))

    touched = {endpoint for endpoint, _ in calls}
    forbidden = {"resumeApp", "addCall", "setCallDuration", "controlCurrentCall"}

    assert not touched & forbidden, f"write endpoint probed: {touched & forbidden}"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except AssertionError as err:
            failures += 1
            print(f"FAIL {name}: {err}")
        else:
            print(f"ok   {name}")
    print()
    print("all passed" if not failures else f"{failures} failure(s)")
    sys.exit(1 if failures else 0)
