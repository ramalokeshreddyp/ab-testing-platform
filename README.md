# 🚀 High-Performance A/B Testing Platform

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2.6+-E92063?style=for-the-badge&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![Redis](https://img.shields.io/badge/Redis-7.0-DC382D?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io/)
[![RabbitMQ](https://img.shields.io/badge/RabbitMQ-3.12-FF6600?style=for-the-badge&logo=rabbitmq&logoColor=white)](https://www.rabbitmq.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15.0-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Pylint](https://img.shields.io/badge/Pylint-10.00%2F10.00-4CAF50?style=for-the-badge)](https://pylint.pycqa.org/)
[![Tests](https://img.shields.io/badge/Tests-18%2F18%20Passed-brightgreen?style=for-the-badge)](https://pytest.org/)

An enterprise-grade, distributed **A/B Testing and Feature Experimentation Platform** engineered for **sub-5ms decision latency**, real-time cache hydration via Redis Pub/Sub, and high-throughput asynchronous event ingestion powered by RabbitMQ.

---

## 🌟 Key Capabilities

- **⚡ Sub-5ms Decision Engine**: Pure in-memory cache reads from Redis with zero database bottleneck during high-traffic evaluation.
- **🛡️ Strict Pydantic v2 Modeling**: Automatic data integrity validation enforcing 100% traffic weight sums and discriminated union targeting rules.
- **🔄 Real-Time Cache Invalidation**: Asynchronous Redis Pub/Sub events dispatch instant cache hydration/eviction across cluster nodes.
- **🎯 Deterministic Assignment**: MurmurHash3 consistent hashing guarantees user consistency across visits without storing user session states.
- **📥 Durable Event Ingestion**: High-throughput analytics endpoint returning `202 Accepted` immediately while publishing events to RabbitMQ.
- **🐳 Full Containerization**: One-command reproducible local and production deployment via Docker Compose with healthchecks on all services.

---

## 🏛 System Architecture

```mermaid
flowchart TB
    subgraph Clients["Client Layer"]
        SDK["Client SDK / Frontend App"]
    end

    subgraph UserFacing["High-Throughput User Services"]
        DE["Decision Engine (Port 8002)
• Sub-5ms Decision API
• Pure Cache Read
• MurmurHash3 Assignment"]
        EV["Event Ingestion API (Port 8000)
• High Throughput Endpoint
• 202 Accepted Response"]
    end

    subgraph Management["Control Plane"]
        API["Config API (Port 8001)
• Experiment CRUD
• Pydantic v2 Validation
• Status Activation"]
    end

    subgraph StorageLayer["Data and Messaging Layer"]
        DB[("PostgreSQL
experiments Table")]
        PUB["Redis Pub/Sub
(experiment_updates)"]
        CACHE[("Redis Cache
experiment:{id} Hashes")]
        QUEUE["RabbitMQ Queue
(analytics_events)"]
        WORKER["Cache Updater Worker
• Async Background Subscriber
• Cache Hydration and Eviction"]
    end

    SDK -->|1. GET /decide| DE
    SDK -->|4. POST /events| EV
    API -->|SQL Read/Write| DB
    API -->|2. Broadcast Activation| PUB
    PUB -->|Listen for Updates| WORKER
    WORKER -->|Fetch Config| DB
    WORKER -->|3. Hydrate Hash and Set| CACHE
    DE -->|Read In-Memory| CACHE
    DE -.->|Async Non-blocking Log| EV
    EV -->|Publish Event| QUEUE
```

---

## 🔄 End-to-End Execution Flows

### 1. User Variant Decision Flow (`GET /decide`)
```mermaid
sequenceDiagram
    autonumber
    actor User as Client Application
    participant DE as Decision Engine (FastAPI)
    participant Redis as Redis In-Memory Cache
    participant EV as Event Ingestion API
    participant RMQ as RabbitMQ (analytics_events)

    User->>DE: GET /decide?user_id=usr_99&attributes={"country":"US"}
    activate DE
    DE->>Redis: SMEMBERS active_experiments
    Redis-->>DE: ["1", "2"]
    DE->>Redis: Pipeline HGETALL experiment:1, experiment:2
    Redis-->>DE: Experiment Configurations
    Note over DE: 1. Evaluate Targeting Rules (country == US)<br/>2. Compute MurmurHash3(user_id:exp_id) % 100<br/>3. Match Variant Bucket
    DE->>User: 200 OK {"user_id": "usr_99", "decisions": [{"variant": "treatment"}]}
    DE--)EV: Non-blocking POST /events (Assignment Log)
    deactivate DE
    activate EV
    EV->>RMQ: Publish Message to 'analytics_events'
    EV-->>DE: 202 Accepted
    deactivate EV
```

### 2. Experiment Lifecycle & Real-Time Cache Update Flow
```mermaid
sequenceDiagram
    autonumber
    actor Admin as Experiment Manager
    participant Config as Config API (Port 8001)
    participant DB as PostgreSQL Database
    participant PubSub as Redis Pub/Sub (experiment_updates)
    participant Worker as Cache Updater Worker
    participant Cache as Redis Hash Store

    Admin->>Config: POST /experiments (Create with Variants sum = 100)
    Config->>DB: INSERT INTO experiments (status='DRAFT')
    Config-->>Admin: 201 Created (id=1, status='DRAFT')

    Admin->>Config: POST /experiments/1/status {"status": "ACTIVE"}
    Config->>DB: UPDATE experiments SET status='ACTIVE'
    Config->>PubSub: PUBLISH experiment_updates {"experiment_id": 1}
    Config-->>Admin: 200 OK

    Worker->>PubSub: Receive {"experiment_id": 1}
    Worker->>DB: SELECT * FROM experiments WHERE id=1
    Worker->>Cache: HSET experiment:1 {id, name, config, status}
    Worker->>Cache: SADD active_experiments 1
```

---

## 🗂 Code Structure & Organization

```
.
├── .env.example              # Environment variables template
├── .gitignore                # Virtualenv and temporary files exclusion
├── .pylintrc                 # Pylint configuration (10.00/10.00 score)
├── docker-compose.yml        # Orchestrates all 7 services with healthchecks
├── requirements.txt          # Production Python dependencies
├── submission.json           # Automated evaluation seed metadata
├── README.md                 # Primary system overview and user guide
├── architecture.md           # Deep architectural specification
├── projectdocumentation.md   # Complete technical manual and API reference
├── scripts/
│   ├── init_db.sql           # Database schema and seed data
│   └── e2e_test.py           # Live end-to-end verification script
├── common/                   # Shared microservices library
│   ├── __init__.py
│   ├── config.py             # Centralized Pydantic settings
│   ├── models.py             # Pydantic v2 schemas and validators
│   └── hashing.py            # MurmurHash3 consistent assignment algorithm
├── config_api/               # Configuration API microservice (Port 8001)
│   ├── __init__.py
│   ├── database.py           # Async SQLAlchemy ORM and session pool
│   ├── main.py               # REST endpoints for experiment CRUD
│   └── Dockerfile
├── cache_updater/            # Redis Pub/Sub Cache Updater worker
│   ├── __init__.py
│   ├── main.py               # Background listener and cache sync worker
│   └── Dockerfile
├── decision_engine/          # Ultra-low latency decision API (Port 8002)
│   ├── __init__.py
│   ├── main.py               # Cache-only evaluation and non-blocking logging
│   └── Dockerfile
├── event_api/                # High-throughput event ingestion API (Port 8000)
│   ├── __init__.py
│   ├── main.py               # RabbitMQ asynchronous producer
│   └── Dockerfile
└── tests/                    # Unit and integration test suite
    ├── __init__.py
    ├── test_models.py        # Pydantic validation tests
    ├── test_hashing.py       # Deterministic assignment and targeting tests
    └── test_apis.py          # API route and error status tests
```

---

## 🚀 Quick Start & Local Execution

### Prerequisites
- [Docker Engine and Docker Compose](https://docs.docker.com/get-docker/)
- [Python 3.11+](https://www.python.org/)

### 1. Clone & Configure
```bash
git clone https://github.com/ramalokeshreddyp/ab-testing-platform.git
cd ab-testing-platform
cp .env.example .env
```

### 2. Start the Distributed Stack
```bash
docker-compose up -d --build
```
All containers will start and reach `healthy` status automatically:
- `ab_testing_db` (PostgreSQL on port `5432`)
- `ab_testing_cache` (Redis on port `6379`)
- `ab_testing_queue` (RabbitMQ on ports `5672`, `15672`)
- `ab_testing_config_api` (FastAPI on port `8001`)
- `ab_testing_cache_updater` (Background Worker)
- `ab_testing_decision_engine` (FastAPI on port `8002`)
- `ab_testing_event_api` (FastAPI on port `8000`)

---

## 🧪 Testing & Quality Assurance

### Run Unit and Integration Tests
```bash
# Setup virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run pytest suite
pytest tests/ -v
```

### Run Pylint Code Quality Check
```bash
pylint --rcfile=.pylintrc common config_api cache_updater decision_engine event_api tests
# Output: Your code has been rated at 10.00/10
```

### Run Live End-to-End System Test
```bash
python scripts/e2e_test.py
```

---

## 📖 API Documentation & Examples

| Service | Port | Endpoint | Method | Description |
|---|---|---|---|---|
| **Config API** | `8001` | `/experiments` | `POST` | Create new experiment (requires variants weight sum = 100) |
| **Config API** | `8001` | `/experiments/{id}/status` | `POST` | Update status (`ACTIVE`/`INACTIVE`) and trigger cache sync |
| **Config API** | `8001` | `/experiments` | `GET` | List all experiments |
| **Decision Engine** | `8002` | `/decide` | `GET` | Get variant assignments for `user_id` (< 5ms) |
| **Event API** | `8000` | `/events` | `POST` | Ingest conversion/assignment events to RabbitMQ (`202 Accepted`) |

For comprehensive architectural design and technical details, please see:
- [architecture.md](architecture.md)
- [projectdocumentation.md](projectdocumentation.md)
