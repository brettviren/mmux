from dataclasses import dataclass
from typing import Any
import json
import logging

REGISTRY: dict[tuple[str, str], type] = {}


def register(proto: str, schema: str):
    def decorator(cls):
        REGISTRY[(proto, schema)] = cls
        return cls
    return decorator


def parse_line(line: bytes | str) -> Any | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        logging.debug("bad JSON: %r", line)
        return None
    key = (data.get("proto"), data.get("schema"))
    cls = REGISTRY.get(key)
    if cls is None:
        logging.debug("unknown proto/schema: %s", key)
        return None
    fields = {k: v for k, v in data.items() if k not in ("proto", "schema")}
    try:
        return cls(**fields)
    except TypeError as e:
        logging.debug("dataclass mismatch for %s: %s", key, e)
        return None


async def events(target: str):
    from mmux.queue import line_stream
    async for line in line_stream(target):
        obj = parse_line(line)
        if obj is not None:
            yield obj
