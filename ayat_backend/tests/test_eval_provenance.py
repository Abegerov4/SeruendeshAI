"""Primary-runtime evidence must not pass on fixture transport or missing checks."""
import copy
import json
import sys
from pathlib import Path

import httpx
import pytest
import yaml

from ayat_backend.eval import run_eval
from eval import check_readiness as gate

REPO = Path(__file__).resolve().parents[2]


def identity(tmp_path):
    path = tmp_path / 'pois.json'
    path.write_text('[]')
    return {'known_ids': {'venue:one'}, 'canonical_path': path,
            'snapshot_version': 'snapshot-one'}


def health():
    return {'status': 'ok', 'pois': 1, 'poi_count': 1, 'llm': 'off',
            'runtime_id': 'ayat', 'readiness_profile': 'template', 'ready': True,
            'snapshot_version': 'snapshot-one', 'provider_verified_at': None,
            'events': 0, 'dense_retrieval': False, 'walk_graph': False,
            'llm_configured': False, 'data_built_at': None}


def valid_response():
    response = copy.deepcopy(json.loads((REPO / 'eval/runs/2026-10-19-branch-integration/http-smoke.json').read_text())['cases'][0]['response'])
    response['route'] = None
    response['recommendations'] = response['recommendations'][:1]
    response['used_context']['time_budget_min'] = 60
    response['recommendations'][0].update(poi_id='venue:one', travel_min=1, visit_min=[10, 20], visit_suggested_min=10)
    return response


@pytest.mark.parametrize('wrong_identity', ['secondary', 'missing_runtime', 'llm_profile'])
def test_cli_rejects_successful_cards_from_wrong_or_missing_health_identity(monkeypatch, tmp_path, wrong_identity):
    (tmp_path / 'eval').mkdir()
    (tmp_path / 'eval/scenarios.yaml').write_text('- id: one\n  title: one\n  request: {query: local}\n  expect: {}\n')
    monkeypatch.setattr(run_eval, 'ROOT', tmp_path)
    monkeypatch.setattr(run_eval, 'local_identity', lambda root: identity(tmp_path))
    remote = health()
    if wrong_identity == 'secondary': remote['runtime_id'] = 'secondary'
    elif wrong_identity == 'missing_runtime': remote.pop('runtime_id')
    else: remote['readiness_profile'] = 'llm'
    real_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda *a, **kw: real_client(*a, **kw, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json=remote if req.url.path == '/api/health' else valid_response()))))
    md = tmp_path / 'report.md'
    monkeypatch.setattr(sys, 'argv', ['eval', '--base-url', 'http://local.test', '--no-llm', '--out', str(md)])
    assert run_eval.main() == 1
    assert json.loads(md.with_suffix('.json').read_text())['metadata']['provenance_errors']


def test_cli_companion_counts_http_failures_and_isolates_array(monkeypatch, tmp_path):
    (tmp_path / 'eval').mkdir()
    (tmp_path / 'eval/scenarios.yaml').write_text('- id: bad\n  title: failing HTTP\n  request: {query: local}\n  expect: {}\n')
    historical = tmp_path / 'eval/results.json'
    historical.write_text('["historical"]')
    monkeypatch.setattr(run_eval, 'ROOT', tmp_path)
    monkeypatch.setattr(run_eval, 'local_identity', lambda root: identity(tmp_path), raising=False)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda *a, **kw: real_client(*a, **kw, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json=health()) if req.url.path == '/api/health'
        else httpx.Response(500, json={'error': 'failed'}))))
    md = tmp_path / 'run/report.md'
    arrays = tmp_path / 'run/results.json'
    monkeypatch.setattr(sys, 'argv', ['eval', '--base-url', 'http://local.test', '--no-llm',
                                     '--out', str(md), '--results-out', str(arrays)])
    assert run_eval.main() == 1
    report = json.loads(md.with_suffix('.json').read_text())
    assert report['metadata']['runtime_id'] == 'ayat'
    assert report['metadata']['execution_kind'] == 'fixture_transport'
    assert report['metadata']['health']['snapshot_version'] == 'snapshot-one'
    assert report['summary'] == {'planned': 1, 'attempted': 1, 'passed': 0, 'failed': 1, 'unexecuted': 0}
    assert report['passed'] is False
    assert json.loads(arrays.read_text())[0]['http_status'] == 500
    assert historical.read_text() == '["historical"]'


def report_fixture(tmp_path, monkeypatch):
    cases = tmp_path / 'scenarios.yaml'
    cases.write_text(yaml.safe_dump([{'id': 'one', 'title': 'one', 'request': {'query': 'local'}, 'expect': {}}]))
    local = identity(tmp_path)
    monkeypatch.setattr(run_eval, 'local_identity', lambda root: local)
    monkeypatch.setattr(gate, 'git_state', lambda root: {'git_head': 'abc', 'git_dirty': True})
    from eval.run_eval import file_sha256, source_fingerprint
    response = valid_response()
    checks = {key: True for key in run_eval.CHECKS}
    checks.update({'C5 categories': None, 'C7 language': None, 'C10 safety rules': None})
    report = {'report_version': 1, 'report_format': 'ayat_evaluation', 'response_schema': 'ayat.RecommendResponse',
              'passed': True, 'input_errors': [], 'metadata': {'runtime_id': 'ayat', 'profile': 'template',
              'execution_kind': 'live_http', 'base_url': 'http://127.0.0.1:8000', 'health': health(),
              'snapshot_version': 'snapshot-one', 'canonical_data_sha256': file_sha256(local['canonical_path']),
              'dataset_sha256': file_sha256(local['canonical_path']), 'scenario_sha256': file_sha256(cases),
              'source_sha256': source_fingerprint(tmp_path), 'git_head': 'abc', 'git_dirty': True},
              'summary': {'planned': 1, 'attempted': 1, 'passed': 1, 'failed': 0, 'unexecuted': 0},
              'results': [{'id': 'one', 'executed': True, 'passed': True, 'http_status': 200, 'ms': 1,
                           'mode': 'template', 'model': None, 'checks': checks, 'response': response}]}
    path = tmp_path / 'report.json'
    path.write_text(json.dumps(report))
    return path, local['canonical_path'], cases, report


def test_primary_gate_accepts_complete_template_evidence_and_rejects_stale_code(tmp_path, monkeypatch):
    path, pois, cases, report = report_fixture(tmp_path, monkeypatch)
    assert gate._ayat_evidence_errors(path, tmp_path, pois, cases, 'template') == []
    source = tmp_path / 'ayat_backend/app/service.py'
    source.parent.mkdir(parents=True)
    source.write_text('# changed while already dirty')
    assert any('fingerprint' in e.lower() for e in gate._ayat_evidence_errors(path, tmp_path, pois, cases, 'template'))


@pytest.mark.parametrize('mutation', ['secondary', 'inprocess', 'snapshot', 'profile', 'missing_check', 'bad_schema', 'forged_id', 'omitted_case'])
def test_primary_gate_rejects_wrong_runtime_profile_snapshot_and_incomplete_checks(tmp_path, monkeypatch, mutation):
    path, pois, cases, report = report_fixture(tmp_path, monkeypatch)
    if mutation == 'secondary': report['metadata']['runtime_id'] = 'secondary'
    elif mutation == 'inprocess': report['metadata']['execution_kind'] = 'in_process'
    elif mutation == 'snapshot': report['metadata']['health']['snapshot_version'] = 'old'
    elif mutation == 'profile': report['metadata']['profile'] = 'llm'
    elif mutation == 'missing_check': report['results'][0]['checks'].pop('C3 grounded ids')
    elif mutation == 'bad_schema': report['results'][0]['response'] = {'recommendations': []}
    elif mutation == 'forged_id': report['results'][0]['response']['recommendations'][0]['poi_id'] = 'invented:poi'
    else: report['results'] = []
    path.write_text(json.dumps(report))
    assert gate._ayat_evidence_errors(path, tmp_path, pois, cases, 'template')


def test_explicit_ayat_presence_does_not_reuse_secondary_entrypoint(tmp_path):
    report = gate.check_readiness(tmp_path, runtime='ayat')
    assert report['runtime_id'] == 'ayat'
    assert next(x for x in report['checks'] if x['name'] == 'backend')['detail'].startswith('ayat_backend/app/main.py')
