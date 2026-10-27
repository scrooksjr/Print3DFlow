import json

from backend.mesh_upload import import_3mf
from backend.tests.test_colors import color_project
from backend.tests.test_integrations import mock_meta, draft_payload


def test_only_assigned_slot_color_is_suggested():
    info = import_3mf(color_project()).metadata["color_info"]
    assert len(info["saved_filaments"]) == 4
    assert info["color_inference"]["suggested_color"] == "Green"
    assert info["color_inference"]["assigned_colors"] == [
        {"slot": 2, "color": "#00FF00FF"}
    ]


def test_four_colors_are_suggested_only_when_four_slots_are_assigned():
    info = import_3mf(color_project(slots=(1, 2, 3, 4))).metadata["color_info"]
    assert info["color_inference"]["suggested_color"] == "Red / Green / Blue / White"
    assert info["quoting_blocked"]


def test_missing_or_encoded_color_mapping_never_suggests_base_color():
    for content in (color_project(slots=()), color_project(paint=True)):
        inference = import_3mf(content).metadata["color_info"]["color_inference"]
        assert inference["suggested_color"] is None and inference["clarification"]


def test_meta_uses_assigned_color_without_asking_for_it_again(client, monkeypatch):
    stage = client.post(
        "/api/model-uploads", files={"file": ("colors.3mf", color_project())}
    ).json()
    sent = mock_meta(
        monkeypatch,
        draft_payload(color=None, questions=["What color should these prints be?"]),
    )
    result = client.post(
        "/api/intake/drafts",
        json=dict(
            request="Three copies of the attached model", model_upload_id=stage["id"]
        ),
    ).json()
    assert result["draft"]["color"] == "Green"
    assert not any("what color" in q.lower() for q in result["draft"]["questions"])
    payload = json.loads(json.loads(sent[0].content)["messages"][1]["content"])
    assert payload["validated_file"]["color_inference"]["assigned_colors"] == [
        {"slot": 2, "color": "#00FF00FF"}
    ]


def test_customer_color_override_is_not_replaced_with_file_color(client, monkeypatch):
    stage = client.post(
        "/api/model-uploads", files={"file": ("colors.3mf", color_project())}
    ).json()
    mock_meta(
        monkeypatch,
        draft_payload(
            color="Red",
            questions=["Which color should be used: file green or requested red?"],
        ),
    )
    result = client.post(
        "/api/intake/drafts",
        json=dict(
            request="Three red copies of the attached model",
            model_upload_id=stage["id"],
        ),
    ).json()
    assert result["draft"]["color"] == "Red"
    assert any("Which color" in q for q in result["draft"]["questions"])
