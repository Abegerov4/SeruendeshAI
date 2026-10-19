"""Verified supplemental facilities reach real retrieval, without overriding conflicts."""
import hashlib
import json

from ayat_backend.app.team_data import load_team_snapshot


def write_snapshot(tmp_path, *, old_features=None):
    row={"id":"osm:node/1","name":"Cafe","address":"Street 1","lat":51.1,"lon":71.4,"category":"cafe",
         "raw_tags":old_features or {},"opening_hours":None}
    raw=json.dumps([row]).encode()
    (tmp_path/"pois.json").write_bytes(raw)
    source={"url":"https://example.org/cafe","checked_at":"2026-10-19","excerpt":"Wi-Fi, sockets, indoors; daily 10:00–20:00"}
    proof={"status":"accepted","branch_scope":"exact","conflict_status":"none","source":source,
           "branch_confirmation":{"source_name":"Cafe","source_address":"Street 1"},"valid_from":None,"valid_to":None}
    record={"canonical_id":row["id"],"identity":{"canonical_name":"Cafe","canonical_address":"Street 1",
            "source_name":"Cafe","source_address":"Street 1","source_url":source["url"],"branch_confirmed":True,"match_basis":"name_address"},
            "facts":[{**proof,"field":key,"value":value} for key,value in
                     [("wifi",True),("sockets",True),("indoor",True),("quiet",True),("opening_hours","Mo-Su 10:00-20:00")]],
            "menu_items":[],"prices":[]}
    (tmp_path/"place_details.json").write_text(json.dumps({"schema_version":1,"canonical_sha256":hashlib.sha256(raw).hexdigest(),
        "as_of":"2026-10-19","records":[record]}))
    return tmp_path/"pois.json"


def test_bound_supplemental_facilities_and_hours_are_used_by_adapter(tmp_path):
    pois,_,_=load_team_snapshot(write_snapshot(tmp_path))
    assert pois[0]["features"]["wifi"] is True
    assert pois[0]["features"]["power_outlets"] is True
    assert pois[0]["features"]["quiet"] is True
    assert pois[0]["indoor"] is True
    assert pois[0]["opening_hours"] == "Mo-Su 10:00-20:00"
    assert pois[0]["hours_source_url"] == "https://example.org/cafe"


def test_conflicting_existing_facility_becomes_unknown_until_review(tmp_path):
    pois,_,_=load_team_snapshot(write_snapshot(tmp_path,old_features={"indoor":"no"}))
    assert pois[0]["indoor"] is None
    assert not any(f["field"] == "indoor" for f in pois[0]["place_details"]["facts"])


def test_existing_dispute_is_not_resolved_by_supplemental_fact(tmp_path):
    path = write_snapshot(tmp_path)
    rows = json.loads(path.read_bytes())
    rows[0]["field_conflicts"] = [{"field":"indoor","source_id":"source-old"}]
    raw = json.dumps(rows).encode()
    path.write_bytes(raw)
    sidecar = json.loads((tmp_path/"place_details.json").read_bytes())
    sidecar["canonical_sha256"] = hashlib.sha256(raw).hexdigest()
    (tmp_path/"place_details.json").write_text(json.dumps(sidecar))
    pois,_,_=load_team_snapshot(path)
    assert pois[0]["indoor"] is None
    assert not any(f["field"] == "indoor" for f in pois[0]["place_details"]["facts"])


def test_supplement_does_not_publish_hours_that_conflict_with_an_accepted_review(tmp_path):
    path=write_snapshot(tmp_path)
    raw=path.read_bytes()
    (tmp_path/"fact_reviews.json").write_text(json.dumps({"schema_version":1,
        "canonical_sha256":hashlib.sha256(raw).hexdigest(),"reviews":[{
        "canonical_id":"osm:node/1","field":"opening_hours","value":"Mo-Su 09:00-18:00",
        "status":"accepted","source":"owner","source_id":"owner:1","source_url":"https://example.org/owner",
        "checked_at":"2026-10-19","reviewed_by":"reviewer","evidence_excerpt":"Daily09–18"}]}))
    pois,_,_=load_team_snapshot(path)
    assert pois[0]["opening_hours"] == "Mo-Su 09:00-18:00"
    assert not any(f["field"] == "opening_hours" for f in pois[0]["place_details"]["facts"])
