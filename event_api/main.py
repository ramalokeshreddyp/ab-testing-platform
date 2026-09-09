import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from fastapi import FastAPI, status, HTTPException
import aio_pika

from common.config import settings
from common.models import AnalyticsEvent

logger = logging.getLogger("EventAPI")

connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
channel: Optional[aio_pika.abc.AbstractRobustChannel] = None
queue: Optional[aio_pika.abc.AbstractQueue] = None


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncGenerator[None, None]:
    global connection, channel, queue
    try:
        connection = await aio_pika.connect_robust(settings.RABBITMQ_URL, timeout=1.0)
        channel = await connection.channel()
        queue = await channel.declare_queue(
            settings.RABBITMQ_QUEUE,
            durable=True
        )
        logger.info("Connected to RabbitMQ and declared queue: %s", settings.RABBITMQ_QUEUE)
    except Exception as exc:
        logger.warning("RabbitMQ not immediately available: %s", exc)

    yield

    if channel is not None and not channel.is_closed:
        try:
            await channel.close()
        except Exception:
            pass
    if connection is not None and not connection.is_closed:
        try:
            await connection.close()
        except Exception:
            pass


app = FastAPI(
    title="A/B Testing Event Ingestion API",
    version="1.0.0",
    description="High-throughput asynchronous event ingestion publishing directly to RabbitMQ.",
    lifespan=lifespan
)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "healthy", "service": "event_api"}


@app.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(event: AnalyticsEvent):
    if channel is None or channel.is_closed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event queue service is currently unavailable."
        )

    try:
        message_body = json.dumps(event.model_dump(mode="json")).encode("utf-8")
        message = aio_pika.Message(
            body=message_body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        )
        await channel.default_exchange.publish(
            message,
            routing_key=settings.RABBITMQ_QUEUE
        )
        return {"status": "accepted", "detail": "Event queued for processing."}
    except Exception as exc:
        logger.error("Failed to publish event to RabbitMQ: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue event."
        ) from exc
