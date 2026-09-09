# 📚 Project Technical Documentation & Manual

## 1. Executive Summary & Problem Statement

Modern technology organizations require continuous data-driven experimentation to optimize user interfaces, recommendation algorithms, and conversion funnels. Traditional monolithic experimentation tools frequently suffer from:
- **High latency**: Database queries inside the critical user render path.
- **Inconsistent assignment**: Flaky user assignments causing poor user experience and invalid statistical results.
- **Write contention**: Database locks caused by concurrent analytics logging.

This project delivers an enterprise-grade backend architecture resolving all three challenges through **Pydantic data modeling, Redis in-memory cache reads, MurmurHash3 consistent hashing, and RabbitMQ message buffering**.

---

## 2. Data Models & Validation Schemas

### 2.1 Experiment & Variant Validation Rules

The platform enforces strict business rules defined via Pydantic v2:
1. **Variant Weight Sum Rule**: The sum of `weight` across all variants in an experiment configuration must equal **exactly 100**. Any payload with sum 99 or 101 is rejected with HTTP `422 Unprocessable Entity`.
2. **Discriminated Union Targeting Rules**: Targeting rules use discriminated union dispatching based on the `type` field (`EQUALS`, `IN_LIST`, `NOT_EQUALS`).

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

### 2.2 PostgreSQL Database Schema
```sql
CREATE TABLE IF NOT EXISTS experiments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
    config JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

---

## 3. Deterministic Assignment Algorithm (MurmurHash3)

To ensure that user $u$ always receives variant $v$ in experiment $e$ across multiple requests without requiring database persistence:

1. **Composite Key**: $K = \text{user\_id} : \text{experiment\_id}$
2. **Hash Value**: $H = \text{MurmurHash3}(K, \text{seed}=0, \text{signed}=\text{False})$
3. **Bucket**: $B = H \pmod{100} \in [0, 99]$
4. **Cumulative Weight Mapping**:
   Given variants $V_1, V_2, \dots, V_k$ with weights $W_1, W_2, \dots, W_k$ ($\sum W_i = 100$):
   $$v = V_m \quad \text{where} \quad \sum_{i=1}^{m-1} W_i \le B < \sum_{i=1}^{m} W_i$$

### Edge Case Verification:
- **100% Control ($W_c = 100, W_t = 0$)**: Cumulative weight for Control is 100. Since $B \in [0, 99]$, $B < 100$ always holds, yielding **100% Control**.
- **100% Treatment ($W_c = 0, W_t = 100$)**: Control weight is 0. Cumulative weight reaches 100 at Treatment, yielding **100% Treatment**.

---

## 4. Complete API Endpoint Specification

### 4.1 Configuration API (Port `8001`)

#### `POST /experiments`
- **Status**: `201 Created`
- **Request Body**:
  ```json
  {
    "name": "checkout_button_color",
    "description": "Test green vs blue button conversion",
    "config": {
      "variants": [
        {"name": "control", "weight": 50},
        {"name": "treatment", "weight": 50}
      ],
      "targeting_rules": [
        {"type": "EQUALS", "attribute": "country", "value": "US"}
      ]
    }
  }
  ```
- **Response**: Full experiment object with generated `id` and status `DRAFT`.

#### `POST /experiments/{id}/status`
- **Status**: `200 OK`
- **Request Body**: `{"status": "ACTIVE"}`
- **Side Effect**: Publishes `{"experiment_id": id}` to Redis channel `experiment_updates`.

---

### 4.2 Decision Engine (Port `8002`)

#### `GET /decide`
- **Query Parameters**:
  - `user_id`: string (required)
  - `attributes`: JSON-encoded string (optional, e.g. `{"country": "US"}`)
- **Latency**: `< 5ms`
- **Response (200 OK)**:
  ```json
  {
    "user_id": "user_123",
    "decisions": [
      {
        "experiment_id": 1,
        "experiment_name": "checkout_button_color",
        "variant": "control",
        "assigned": true
      }
    ]
  }
  ```

---

### 4.3 Event Ingestion API (Port `8000`)

#### `POST /events`
- **Status**: `202 Accepted`
- **Request Body**:
  ```json
  {
    "event_type": "conversion",
    "payload": {
      "user_id": "user_123",
      "experiment_id": 1,
      "variant_name": "control"
    }
  }
  ```
- **Side Effect**: Serializes event and publishes to RabbitMQ queue `analytics_events`.

---

## 5. Verification & Test Evidence

```
============================================================
STARTING END-TO-END VERIFICATION
============================================================

[1/8] Verifying Health Endpoints...
  ✓ Config API is healthy ({'status': 'healthy', 'service': 'config_api'})
  ✓ Decision Engine is healthy ({'status': 'healthy', 'service': 'decision_engine'})
  ✓ Event API is healthy ({'status': 'healthy', 'service': 'event_api'})

[2/8] Verifying Seeded Experiment against submission.json...
  ✓ Seeded experiment verified: ID 1, Name 'checkout_button_color', Status: ACTIVE

[3/8] Verifying Redis Cache Hydration...
  ✓ Redis cache verified: Hash 'experiment:1' found with status 'ACTIVE'

[4/8] Testing Decision Engine Latency (< 50ms across 100 requests)...
  ✓ 100 requests completed successfully. Average latency: 2.84 ms (Target < 50ms)

[5/8] Testing Pydantic Weight Sum Validation...
  ✓ Correctly rejected weight sum 99 and 101 with 422 Unprocessable Entity

[6/8] Testing Experiment Creation, Activation, and Deterministic Assignment...
  ✓ Created experiment in DRAFT status
  ✓ Assigned variant: control (100% control allocation)
  ✓ Updated assignment: treatment (100% treatment allocation via Redis Pub/Sub hydration)

[7/8] Testing Event Ingestion API...
  ✓ Invalid event payload returned 422 Unprocessable Entity

[8/8] Testing RabbitMQ Event Publishing (Requirement 12)...
  ✓ Event ingested with 202 Accepted
  ✓ Exactly matched message verified from RabbitMQ queue 'analytics_events'

============================================================
ALL END-TO-END TESTS PASSED 100% SUCCESSFULLY! 🚀
============================================================
```
