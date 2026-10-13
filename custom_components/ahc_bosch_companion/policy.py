"""Pure Bosch/AHC setpoint arbitration, independent of Home Assistant.

AHC remains responsible for window/frost/liming protection.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

MIN_TEMP = 5.0
MAX_TEMP = 30.0


@dataclass(frozen=True)
class Desired:
    """Command to send to a Bosch BTH-RA."""

    mode: str  # "manual" or "pause"
    temperature: float | None = None


def valid_temp(value: object, low: float = MIN_TEMP, high: float = MAX_TEMP) -> float | None:
    """Validate incoming temperatures without coercing None/NaN to zero."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return round(number, 1) if isfinite(number) and low <= number <= high else None


def is_physical_schedule_change(
    source: str | None, previous_setpoint: float | None, reported: float | None
) -> bool:
    """A persistent 'manual' source by itself is NOT a new physical event."""
    return (
        source == "manual"
        and previous_setpoint is not None
        and reported is not None
        and abs(previous_setpoint - reported) >= 0.1
    )


def decide(
    ahc_target: object,
    ahc_hvac_mode: str,
    room_mode: str,
    override_mode: str,
    override_setpoint: object,
    *,
    ahc_protection: bool = False,
) -> Desired | None:
    """Resolve authority and protective overrides.

    No valid AHC target -> no actuation. Protective AHC target always wins.
    When AHC explicitly selects OFF, BTH-RA pause is used because its
    Zigbee standard system_mode does not support a functional OFF state.
    """
    base = valid_temp(ahc_target)
    if base is None or ahc_hvac_mode not in ("heat", "off"):
        return None
    if ahc_hvac_mode == "off":
        return Desired("pause")
    if ahc_protection:
        return Desired("manual", base)
    if room_mode == "pause":
        return Desired("pause")
    user_target = valid_temp(override_setpoint)
    if user_target is not None and override_mode in ("manual", "temporary"):
        return Desired("manual", user_target)
    return Desired("manual", base)
