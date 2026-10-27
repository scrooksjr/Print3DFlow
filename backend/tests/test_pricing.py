from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.pricing import RateCard, calculate
from backend.tests.test_workflow import quoted, plan, approve
from backend.tests.test_integrations import setup_slice


def test_default_rate_card_is_decimal_safe():
    assert calculate(75, 4.5, RateCard())["total_cents"] == 2220


def test_synthetic_policy_allowance_and_included_waste():
    # Invented test values, not a customer or shop rate card.
    rates = RateCard(
        pla_per_kg=24,
        included_waste_percent=8,
        machine_per_hour=7,
        machine_variance_percent=5,
        setup_per_job=9,
        markup_percent=12,
        minimum_order=25,
        reservation_buffer_minutes=0,
        support_surcharge_per_kg=4,
    )
    price = calculate(100, 1, rates, support_percent=0)
    assert [i["cents"] for i in price["items"]] == [240, 735, 900, 225, 400]
    assert price["total_cents"] == 2500
    assert Decimal(price["billable_grams"]) == 100


def test_support_surcharge_is_optional_and_strictly_above_threshold():
    rates = RateCard(pla_per_kg=24, support_surcharge_per_kg=4)
    assert calculate(100, 1, rates, support_percent=30)["items"][0]["cents"] == 240
    assert (
        calculate(100, 1, rates, support_percent=30, apply_support_surcharge=True)[
            "items"
        ][0]["cents"]
        == 280
    )
    with pytest.raises(ValueError):
        calculate(100, 1, rates, support_percent=25, apply_support_surcharge=True)
    with pytest.raises(ValueError):
        calculate(100, 1, rates, apply_support_surcharge=True)


def test_shop_price_waste_markup_and_minimum():
    rates = RateCard(
        currency="CAD",
        pla_per_kg=25,
        waste_percent=10,
        machine_per_hour=8,
        setup_per_job=7,
        markup_percent=25,
        minimum_order=30,
    )
    result = calculate(100, 1, rates)
    assert [i["cents"] for i in result["items"]] == [275, 800, 700, 444, 781]
    assert result["total_cents"] == 3000
    assert Decimal(result["billable_grams"]) == 110


@pytest.mark.parametrize(
    "fields",
    [
        {"pla_per_kg": -1},
        {"waste_percent": 101},
        {"machine_per_hour": "NaN"},
        {"currency": "JPY"},
        {"reservation_buffer_minutes": -1},
    ],
)
def test_invalid_rate_inputs_rejected(fields):
    with pytest.raises(ValidationError):
        RateCard(**fields)


def test_rate_changes_only_affect_new_quotes(client):
    key, old = quoted(client)
    rates = RateCard(
        machine_per_hour=10,
        pla_per_kg=20,
        setup_per_job=3,
        markup_percent=0,
        reservation_buffer_minutes=15,
    )
    saved = client.post("/api/pricing", json=rates.model_dump(mode="json"))
    assert saved.status_code == 201
    assert client.get("/api/pricing").json()["id"] == saved.json()["id"]
    # An existing reviewed quote retains its immutable terms.
    assert approve(client, plan(client, key)).status_code == 200
    _, new = quoted(client)
    assert new["pricing_mode"] == "shop" and new["rate_card"] == saved.json()["id"]
    assert new["total_cents"] == 4950  # 75g at 20/kg + 4.5h at 10/h + 3 setup
    assert new["duration_minutes"] == 285
    old_after = next(
        q for q in client.get("/api/state").json()["quotes"] if q["id"] == old["id"]
    )
    assert old_after == old
    assert old["total_cents"] == 2220 and old["duration_minutes"] == 300


def test_comparison_records_per_part_agreement_without_calibration(
    client, monkeypatch, tmp_path
):
    setup_slice(monkeypatch, tmp_path)
    key, _ = quoted(client)
    response = client.post(
        f"/api/jobs/{key}/slice-quotes",
        json={"confirmed": True, "idempotency_key": "pricing-comparison-slice"},
    )
    task = client.get("/api/tasks/" + response.json()["id"]).json()
    qid = task["quote_id"]
    r = client.post(
        f"/api/quotes/{qid}/studio-comparisons",
        json={
            "studio_grams": 3.5,
            "studio_minutes": 15,
            "same_part_and_settings_confirmed": True,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["within_tolerance"]
    assert r.json()["quantity_basis"] == "one part"
    assert r.json()["physical_print_calibrated"] is False
    assert r.json()["time_difference_percent"] == 0
    assert len(client.get(f"/api/quotes/{qid}/studio-comparisons").json()) == 1
    mismatch = client.post(
        f"/api/quotes/{qid}/studio-comparisons",
        json={
            "studio_grams": 7,
            "studio_minutes": 30,
            "same_part_and_settings_confirmed": True,
        },
    )
    assert not mismatch.json()["within_tolerance"]


def test_manual_quote_cannot_be_used_for_studio_calibration(client):
    _, q = quoted(client)
    assert (
        client.post(
            "/api/quotes/" + q["id"] + "/studio-comparisons",
            json={
                "studio_grams": 25,
                "studio_minutes": 90,
                "same_part_and_settings_confirmed": True,
            },
        ).status_code
        == 422
    )
