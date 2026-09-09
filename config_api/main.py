import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, List
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as aioredis

from common.config import settings
from common.models import (
    ExperimentCreate,
    ExperimentUpdate,
    ExperimentResponse,
    StatusUpdate,
    ExperimentStatus
)
from config_api.database import get_db, ExperimentModel, Base, engine

logger = logging.getLogger("ConfigAPI")
redis_pool: aioredis.Redis = None


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncGenerator[None, None]:
    global redis_pool
    try:
        redis_pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        logger.warning("Database or Redis not immediately available at startup: %s", exc)

    yield

    if redis_pool is not None:
        try:
            await redis_pool.close()
        except Exception:
            pass
    try:
        await engine.dispose()
    except Exception:
        pass


app = FastAPI(
    title="A/B Testing Configuration API",
    version="1.0.0",
    description="Manage A/B testing experiment definitions and lifecycle.",
    lifespan=lifespan
)


async def publish_experiment_update(experiment_id: int) -> None:
    if redis_pool is not None:
        try:
            payload = json.dumps({"experiment_id": experiment_id})
            await redis_pool.publish(settings.REDIS_CHANNEL, payload)
        except Exception:
            pass


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "healthy", "service": "config_api"}


@app.post(
    "/experiments",
    response_model=ExperimentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new experiment"
)
async def create_experiment(
    payload: ExperimentCreate,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ExperimentModel).where(ExperimentModel.name == payload.name)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Experiment with name '{payload.name}' already exists."
        )

    experiment = ExperimentModel(
        name=payload.name,
        description=payload.description,
        status=ExperimentStatus.DRAFT.value,
        config=payload.config.model_dump()
    )
    db.add(experiment)
    await db.commit()
    await db.refresh(experiment)
    return experiment


@app.get(
    "/experiments",
    response_model=List[ExperimentResponse],
    summary="List all experiments"
)
async def list_experiments(db: AsyncSession = Depends(get_db)):
    stmt = select(ExperimentModel).order_by(ExperimentModel.id.asc())
    result = await db.execute(stmt)
    return result.scalars().all()


@app.get(
    "/experiments/{experiment_id}",
    response_model=ExperimentResponse,
    summary="Get experiment by ID"
)
async def get_experiment(
    experiment_id: int,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ExperimentModel).where(ExperimentModel.id == experiment_id)
    result = await db.execute(stmt)
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment with ID {experiment_id} not found."
        )
    return experiment


@app.patch(
    "/experiments/{experiment_id}",
    response_model=ExperimentResponse,
    summary="Update an experiment"
)
async def update_experiment(
    experiment_id: int,
    payload: ExperimentUpdate,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ExperimentModel).where(ExperimentModel.id == experiment_id)
    result = await db.execute(stmt)
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment with ID {experiment_id} not found."
        )

    if payload.name is not None and payload.name != experiment.name:
        name_check = await db.execute(
            select(ExperimentModel).where(ExperimentModel.name == payload.name)
        )
        if name_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Experiment with name '{payload.name}' already exists."
            )
        experiment.name = payload.name

    if payload.description is not None:
        experiment.description = payload.description

    if payload.config is not None:
        experiment.config = payload.config.model_dump()

    await db.commit()
    await db.refresh(experiment)

    if experiment.status == ExperimentStatus.ACTIVE.value:
        await publish_experiment_update(experiment.id)

    return experiment


@app.delete(
    "/experiments/{experiment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an experiment"
)
async def delete_experiment(
    experiment_id: int,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ExperimentModel).where(ExperimentModel.id == experiment_id)
    result = await db.execute(stmt)
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment with ID {experiment_id} not found."
        )

    await db.delete(experiment)
    await db.commit()
    await publish_experiment_update(experiment_id)
    return None


@app.post(
    "/experiments/{experiment_id}/status",
    response_model=ExperimentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update experiment status"
)
async def update_experiment_status(
    experiment_id: int,
    payload: StatusUpdate,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ExperimentModel).where(ExperimentModel.id == experiment_id)
    result = await db.execute(stmt)
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment with ID {experiment_id} not found."
        )

    experiment.status = payload.status.value
    await db.commit()
    await db.refresh(experiment)

    await publish_experiment_update(experiment.id)
    return experiment
