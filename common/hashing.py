import hashlib
from typing import Any, Dict, List, Optional
try:
    import mmh3
except ImportError:
    mmh3 = None

from common.models import TargetingRule, Variant


def get_hash_bucket(user_id: str, experiment_id: Any) -> int:
    key = f"{user_id}:{experiment_id}"
    if mmh3 is not None:
        return mmh3.hash(key, seed=0, signed=False) % 100
    hash_digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(hash_digest, 16) % 100


def assign_variant(user_id: str, experiment_id: Any, variants: List[Variant]) -> Optional[str]:
    if not variants:
        return None
    bucket = get_hash_bucket(user_id, experiment_id)
    cumulative_weight = 0
    for variant in variants:
        cumulative_weight += variant.weight
        if bucket < cumulative_weight and variant.weight > 0:
            return variant.name
    for variant in variants:
        if variant.weight > 0:
            return variant.name
    return variants[0].name


def evaluate_targeting(rules: Optional[List[TargetingRule]], attributes: Optional[Dict[str, Any]]) -> bool:
    if not rules:
        return True
    if attributes is None:
        attributes = {}

    for rule in rules:
        attr_name = rule.attribute
        user_val = attributes.get(attr_name)

        if rule.type == "EQUALS":
            if user_val is None:
                return False
            if user_val != rule.value and str(user_val) != str(rule.value):
                return False
        elif rule.type == "IN_LIST":
            if user_val is None or not isinstance(rule.value, list):
                return False
            str_list = [str(x) for x in rule.value]
            if user_val not in rule.value and str(user_val) not in str_list:
                return False
        elif rule.type == "NOT_EQUALS":
            if user_val == rule.value or str(user_val) == str(rule.value):
                return False

    return True
