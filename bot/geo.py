"""Resolve a shared location to an IANA timezone, for the /timezone "share location" flow.

Uses ``timezonefinder``'s bundled boundary data — an offline lookup, no network call and
no API key needed at request time. ``TimezoneFinder`` is expensive to construct (it loads
the boundary index into memory), so it is built once, lazily, on first use.
"""

from __future__ import annotations

_finder = None


def _get_finder():
    global _finder
    if _finder is None:
        from timezonefinder import TimezoneFinder

        _finder = TimezoneFinder()
    return _finder


def timezone_from_location(lat: float, lng: float) -> str | None:
    """Return the IANA timezone at ``(lat, lng)``, or ``None`` if none could be resolved."""
    return _get_finder().timezone_at(lat=lat, lng=lng)
