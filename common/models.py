from datetime import datetime
from enum import Enum
from typing import Any, List, Literal, Optional, Union, Annotated
from pydantic import BaseModel, Field, model_validator


class ExperimentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BaseRule(BaseModel):
    attribute: str


class EqualsRule(BaseRule):
    type: Literal["EQUALS"] = "EQUALS"
    value: Any


class InListRule(BaseRule):
    type: Literal["IN_LIST"] = "IN_LIST"
    value: List[Any]


class NotEqualsRule(BaseRule):
    type: Literal["NOT_EQUALS"] = "NOT_EQUALS"
    value: Any


TargetingRule = Annotated[
    Union[EqualsRule, InListRule, NotEqualsRule],
    Field(discriminator="type")
]


class Variant(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    weight: int = Field(ge=0, le=100)


class ExperimentConfig(BaseModel):
    variants: List[Variant] = Field(min_length=1)
    targeting_rules: Optional[List[TargetingRule]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_variant_weights(self) -> "ExperimentConfig":
        total_weight = sum(v.weight for v in self.variants)
        if total_weight != 100:
            raise ValueError(f"Sum of variant weights must equal exactly 100, got {total_weight}")
        return self


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    config: ExperimentConfig


class ExperimentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    config: Optional[ExperimentConfig] = None


class StatusUpdate(BaseModel):
    status: ExperimentStatus


class ExperimentResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    status: str
    config: ExperimentConfig
    created_at: datetime
    updated_at: datetime


class EventPayload(BaseModel):
    user_id: str = Field(min_length=1)
    experiment_id: int
    variant_name: str = Field(min_length=1)


class AnalyticsEvent(BaseModel):
    event_type: str = Field(min_length=1)
    payload: EventPayload
    timestamp: Optional[datetime] = None


class DecisionResponse(BaseModel):
    experiment_id: int
    experiment_name: str
    variant: str
    assigned: bool = True


class DecisionResult(BaseModel):
    user_id: str
    decisions: List[DecisionResponse]
