"""Per-property rows for the AVM report table (scope #10).

The client asked for the home evaluation "in the AVM report format": a
subject column beside comparable sales, row by row. Every value comes from the
listing record; anything the feed does not carry is None and renders as a
dash. Rows the sample report has but no feed provides here (roll number,
structure condition, renovation year) are deliberately absent.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from mls.models import Property
from mls.services.valuation.lot_dims import infer_lot_depth

FEET_PER_METRE = 3.28084


def _num(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> Optional[str]:
    text = (value or "").strip() if isinstance(value, str) else value
    return text or None


def _yes_no(value: Optional[str]) -> Optional[bool]:
    """'None'/'No' → False, any description → True, blank → unknown (None).

    Blank is unknown rather than "no": DDF leaves the field empty both when
    there is none and when the agent skipped it.
    """
    text = (value or "").strip().lower()
    if not text:
        return None
    return text not in {"none", "no", "n", "n/a"}


def _feet(value: Optional[Decimal], units: Optional[str]) -> Optional[float]:
    number = _num(value)
    if number is None:
        return None
    if (units or "").strip().lower().startswith("met"):
        number = round(number * FEET_PER_METRE, 2)
    return number


def property_details(prop: Optional[Property]) -> dict[str, Any]:
    """AVM table values for one listing. All keys always present."""
    if prop is None:
        return {key: None for key in DETAIL_KEYS}
    depth = infer_lot_depth(prop.lot_size_dimensions, prop.lot_size_area, prop.frontage_length_numeric)
    return {
        "address": _text(prop.unparsed_address),
        "city": _text(prop.city),
        "province": _text(prop.state_or_province),
        "postal_code": _text(prop.postal_code),
        "property_style": _text(prop.architectural_style) or _text(prop.property_sub_type),
        "property_type": _text(prop.property_sub_type),
        "frontage_ft": _feet(prop.frontage_length_numeric, prop.frontage_length_numeric_units),
        "depth_ft": _feet(depth, prop.frontage_length_numeric_units) if depth is not None else None,
        "lot_area": _num(prop.lot_size_area),
        "lot_area_units": _text(prop.lot_size_units),
        "year_built": prop.year_built,
        "floor_area_sqft": _num(prop.living_area) or _num(prop.above_grade_finished_area),
        "basement": _text(prop.basement),
        "storeys": prop.stories,
        "bedrooms": prop.bedrooms_total,
        "bedrooms_below_grade": prop.bedrooms_below_grade,
        "bathrooms_full": prop.bathrooms_total_integer,
        "bathrooms_half": prop.bathrooms_partial,
        "fireplaces": prop.fireplaces_total,
        "heating": _text(prop.heating),
        "air_conditioning": _yes_no(prop.cooling),
        "pool": _yes_no(prop.pool_features),
        "parking_total": prop.parking_total,
        "parking_features": _text(prop.parking_features),
        "tax_annual_amount": _num(prop.tax_annual_amount),
    }


DETAIL_KEYS = (
    "address", "city", "province", "postal_code", "property_style", "property_type",
    "frontage_ft", "depth_ft", "lot_area", "lot_area_units", "year_built", "floor_area_sqft",
    "basement", "storeys", "bedrooms", "bedrooms_below_grade", "bathrooms_full", "bathrooms_half",
    "fireplaces", "heating", "air_conditioning", "pool", "parking_total", "parking_features",
    "tax_annual_amount",
)


def subject_details(prop: Optional[Property], subject: dict[str, Any]) -> dict[str, Any]:
    """The subject column: the looked-up listing, overridden by what the user entered."""
    details = property_details(prop)
    overrides = {
        "postal_code": subject.get("postal_code") or None,
        "property_type": subject.get("property_sub_type") or None,
        "bedrooms": subject.get("bedrooms_total"),
        "bedrooms_below_grade": subject.get("bedrooms_partial"),
        "bathrooms_full": subject.get("bathrooms_total"),
        "floor_area_sqft": subject.get("living_area"),
        "parking_total": subject.get("parking_total"),
        "tax_annual_amount": subject.get("tax_annual_amount"),
        "frontage_ft": subject.get("lot_frontage"),
        "depth_ft": subject.get("lot_depth"),
    }
    for key, value in overrides.items():
        if value not in (None, ""):
            details[key] = value
    if not details["property_style"] and details["property_type"]:
        details["property_style"] = details["property_type"]
    return details


def confidence_stars(confidence: Optional[str], comp_count: int) -> int:
    """0-5 stars for the report header, from the model's own confidence band.

    Bands come from hedonic.apply_hedonic (by comparable count); within a band
    more comparables earn the higher star, capped at 5.
    """
    band = (confidence or "").lower()
    if band == "high":
        return 5 if comp_count >= 8 else 4
    if band == "medium":
        return 3
    if band == "low":
        return 2 if comp_count >= 2 else 1
    return 0
