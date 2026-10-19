"""Combine independent assertions only when the full branch identity agrees."""
from copy import deepcopy
from datetime import date
import json


def merge_detail_sources(base: dict, supplement: dict) -> tuple[dict, list[str]]:
    if (base.get("schema_version") != 1 or supplement.get("schema_version") != 1
            or base.get("canonical_sha256") != supplement.get("canonical_sha256")):
        raise ValueError("Place detail sources belong to different master/schema")
    result = deepcopy(base)
    result["as_of"] = max(date.fromisoformat(base["as_of"]), date.fromisoformat(supplement["as_of"])).isoformat()
    for payload in (base, supplement):
        if not isinstance(payload.get("records"), list):
            raise ValueError("Place detail source records must be a list")
        ids = [r.get("canonical_id") for r in payload["records"] if isinstance(r, dict)]
        if len(ids) != len(payload["records"]) or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("Place detail sources require unique canonical IDs")
    by_id = {record["canonical_id"]: record for record in result["records"]}
    held = []
    for record in supplement["records"]:
        ident = record["canonical_id"]
        current = by_id.get(ident)
        if current is None:
            current = deepcopy(record)
            result["records"].append(current)
            by_id[ident] = current
        elif current.get("identity") != record.get("identity"):
            held.append(ident)
        else:
            for key in ("facts", "menu_items", "prices"):
                values = current.setdefault(key, [])
                incoming = record.get(key, [])
                if not isinstance(values, list) or not isinstance(incoming, list):
                    raise ValueError("Place assertions must be lists")
                seen = {json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) for value in values}
                for value in incoming:
                    fingerprint = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
                    if fingerprint not in seen:
                        values.append(deepcopy(value))
                        seen.add(fingerprint)
    return result, held
