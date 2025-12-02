import importlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from kombu.serialization import register


DATACLASS_MARKER = "__dataclass__"


def _default(obj: Any):
    if is_dataclass(obj):
        return {
            DATACLASS_MARKER: f"{obj.__class__.__module__}.{obj.__class__.__name__}",
            "data": asdict(obj),
        }
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _object_hook(obj: dict):
    marker = obj.get(DATACLASS_MARKER)
    if not marker:
        return obj
    module_name, class_name = marker.rsplit(".", 1)
    module = importlib.import_module(module_name)
    dataclass_type = getattr(module, class_name)
    return dataclass_type(**obj["data"])


def dataclass_dumps(obj: Any) -> str:
    return json.dumps(obj, default=_default)


def dataclass_loads(data: str) -> Any:
    return json.loads(data, object_hook=_object_hook)


register(
    "dataclass-json",
    dataclass_dumps,
    dataclass_loads,
    content_type="application/json",
    content_encoding="utf-8",
)
