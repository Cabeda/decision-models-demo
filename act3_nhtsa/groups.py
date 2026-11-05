"""Shared component-group vocabulary for Act 3.

NHTSA's COMPDESC field has ~44 top-level categories in the VW-Group slice.
That is far more than Laya can handle as Choice options (it degrades past ~20),
so we collapse them into a small, projector-readable set. The same mapping is
the Choice the model answers AND the ground-truth bucket the report compares
against, so it lives in one place.
"""

from __future__ import annotations

# The simplified groups the model chooses from, with a one-line description each.
# Keep this at <=12 entries (Laya weakens past ~20 options).
GROUPS: dict[str, str] = {
    "air_bags": "Air bags and their sensors or deployment",
    "brakes": "Service brakes, ABS, parking brake, brake hold",
    "electrical": "Electrical system, wiring, battery, infotainment, communication",
    "engine": "Engine, engine cooling",
    "fuel_propulsion": "Fuel system, propulsion, hybrid/EV drive",
    "powertrain": "Transmission, drivetrain, power train",
    "steering_suspension": "Steering, suspension, wheels, tires",
    "driver_assist": "Forward collision, lane departure, back-over, speed control, stability",
    "structure_body": "Structure, body, exterior lighting, latches, seats, visibility/wipers",
    "other": "Equipment, child seats, or anything that fits none of the above",
}

# Map each raw top-level COMPDESC category (upper-cased, text before the first
# ':') to one simplified group. Anything not listed falls through to "other".
_RAW_TO_GROUP: dict[str, str] = {
    "AIR BAGS": "air_bags",
    "SERVICE BRAKES": "brakes",
    "SERVICE BRAKES, HYDRAULIC": "brakes",
    "SERVICE BRAKES, AIR": "brakes",
    "PARKING BRAKE": "brakes",
    "ELECTRICAL SYSTEM": "electrical",
    "COMMUNICATION": "electrical",
    "INTERIOR LIGHTING": "electrical",
    "ENGINE": "engine",
    "ENGINE AND ENGINE COOLING": "engine",
    "FUEL/PROPULSION SYSTEM": "fuel_propulsion",
    "FUEL SYSTEM, GASOLINE": "fuel_propulsion",
    "FUEL SYSTEM, DIESEL": "fuel_propulsion",
    "FUEL SYSTEM, OTHER": "fuel_propulsion",
    "HYBRID PROPULSION SYSTEM": "fuel_propulsion",
    "FIRERELATED": "fuel_propulsion",
    "POWER TRAIN": "powertrain",
    "TRACTION CONTROL SYSTEM": "powertrain",
    "STEERING": "steering_suspension",
    "SUSPENSION": "steering_suspension",
    "WHEELS": "steering_suspension",
    "TIRES": "steering_suspension",
    "FORWARD COLLISION AVOIDANCE": "driver_assist",
    "LANE DEPARTURE": "driver_assist",
    "BACK OVER PREVENTION": "driver_assist",
    "VEHICLE SPEED CONTROL": "driver_assist",
    "ELECTRONIC STABILITY CONTROL (ESC)": "driver_assist",
    "STRUCTURE": "structure_body",
    "EXTERIOR LIGHTING": "structure_body",
    "VISIBILITY/WIPER": "structure_body",
    "VISIBILITY": "structure_body",
    "SEATS": "structure_body",
    "SEAT BELTS": "structure_body",
    "LATCHES/LOCKS/LINKAGES": "structure_body",
    "TRAILER HITCHES": "structure_body",
}


def group_of(compdesc: str | None) -> str:
    """Ground-truth simplified group for a raw COMPDESC value."""
    if not compdesc:
        return "other"
    top = compdesc.split(":", 1)[0].strip().upper()
    return _RAW_TO_GROUP.get(top, "other")
