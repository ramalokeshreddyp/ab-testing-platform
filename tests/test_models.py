import pytest
from pydantic import ValidationError
from common.models import (
    ExperimentConfig,
    Variant,
    EqualsRule,
    InListRule,
    ExperimentCreate,
    StatusUpdate,
    AnalyticsEvent,
    EventPayload,
    ExperimentStatus
)


def test_valid_experiment_config():
    config = ExperimentConfig(
        variants=[
            Variant(name="control", weight=50),
            Variant(name="treatment", weight=50)
        ],
        targeting_rules=[
            EqualsRule(attribute="country", value="US")
        ]
    )
    assert len(config.variants) == 2
    assert sum(v.weight for v in config.variants) == 100


def test_invalid_variant_weights_sum_less_than_100():
    with pytest.raises(ValidationError) as exc_info:
        ExperimentConfig(
            variants=[
                Variant(name="control", weight=40),
                Variant(name="treatment", weight=59)
            ]
        )
    assert "Sum of variant weights must equal exactly 100" in str(exc_info.value)


def test_invalid_variant_weights_sum_greater_than_100():
    with pytest.raises(ValidationError) as exc_info:
        ExperimentConfig(
            variants=[
                Variant(name="control", weight=50),
                Variant(name="treatment", weight=51)
            ]
        )
    assert "Sum of variant weights must equal exactly 100" in str(exc_info.value)


def test_experiment_create_payload():
    payload = ExperimentCreate(
        name="new_checkout_flow",
        description="Testing checkout conversion",
        config=ExperimentConfig(
            variants=[
                Variant(name="control", weight=50),
                Variant(name="treatment", weight=50)
            ],
            targeting_rules=[
                InListRule(attribute="country", value=["US", "CA", "UK"])
            ]
        )
    )
    assert payload.name == "new_checkout_flow"
    assert payload.config.variants[0].weight == 50


def test_status_update():
    status_active = StatusUpdate(status=ExperimentStatus.ACTIVE)
    assert status_active.status == "ACTIVE"
    status_draft = StatusUpdate(status=ExperimentStatus.DRAFT)
    assert status_draft.status == "DRAFT"


def test_analytics_event_validation():
    valid_event = AnalyticsEvent(
        event_type="assignment",
        payload=EventPayload(
            user_id="user_123",
            experiment_id=1,
            variant_name="control"
        )
    )
    assert valid_event.payload.user_id == "user_123"

    with pytest.raises(ValidationError):
        AnalyticsEvent(
            event_type="conversion",
            payload={"user_id": ""}
        )
