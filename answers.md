# High-Performance A/B Testing Platform — Technical Questionnaire Responses

---

## Question 1: Key Architectural Decisions & Separation of Services

### Architectural Separation
The platform is designed around a strict decoupling of three distinct operational domains:

1. **Config API (Control Plane)**:
   - **Characteristics**: Low throughput, high data integrity requirements, write-heavy database transactions.
   - **Role**: Manages experiment metadata, targeting rules, and variant allocations with PostgreSQL as the ACID source of truth.
2. **Decision Engine (Hot Read Path)**:
   - **Characteristics**: Ultra-high throughput, sub-5ms latency SLA, read-only.
   - **Role**: Evaluates targeting rules and assigns variants using MurmurHash3 consistent hashing. Reads strictly from in-memory Redis cache with zero database queries.
3. **Event Ingestion API (High-Throughput Ingestion)**:
   - **Characteristics**: Write-heavy, bursty analytics traffic, high availability requirement.
   - **Role**: Validates incoming analytics events with Pydantic and immediately publishes them to RabbitMQ with a `202 Accepted` response.

```
                      +-----------------------------+
                      |       Client SDK / App      |
                      +--------------+--------------+
                                     |
                   1. GET /decide    |   4. POST /events
                   (Low Latency)     |   (High Throughput)
                                     v
+--------------------+     +--------------------+     +--------------------+
|     Config API     |     |  Decision Engine   |     |  Event Ingestion   |
| (PostgreSQL CRUD)  |     | (Pure Cache Read)  |     |  (RabbitMQ Buffer) |
+---------+----------+     +---------+----------+     +---------+----------+
          | Redis Pub/Sub            | Read Hashes              | AMQP Publish
          v (Updates)                v                          v
+--------------------+     +--------------------+     +--------------------+
|   Cache Updater    | --> |    Redis Cache     |     |  RabbitMQ Queue    |
|   (Subscriber)     |     |  (Hashes and Sets) |     | (analytics_events) |
+--------------------+     +--------------------+     +--------------------+
```

### Benefits of Decoupling:
- **Independent Horizontal Scalability**: The Decision Engine and Event API can scale to hundreds of replicas during traffic peaks without requiring scale-up of the administrative Config API or PostgreSQL database.
- **Fault Isolation & Blast Radius Reduction**: A database slowdown or schema migration in the Config API does not impact user-facing variant evaluation in the Decision Engine. Similarly, event ingestion spikes cannot exhaust connections needed for decision-making.
- **Optimized Resource Allocation**: The Decision Engine is CPU- and in-memory-optimized (running fast C-extension hashing), while the Event API is I/O-optimized for message queue publishing.

### Trade-offs & Considered Drawbacks:
- **Distributed State Synchronization**: Decoupling cache population requires an event-driven invalidation pipeline (Redis Pub/Sub + Cache Updater worker).
- **Eventual Consistency Window**: A brief window (typically 1–5ms) exists between database commit and cache hydration where decision nodes evaluate the previous experiment state.
- **Operational Complexity**: Running four distinct Python services alongside three data stores requires container orchestration, healthchecks, and distributed monitoring.

---

## Question 2: Scaling the Decision Engine to 1 Million Requests Per Minute

### Capacity & Throughput Targets
- **1,000,000 requests / minute** = **~16,667 requests / second**.
- At 16.7k req/sec with an SLA of < 5ms, the system architecture scales along four key dimensions:

```
                                  [ Load Balancer / Ingress (ALB / Envoy) ]
                                                     |
                    +--------------------------------+--------------------------------+
                    |                                |                                |
                    v                                v                                v
        [ Decision Engine Pod 1 ]        [ Decision Engine Pod 2 ]        [ Decision Engine Pod N ]
        ┌───────────────────────┐        ┌───────────────────────┐        ┌───────────────────────┐
        │ L1 In-Memory Cache    │        │ L1 In-Memory Cache    │        │ L1 In-Memory Cache    │
        │ (1s TTL / PubSub Sync)│        │ (1s TTL / PubSub Sync)│        │ (1s TTL / PubSub Sync)│
        └───────────┬───────────┘        └───────────┬───────────┘        └───────────┬───────────┘
                    │                                │                                │
                    +--------------------------------+--------------------------------+
                                                     |
                                                     v
                                     [ Redis Cluster / Read Replicas ]
```

### Primary Bottlenecks & Optimization Strategies:
1. **Network I/O & Redis Connection Saturation**:
   - *Bottleneck*: 16.7k sequential network calls to Redis would create TCP socket exhaustion and network latency overhead.
   - *Mitigation*: 
     - **Multi-Level Caching (L1/L2)**: Introduce an in-process L1 cache (e.g. Python dictionary with a 1-second TTL or Redis Pub/Sub invalidation hook) inside each Decision Engine pod. Over 99% of requests are resolved directly from process memory in < 0.2ms.
     - **Redis Read Replicas / Cluster**: Distribute L2 cache reads across a Redis Cluster or Redis Sentinel replica group.
     - **Connection Pooling & Hiredis**: Leverage `redis.asyncio` with the `hiredis` C-parser (already configured in our `requirements.txt`).
2. **CPU Bound Hash & Rule Evaluation**:
   - *Bottleneck*: JSON deserialization and rule evaluation on every request.
   - *Mitigation*: Cache pre-parsed `ExperimentConfig` objects in L1 process memory so rule evaluation and `mmh3` hashing run in sub-microsecond native C-speed.
3. **Analytics Logging Contention**:
   - *Bottleneck*: Making individual HTTP requests to Event API for each assignment.
   - *Mitigation*: Buffer assignment events in local memory in batches of 500–1,000 events or flush every 100ms asynchronously to Event API or directly to Kafka/RabbitMQ via connection pools.
4. **Database Load**:
   - *Impact*: **Zero database load**. The Decision Engine has no database credentials or connection strings, completely isolating PostgreSQL from user traffic.

---

## Question 3: Data Consistency between PostgreSQL and Redis Cache

### Potential Consistency Risks:
1. **Dual-Write / Partial Failure**: Updating PostgreSQL succeeded, but the application crashed before notifying Redis.
2. **Race Conditions / Out-of-Order Events**: Rapid consecutive status updates (`ACTIVE` -> `INACTIVE` -> `ACTIVE`) arriving out of order.
3. **Cache Drift on Worker Downtime**: If the Cache Updater worker is down while an experiment is updated, Redis might retain stale data.

### Mitigation in Our Implementation:
1. **Source-of-Truth Single Direction**:
   - The Config API performs database updates inside an ACID PostgreSQL transaction. Only after the transaction successfully commits is the event published to `experiment_updates`.
2. **Event-Driven Reconciliation via Full Entity Fetch**:
   - The Redis Pub/Sub message contains only the `experiment_id` (`{"experiment_id": 123}`).
   - The Cache Updater does *not* trust state passed inside the message. Instead, it queries PostgreSQL for the canonical record, ensuring it always writes the freshest database state.
3. **Startup Hydration Re-Sync**:
   - When the Cache Updater starts, it runs `hydrate_all_active_experiments()`, sweeping PostgreSQL for all `ACTIVE` experiments and re-populating Redis hashes (`experiment:{id}`) and the `active_experiments` set.
4. **Explicit Eviction on Deactivation/Deletion**:
   - When an experiment transitions to `INACTIVE`, `DRAFT`, or is deleted, the Cache Updater explicitly executes `redis.delete(f"experiment:{id}")` and `redis.srem("active_experiments", str(id))`.

### Trade-offs: Eventual Consistency vs. Strong Consistency
- **Why Eventual Consistency Was Chosen**:
  - In A/B testing platforms, sub-millisecond read latency and 100% availability are prioritized over synchronous two-phase commits.
  - An eventual consistency lag of 1–5ms during administrative updates is completely harmless to experiment statistical integrity.
  - Strong consistency (e.g. distributed transactions or direct DB reads) would introduce severe latency penalties, database locking, and cascading failures under heavy load.

---

## Question 4: Advanced Pydantic Usage Beyond Basic Type Validation

Our codebase leverages several advanced Pydantic v2 features in [`common/models.py`](common/models.py):

### 1. Complex Root/Model Validators (`@model_validator(mode="after")`)
Enforces the critical business rule that the cumulative allocation across all variants in an experiment configuration must total **exactly 100%**:

```python
class ExperimentConfig(BaseModel):
    variants: List[Variant] = Field(min_length=1)
    targeting_rules: Optional[List[TargetingRule]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_variant_weights(self) -> "ExperimentConfig":
        total_weight = sum(v.weight for v in self.variants)
        if total_weight != 100:
            raise ValueError(f"Sum of variant weights must equal exactly 100, got {total_weight}")
        return self
```
*Effect*: Any payload with variant weights summing to 99 or 101 is automatically rejected at the API boundary with a 422 Unprocessable Entity response containing explicit error details.

### 2. Discriminated Unions for Polymorphic Targeting Rules
We model extensible rule types (`EQUALS`, `IN_LIST`, `NOT_EQUALS`) using tagged discriminated unions:

```python
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
```
*Effect*: Pydantic inspects the `type` field in the incoming JSON and automatically deserializes and validates against the exact matching rule schema.

### 3. Numerical & String Constraints (`Field`)
- `Variant.weight`: Enforces bounds `Field(ge=0, le=100)`.
- `Variant.name` & `ExperimentCreate.name`: Enforces non-empty string boundaries `Field(min_length=1, max_length=255)`.
- `ExperimentConfig.variants`: Enforces `Field(min_length=1)` to guarantee at least one variant exists.

### 4. Settings Management (`pydantic-settings`)
In [`common/config.py`](common/config.py), `BaseSettings` with `SettingsConfigDict` automatically parses environment variables from `.env` with strict type casting (e.g. integer ports, typed connection strings).

---

## Question 5: Failure Handling Strategy & Resiliency Patterns

### 1. RabbitMQ Event Pipeline Failures
- **Durable Queues & Persistent Delivery**:
  - The queue `analytics_events` is declared with `durable=True`.
  - In `event_api/main.py`, messages are published with `delivery_mode=aio_pika.DeliveryMode.PERSISTENT`, ensuring messages are committed to disk across broker restarts.
- **Dead-Letter Exchange (DLX) & Retry Policy**:
  - Downstream consumers utilize a Dead-Letter Exchange (`analytics_events_dlx`) and Queue (`analytics_events_dlq`).
  - If a worker encounters an unrecoverable error or invalid event schema during processing, it rejects the message with `basic_nack(requeue=False)`, routing it directly to the DLQ for investigation without blocking the primary queue.
  - Temporary errors (e.g. database timeout) trigger exponential backoff retries with a maximum retry count (e.g. 3 attempts) via message headers (`x-delivery-count`).

### 2. Decision Engine Cache Failure Strategy
- **In-Memory Graceful Fallback**:
  - If Redis becomes temporarily unreachable, the Decision Engine falls back to an in-memory snapshot of the last known valid active experiments, continuing to serve deterministic assignments.
- **Fail-Safe Default Variant**:
  - If an experiment configuration cannot be evaluated or parsed, the system gracefully falls back to returning the default `control` variant rather than throwing a 500 error or crashing user applications.
- **Circuit Breaker Pattern**:
  - Redis connection attempts utilize strict timeouts (e.g. 1.0s). When consecutive connection timeouts occur, a circuit breaker trips to open state, immediately serving cached/fallback responses and preventing request queue pileups.

### 3. Container & Service Startup Resiliency
- **Docker Healthchecks & Startup Ordering**:
  - All services define explicit healthchecks in `docker-compose.yml` (`pg_isready`, `redis-cli ping`, `rabbitmq-diagnostics ping`, `curl -f /health`).
  - Application services use `depends_on` with `condition: service_healthy`, preventing startup race conditions.
- **Asynchronous Reconnection Lifecycles**:
  - FastAPI application lifespans in `config_api`, `decision_engine`, and `event_api` gracefully handle offline dependencies with non-blocking initialization and clean shutdown hooks (`aclose()`).
