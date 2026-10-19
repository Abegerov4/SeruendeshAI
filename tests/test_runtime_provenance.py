"""Current UI runtime and review decisions must invalidate old live evidence."""
from eval.run_eval import source_fingerprint


def test_ayat_runtime_change_invalidates_evidence(tmp_path):
    source = tmp_path / "ayat_backend/app/service.py"
    source.parent.mkdir(parents=True)
    source.write_text("policy = 1\n")
    before = source_fingerprint(tmp_path)
    source.write_text("policy = 2\n")
    assert source_fingerprint(tmp_path) != before


def test_quarantine_change_invalidates_evidence(tmp_path):
    policy = tmp_path / "data/quarantine.json"
    policy.parent.mkdir()
    policy.write_text("[]")
    before = source_fingerprint(tmp_path)
    policy.write_text('[{"id":"review:1"}]')
    assert source_fingerprint(tmp_path) != before


def test_fact_review_change_invalidates_evidence(tmp_path):
    policy = tmp_path / "data/processed/fact_reviews.json"
    policy.parent.mkdir(parents=True)
    policy.write_text("[]")
    before = source_fingerprint(tmp_path)
    policy.write_text('[{"reviewed_fact":true}]')
    assert source_fingerprint(tmp_path) != before


def test_frozen_dependency_lock_change_invalidates_evidence(tmp_path):
    lock = tmp_path / "ayat_backend/uv.lock"
    lock.parent.mkdir()
    lock.write_text("revision = 1\n")
    before = source_fingerprint(tmp_path)
    lock.write_text("revision = 999\n")
    assert source_fingerprint(tmp_path) != before
