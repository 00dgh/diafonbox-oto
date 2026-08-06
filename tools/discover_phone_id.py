#!/usr/bin/env python3
"""Find a Multitek Cloud account's phone_id from the command line.

Runs the same discovery the Home Assistant integration uses, but without
needing Home Assistant. Handy for checking whether discovery works on your
account before installing anything, and for reporting bugs: the printed report
shows exactly which endpoints answered and what was mined from each.

    pip install aiohttp
    python tools/discover_phone_id.py you@example.com

Only read-only endpoints are contacted. Nothing on your account is modified.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "diafonbox_oto"
)
_PKG = "diafonbox_oto_standalone"


def _load_component_modules():
    """Import the integration's HA-free modules without importing the package.

    The package's __init__ pulls in Home Assistant, which we do not have here,
    so build a synthetic package and load only the modules we need. Relative
    imports inside them still resolve because the module names are prefixed.
    """
    if not COMPONENT_DIR.is_dir():
        sys.exit(f"Component directory not found: {COMPONENT_DIR}")

    package = types.ModuleType(_PKG)
    package.__path__ = [str(COMPONENT_DIR)]
    sys.modules[_PKG] = package

    def load(name: str):
        spec = importlib.util.spec_from_file_location(
            f"{_PKG}.{name}", COMPONENT_DIR / f"{name}.py"
        )
        if spec is None or spec.loader is None:
            sys.exit(f"Could not load {name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{_PKG}.{name}"] = module
        spec.loader.exec_module(module)
        return module

    load("const")
    load("api")
    return load("discovery")


async def _run(email: str, verify: bool, as_json: bool) -> int:
    try:
        import aiohttp
    except ImportError:
        sys.exit("aiohttp is required:  pip install aiohttp")

    discovery = _load_component_modules()

    async with aiohttp.ClientSession() as session:
        result = await discovery.async_discover_phone_id(
            session, email, verify=verify
        )

    if as_json:
        print(
            json.dumps(
                {
                    "email": email,
                    "server_ignores_phone_id": result.server_ignores_phone_id,
                    "diagnosis": result.diagnosis,
                    "best": result.best.value if result.best else None,
                    "candidates": [
                        {
                            "value": c.value,
                            "source": c.source,
                            "tier": c.tier,
                            "label": c.label,
                            "verified": c.verified,
                        }
                        for c in result.candidates
                    ],
                    "report": result.report,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0 if result.best else 1

    print(result.format_report())
    print()

    if not result.candidates:
        print("No phone_id found.")
        if result.diagnosis:
            print()
            print(result.diagnosis)
        return 1

    print(f"{'phone_id':<40} {'verified':<9} source")
    print("-" * 78)
    for candidate in result.candidates:
        mark = "yes" if candidate.verified else "no"
        print(f"{candidate.value:<40} {mark:<9} {candidate.source}")
        if candidate.label:
            print(f"{'':<40} {'':<9} {candidate.label}")

    print()
    best = result.best
    print(f"Use this one: {best.value}")
    if not best.verified:
        print("(unverified - it is the best-ranked guess, not a confirmed value)")
    return 0


def main() -> None:
    """Parse arguments and run discovery."""
    parser = argparse.ArgumentParser(
        description="Discover the phone_id for a Multitek Cloud account."
    )
    parser.add_argument("email", help="e-mail registered in the Multitek Cloud app")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the confirmation round (fewer requests, less certainty)",
    )
    parser.add_argument("--json", action="store_true", help="machine readable output")
    args = parser.parse_args()

    raise SystemExit(
        asyncio.run(_run(args.email, not args.no_verify, args.json))
    )


if __name__ == "__main__":
    main()
