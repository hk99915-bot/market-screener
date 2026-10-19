"""Strict JSON for browser-facing detail: missing non-finite numbers become null."""
import json
import math


def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: finite_tree(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_tree(v) for v in value]
    return value


def dumps(value, **kwargs):
    kwargs["allow_nan"] = False
    return json.dumps(finite_tree(value), **kwargs)
