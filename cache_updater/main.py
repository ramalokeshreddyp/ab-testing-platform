import asyncio
import json
import logging
import sys
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from common.config import settings
from config_api.database import ExperimentModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [CacheUpdater] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("CacheUpdater")

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def sync_experiment_to_cache(experiment_id: int, redis_client: aioredis.Redis) -> None:
    async with AsyncSessionLocal() as session:
        stmt = select(ExperimentModel).where(ExperimentModel.id == experiment_id)
        result = await session.execute(stmt)
        experiment = result.scalar_one_or_none()

    cache_key = f"experiment:{experiment_id}"

    if experiment is not None and experiment.status == "ACTIVE":
        config_data = experiment.config
        config_str = json.dumps(config_data) if isinstance(config_data, (dict, list)) else str(config_data)
        mapping = {
            "id": str(experiment.id),
            "name": str(experiment.name),
            "description": str(experiment.description or ""),
            "status": str(experiment.status),
            "config": config_str
        }
        await redis_client.hset(cache_key, mapping=mapping)
        await redis_client.sadd("active_experiments", str(experiment.id))
        logger.info("Cached ACTIVE experiment: %s (id: %d)", experiment.name, experiment.id)
    else:
        await redis_client.delete(cache_key)
        await redis_client.srem("active_experiments", str(experiment_id))
        logger.info("Removed experiment id %d from cache", experiment_id)


async def hydrate_all_active_experiments(redis_client: aioredis.Redis) -> None:
    logger.info("Hydrating all active experiments from database to Redis...")
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(ExperimentModel)
            result = await session.execute(stmt)
            experiments = result.scalars().all()

        for exp in experiments:
            await sync_experiment_to_cache(exp.id, redis_client)
        logger.info("Initial cache hydration complete.")
    except Exception as exc:
        logger.warning("Initial hydration delayed: %s", exc)


async def run_cache_updater():
    logger.info("Starting Cache Updater worker...")
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()

    connected = False
    for attempt in range(1, 30):
        try:
            await redis_client.ping()
            await pubsub.subscribe(settings.REDIS_CHANNEL)
            logger.info("Subscribed to Redis channel: %s", settings.REDIS_CHANNEL)
            connected = True
            break
        except Exception as exc:
            logger.info("Waiting for Redis connection (attempt %d/30): %s", attempt, exc)
            await asyncio.sleep(2)

    if not connected:
        logger.error("Could not connect to Redis. Exiting.")
        return

    await hydrate_all_active_experiments(redis_client)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                logger.info("Received update message: %s", data)
                try:
                    payload = json.loads(data)
                    experiment_id = payload.get("experiment_id")
                    if experiment_id is not None:
                        await sync_experiment_to_cache(int(experiment_id), redis_client)
                except Exception as parse_err:
                    logger.error("Error processing message %s: %s", data, parse_err)
    except asyncio.CancelledError:
        logger.info("Cache updater loop cancelled.")
    finally:
        await pubsub.unsubscribe(settings.REDIS_CHANNEL)
        await redis_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_cache_updater())
