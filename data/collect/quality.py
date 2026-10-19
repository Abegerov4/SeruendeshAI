"""Small, explicit review decisions; original source facts remain auditable."""
from copy import deepcopy


def apply_quality_overrides(candidates, overrides, *, phase="before_enrichment"):
    phases = {"before_enrichment", "after_enrichment"}
    if phase not in phases:
        raise ValueError(f"Unknown quality review phase: {phase}")
    for ident, rule in overrides.items():
        if rule.get("phase", "before_enrichment") not in phases:
            raise ValueError(f"Unknown quality review phase for {ident}: {rule.get('phase')}")
    safe, quarantined, applied = [], [], []
    for original in candidates:
        poi = deepcopy(original)
        rule = overrides.get(poi["id"])
        if rule and rule.get("phase", "before_enrichment") != phase:
            rule = None
        if rule and (any(poi.get(key) != value for key, value in rule.get("when", {}).items()) or
                     any(poi.get("raw_tags", {}).get(key) != value for key, value in rule.get("when_raw_tags", {}).items())):
            rule = None
        if rule:
            action = rule["action"]
            poi.setdefault("quality_review_notes", []).append(deepcopy(rule))
            applied.append({"id": poi["id"], "action": action})
            if action == "quarantine":
                quarantined.append(poi)
                continue
            if action == "suppress_wikimedia":
                poi["skip_wikimedia_enrichment"] = True
                poi.setdefault("quality_flags", []).append("conflicting_wikimedia_link")
            elif action == "suppress_cuisine_text":
                poi["suppress_cuisine_text"] = True
                poi["tags"] = [tag for tag in poi.get("tags", []) if not tag.startswith("cuisine=")]
                poi.setdefault("quality_flags", []).append("unverified_cuisine_tag")
            elif action == "verified_same_place":
                poi["verified_identity_parent_id"] = rule["target_id"]
            else:
                raise ValueError(f"Unknown quality review action: {action}")
        safe.append(poi)
    return safe, quarantined, {"quarantine_count": len(quarantined), "applied_overrides": applied}
