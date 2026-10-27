"""Deterministic rate-card math. Currency values are expressed in major units."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RateCard(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, validate_default=True
    )
    currency: Literal["USD", "CAD", "EUR", "GBP", "AUD", "NZD"] = "USD"
    pla_per_kg: Decimal = Field(default=Decimal("30"), ge=0, le=10000)
    waste_percent: Decimal = Field(default=0, ge=0, le=100)
    machine_per_hour: Decimal = Field(default=Decimal("2.50"), ge=0, le=10000)
    setup_per_job: Decimal = Field(default=5, ge=0, le=100000)
    markup_percent: Decimal = Field(default=20, ge=0, le=1000)
    minimum_order: Decimal = Field(default=0, ge=0, le=100000)
    reservation_buffer_minutes: int = Field(default=30, ge=0, le=1440)
    included_waste_percent: Decimal = Field(default=0, ge=0, le=100)
    machine_variance_percent: Decimal = Field(default=0, ge=0, le=100)
    support_threshold_percent: Decimal = Field(default=25, ge=0, le=100)
    support_surcharge_per_kg: Decimal = Field(default=0, ge=0, le=10000)


def minor(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate(
    grams, hours, rates: RateCard, support_percent=None, apply_support_surcharge=False
):
    grams = Decimal(str(grams))
    hours = Decimal(str(hours))
    if apply_support_surcharge and (
        support_percent is None
        or Decimal(str(support_percent)) <= rates.support_threshold_percent
    ):
        raise ValueError(
            "A support share above the configured threshold is required for the optional surcharge."
        )
    effective_rate = rates.pla_per_kg + (
        rates.support_surcharge_per_kg if apply_support_surcharge else 0
    )
    material = minor(
        grams * (1 + rates.waste_percent / 100) * effective_rate / 1000 * 100
    )
    billed_hours = hours * (1 + rates.machine_variance_percent / 100)
    machine = minor(billed_hours * rates.machine_per_hour * 100)
    setup = minor(rates.setup_per_job * 100)
    markup = minor(Decimal(material + machine + setup) * rates.markup_percent / 100)
    minimum = max(
        0, minor(rates.minimum_order * 100) - material - machine - setup - markup
    )
    items = [
        dict(
            label=f"PLA material ({rates.currency} {effective_rate}/kg; {rates.waste_percent}% additional waste)",
            cents=material,
        ),
        dict(
            label=f"Machine time ({rates.currency} {rates.machine_per_hour}/h; +{rates.machine_variance_percent}% allowance)",
            cents=machine,
        ),
        dict(label="Setup per job", cents=setup),
        dict(label=f"Markup ({rates.markup_percent}%)", cents=markup),
    ]
    if minimum:
        items.append(dict(label="Minimum order adjustment", cents=minimum))
    return dict(
        items=items,
        total_cents=sum(x["cents"] for x in items),
        billable_grams=str(grams * (1 + rates.waste_percent / 100)),
        billable_hours=str(billed_hours),
        support_surcharge_applied=apply_support_surcharge,
    )
