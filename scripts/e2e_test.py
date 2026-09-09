import time
import json
import httpx
import redis
import pika

print("=" * 60)
print("STARTING END-TO-END VERIFICATION")
print("=" * 60)

client = httpx.Client(timeout=5.0)

# 1. Health Checks
print("\n[1/8] Verifying Health Endpoints...")
for name, url in [
    ("Config API", "http://localhost:8001/health"),
    ("Decision Engine", "http://localhost:8002/health"),
    ("Event API", "http://localhost:8000/health")
]:
    res = client.get(url)
    assert res.status_code == 200, f"{name} health check failed: {res.status_code}"
    print(f"  ? {name} is healthy ({res.json()})")

# 2. Verify Seeded Experiment & submission.json
print("\n[2/8] Verifying Seeded Experiment against submission.json...")
with open("submission.json", "r") as f:
    submission_data = json.load(f)
seeded = submission_data["seeded_experiment"]
res = client.get(f"http://localhost:8001/experiments/{seeded['id']}")
assert res.status_code == 200, f"Failed to get seeded experiment: {res.status_code}"
exp_data = res.json()
assert exp_data["name"] == seeded["name"], f"Name mismatch: {exp_data['name']} vs {seeded['name']}"
assert exp_data["status"] == "ACTIVE"
print(f"  ? Seeded experiment verified: ID {exp_data['id']}, Name '{exp_data['name']}', Status: {exp_data['status']}")

# 3. Verify Redis Cache Hydration
print("\n[3/8] Verifying Redis Cache Hydration...")
r = redis.Redis(host="localhost", port=6379, decode_responses=True)
cached = r.hgetall(f"experiment:{seeded['id']}")
assert cached, f"Experiment {seeded['id']} not found in Redis cache!"
assert cached["name"] == seeded["name"]
active_set = r.smembers("active_experiments")
assert str(seeded["id"]) in active_set
print(f"  ? Redis cache verified: Hash 'experiment:{seeded['id']}' found with status '{cached['status']}'")

# 4. Decision Engine Latency (< 50ms across 100 requests)
print("\n[4/8] Testing Decision Engine Latency (< 50ms across 100 requests)...")
times = []
for i in range(100):
    start = time.perf_counter()
    res = client.get("http://localhost:8002/decide", params={"user_id": f"user_bench_{i}", "attributes": json.dumps({"country": "US"})})
    elapsed_ms = (time.perf_counter() - start) * 1000
    times.append(elapsed_ms)
    assert res.status_code == 200, f"Request {i} failed: {res.status_code}"

avg_latency = sum(times) / len(times)
print(f"  ? 100 requests completed successfully. Average latency: {avg_latency:.2f} ms (Target < 50ms)")
assert avg_latency < 50.0, f"Latency exceeded 50ms: {avg_latency:.2f}ms"

# 5. Pydantic Validation on Experiment Weights (Sum = 100)
print("\n[5/8] Testing Pydantic Weight Sum Validation...")
res_99 = client.post("http://localhost:8001/experiments", json={
    "name": "invalid_exp_99",
    "config": {
        "variants": [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 49}],
        "targeting_rules": []
    }
})
assert res_99.status_code == 422, f"Expected 422 for sum 99, got {res_99.status_code}"
res_101 = client.post("http://localhost:8001/experiments", json={
    "name": "invalid_exp_101",
    "config": {
        "variants": [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 51}],
        "targeting_rules": []
    }
})
assert res_101.status_code == 422, f"Expected 422 for sum 101, got {res_101.status_code}"
print("  ? Correctly rejected weight sum 99 and 101 with 422 Unprocessable Entity")

# 6. Full Experiment Lifecycle & Dynamic Deterministic Hashing
print("\n[6/8] Testing Experiment Creation, Activation, and Deterministic Assignment...")
# Create experiment with 100% control
new_exp = client.post("http://localhost:8001/experiments", json={
    "name": "test_e2e_lifecycle_unique",
    "description": "E2E lifecycle test",
    "config": {
        "variants": [{"name": "control", "weight": 100}, {"name": "treatment", "weight": 0}],
        "targeting_rules": [{"type": "EQUALS", "attribute": "env", "value": "prod"}]
    }
}).json()
exp_id = new_exp["id"]
assert new_exp["status"] == "DRAFT"
print(f"  ? Created experiment {exp_id} in DRAFT status")

# Activate experiment
client.post(f"http://localhost:8001/experiments/{exp_id}/status", json={"status": "ACTIVE"})
time.sleep(1.0) # Allow cache updater to process pub/sub

# Query decision engine
decision_res = client.get("http://localhost:8002/decide", params={"user_id": "user_alpha", "attributes": json.dumps({"env": "prod"})}).json()
user_decisions = [d for d in decision_res["decisions"] if d["experiment_id"] == exp_id]
assert len(user_decisions) == 1
assert user_decisions[0]["variant"] == "control", f"Expected control, got {user_decisions[0]['variant']}"
print(f"  ? Assigned variant: {user_decisions[0]['variant']} (100% control allocation)")

# Update to 100% treatment
client.patch(f"http://localhost:8001/experiments/{exp_id}", json={
    "config": {
        "variants": [{"name": "control", "weight": 0}, {"name": "treatment", "weight": 100}],
        "targeting_rules": [{"type": "EQUALS", "attribute": "env", "value": "prod"}]
    }
})
time.sleep(1.0) # Allow cache updater to process pub/sub

# Query decision engine again for same user
decision_res2 = client.get("http://localhost:8002/decide", params={"user_id": "user_alpha", "attributes": json.dumps({"env": "prod"})}).json()
user_decisions2 = [d for d in decision_res2["decisions"] if d["experiment_id"] == exp_id]
assert user_decisions2[0]["variant"] == "treatment", f"Expected treatment, got {user_decisions2[0]['variant']}"
print(f"  ? Updated assignment: {user_decisions2[0]['variant']} (100% treatment allocation)")

# 7. Event Ingestion API Validation
print("\n[7/8] Testing Event Ingestion API...")
inv_ev = client.post("http://localhost:8000/events", json={"event_type": "conversion", "payload": {"experiment_id": 1, "variant_name": "control"}})
assert inv_ev.status_code == 422
print("  ? Invalid event payload returned 422 Unprocessable Entity")

# 8. Event Ingestion -> RabbitMQ Queue Publishing (Requirement 12)
print("\n[8/8] Testing RabbitMQ Event Publishing (Requirement 12)...")
conn = pika.BlockingConnection(pika.ConnectionParameters(host="localhost", port=5672, credentials=pika.PlainCredentials("guest", "guest")))
ch = conn.channel()
ch.queue_purge(queue="analytics_events")

valid_event = {
    "event_type": "conversion",
    "payload": {
        "user_id": "user_e2e_test",
        "experiment_id": 1,
        "variant_name": "treatment"
    }
}
res_event = client.post("http://localhost:8000/events", json=valid_event)
assert res_event.status_code == 202, f"Expected 202 Accepted, got {res_event.status_code}"
print("  ? Event ingested with 202 Accepted")

time.sleep(0.5)
method_frame, header_frame, body = ch.basic_get(queue="analytics_events", auto_ack=True)
assert method_frame is not None, "No message found in RabbitMQ analytics_events queue!"
published_data = json.loads(body.decode("utf-8"))
assert published_data["event_type"] == "conversion"
assert published_data["payload"]["user_id"] == "user_e2e_test"
assert published_data["payload"]["experiment_id"] == 1
assert published_data["payload"]["variant_name"] == "treatment"
conn.close()
print(f"  ? Exactly matched message verified from RabbitMQ queue 'analytics_events': {published_data}")

print("\n" + "=" * 60)
print("ALL END-TO-END TESTS PASSED 100% SUCCESSFULLY! ??")
print("=" * 60)
