from common.models import Variant, EqualsRule, InListRule, NotEqualsRule
from common.hashing import assign_variant, evaluate_targeting


def test_deterministic_assignment_consistency():
    variants = [
        Variant(name="control", weight=50),
        Variant(name="treatment", weight=50)
    ]
    user_id = "user_test_123"
    exp_id = 1

    first_result = assign_variant(user_id, exp_id, variants)
    for _ in range(50):
        assert assign_variant(user_id, exp_id, variants) == first_result


def test_100_percent_control_allocation():
    variants = [
        Variant(name="control", weight=100),
        Variant(name="treatment", weight=0)
    ]
    for i in range(100):
        user_id = f"user_random_{i}"
        assert assign_variant(user_id, 1, variants) == "control"


def test_100_percent_treatment_allocation():
    variants = [
        Variant(name="control", weight=0),
        Variant(name="treatment", weight=100)
    ]
    for i in range(100):
        user_id = f"user_random_{i}"
        assert assign_variant(user_id, 1, variants) == "treatment"


def test_traffic_distribution_50_50():
    variants = [
        Variant(name="control", weight=50),
        Variant(name="treatment", weight=50)
    ]
    counts = {"control": 0, "treatment": 0}
    total_users = 1000
    for i in range(total_users):
        v = assign_variant(f"user_{i}", 42, variants)
        counts[v] += 1

    assert 400 <= counts["control"] <= 600
    assert 400 <= counts["treatment"] <= 600


def test_evaluate_targeting_equals():
    rules = [EqualsRule(attribute="country", value="US")]
    assert evaluate_targeting(rules, {"country": "US"}) is True
    assert evaluate_targeting(rules, {"country": "CA"}) is False
    assert evaluate_targeting(rules, {}) is False
    assert evaluate_targeting(rules, None) is False


def test_evaluate_targeting_in_list():
    rules = [InListRule(attribute="browser", value=["Chrome", "Firefox"])]
    assert evaluate_targeting(rules, {"browser": "Chrome"}) is True
    assert evaluate_targeting(rules, {"browser": "Firefox"}) is True
    assert evaluate_targeting(rules, {"browser": "Safari"}) is False
    assert evaluate_targeting(rules, {}) is False


def test_evaluate_targeting_not_equals():
    rules = [NotEqualsRule(attribute="tier", value="enterprise")]
    assert evaluate_targeting(rules, {"tier": "free"}) is True
    assert evaluate_targeting(rules, {"tier": "enterprise"}) is False


def test_evaluate_targeting_empty():
    assert evaluate_targeting([], {"country": "US"}) is True
    assert evaluate_targeting(None, {"country": "US"}) is True
