import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, List, Optional, Any
from fastapi import FastAPI, Query, status, HTTPException
import httpx
import redis.asyncio as aioredis

from common.config import settings
from common.models import (
    ExperimentConfig,
    DecisionResponse,
    DecisionResult
)
from common.hashing import assign_variant, evaluate_targeting

logger = logging.getLogger("DecisionEngine")

redis_client: Optional[aioredis.Redis] = None
http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncGenerator[None, None]:
    global redis_client, http_client
    try:
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as exc:
        logger.warning("Redis not immediately available: %s", exc)

    http_client = httpx.AsyncClient(timeout=2.0)
    yield
    if redis_client is not None:
        try:
            await redis_client.close()
        except Exception:
            pass
    if http_client is not None:
        try:
            await http_client.aclose()
        except Exception:
            pass


app = FastAPI(
    title="A/B Testing Decision Engine",
    version="1.0.0",
    description="High-performance, low-latency decision service reading strictly from Redis cache.",
    lifespan=lifespan
)


async def send_assignment_event(user_id: str, experiment_id: int, variant_name: str) -> None:
    if http_client is None:
        return
    try:
        event = {
            "event_type": "assignment",
            "payload": {
                "user_id": user_id,
                "experiment_id": experiment_id,
                "variant_name": variant_name
            }
        }
        await http_client.post(settings.EVENT_API_URL, json=event)
    except Exception:
        pass


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "healthy", "service": "decision_engine"}


@app.get("/decide", response_model=DecisionResult, status_code=status.HTTP_200_OK)
async def decide(
    user_id: str = Query(..., min_length=1, description="Unique identifier for the user"),
    attributes: Optional[str] = Query(None, description="JSON-encoded string of user attributes")
):
    if redis_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache connection is unavailable."
        )

    user_attrs: Dict[str, Any] = {}
    if attributes:
        try:
            user_attrs = json.loads(attributes)
            if not isinstance(user_attrs, dict):
                user_attrs = {}
        except Exception:
            user_attrs = {}

    active_exp_ids = await redis_client.smembers("active_experiments")
    decisions: List[DecisionResponse] = []

    if active_exp_ids:
        async with redis_client.pipeline(transaction=False) as pipe:
            for exp_id in active_exp_ids:
                pipe.hgetall(f"experiment:{exp_id}")
            results = await pipe.execute()

        for exp_data in results:
            if not exp_data or exp_data.get("status") != "ACTIVE":
                continue

            try:
                exp_id = int(exp_data.get("id"))
                exp_name = exp_data.get("name", f"experiment_{exp_id}")
                config_raw = exp_data.get("config")
                if not config_raw:
                    continue

                config_dict = json.loads(config_raw) if isinstance(config_raw, str) else config_raw
                config = ExperimentConfig.model_validate(config_dict)

                if not evaluate_targeting(config.targeting_rules, user_attrs):
                    continue

                assigned = assign_variant(user_id, exp_id, config.variants)
                if assigned:
                    decisions.append(
                        DecisionResponse(
                            experiment_id=exp_id,
                            experiment_name=exp_name,
                            variant=assigned,
                            assigned=True
                        )
                    )
                    asyncio.create_task(send_assignment_event(user_id, exp_id, assigned))
            except Exception as parse_err:
                logger.warning("Error processing cached experiment: %s", parse_err)
                continue

    return DecisionResult(user_id=user_id, decisions=decisions)
