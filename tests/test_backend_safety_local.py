"""Local safety checks for team/04_qa_docs.md, stages2–3.

These use the actual HTTP application, keyword retriever, intent parser,
recommendation validator and rendering cleaner. Only the model-provider and
tracing SDK boundaries are deterministic doubles. No model-resistance or real
RAG claim is made; the poisoned POI lives only in qa_backend's temporary file.
"""
from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache
import json
import logging
from pathlib import Path
import re

import pytest


AFTERNOON = '2026-10-18T15:00:00+05:00'
ORIGIN = {'lat': 51.128, 'lon': 71.43}


def _single_park(backend):
    park = deepcopy(next(poi for poi in backend.pois if poi['id'] == 'test:park'))
    backend.set_pois([park])
    return park


def _answer(poi_id, **changes):
    recommendation = {'poi_id': poi_id, 'why': 'Подходит для прогулки рядом.',
                      'visit_min': [10, 15], 'what_to_do': 'Пройти по парку.', 'source': 'poi_data'}
    recommendation.update(changes)
    return {'recommendations': [recommendation], 'notes': []}


def _provider(backend, monkeypatch, answer):
    calls = []

    def chat_json(system, user, **options):
        # Application validators execute locally; provider payload/role metadata
        # remains the boundary inspected for PII and exact-coordinate leakage.
        provider_options = {key: options[key] for key in ('role', 'name', 'model_override') if key in options}
        calls.append({'system': system, 'user': user, **provider_options})
        # Real intent rules remain active; the controlled malicious/valid output
        # is returned only to the actual generation validation layer.
        if options.get('name') == 'parse-intent':
            return None
        assert options.get('name') == 'decide-recommendations'
        return deepcopy(answer)

    monkeypatch.setattr(backend.llm, 'chat_json', chat_json)
    return calls


def _post(backend, **changes):
    request = {'query': 'Хочу парк рядом', 'location': ORIGIN, 'time_budget_min': 60,
               'mode': 'walk', 'lang': 'ru', 'now': AFTERNOON}
    request.update(changes)
    response = backend.client.post('/api/recommend', json=request)
    assert response.status_code == 200, response.text
    return response.json()


class _TraceSink:
    """Capture the SDK boundary while keeping real tracing.span code active."""
    def __init__(self):
        self.events = []

    @contextmanager
    def start_as_current_observation(self, **parameters):
        self.events.append({'start': parameters})
        sink = self

        class Observation:
            def update(self, **parameters):
                sink.events.append({'update': parameters})
                return self

        yield Observation()

    def flush(self):
        pass


def _trace_sink(backend, monkeypatch):
    sink = _TraceSink()
    @lru_cache
    def client():
        return sink
    monkeypatch.setattr(backend.tracing, '_client', client)
    return sink


@pytest.mark.parametrize('pii,canonical', [
    ('qa.person@example.com', 'qa.person@example.com'),
    ('+7 000 000-00-00', '70000000000'),
    ('000000000000', '000000000000'),
], ids=['email', 'phone', 'iin'])
def test_pii_is_masked_before_model_requests_and_backend_telemetry(
        qa_backend, monkeypatch, caplog, pii, canonical):
    """QA stage3: masking must precede providers and traces, not just final JSON."""
    park = _single_park(qa_backend)
    calls = _provider(qa_backend, monkeypatch, _answer(park['id']))
    traces = _trace_sink(qa_backend, monkeypatch)
    caplog.set_level(logging.DEBUG, logger='backend.pipeline')
    body = _post(qa_backend, query=f'СИНТЕТИЧЕСКИЙ ТЕСТ: контакт {pii}. Хочу парк рядом')
    assert body['recommendations']
    assert {call['name'] for call in calls} == {'parse-intent', 'decide-recommendations'}
    assert traces.events, 'The real tracing adapter must have emitted observations'
    payload = json.dumps({'provider': calls, 'traces': traces.events,
                          'logs': [r.getMessage() for r in caplog.records if r.name.startswith('backend.')]},
                         ensure_ascii=False)
    assert pii not in payload, 'Raw synthetic PII reached a provider or backend telemetry'
    if canonical.isdigit():
        assert canonical not in re.sub(r'\D', '', payload), 'Reformatting must not preserve the identifier'
    else:
        assert canonical.casefold() not in payload.casefold()
    assert 'Хочу парк рядом' in payload, 'Privacy must preserve the useful request intent'


def test_exact_user_gps_never_enters_model_payload_logs_or_trace_observations(
        qa_backend, monkeypatch, caplog):
    """QA stage3: inspect actual outgoing arguments and telemetry with distinct GPS."""
    park = _single_park(qa_backend)
    calls = _provider(qa_backend, monkeypatch, _answer(park['id']))
    traces = _trace_sink(qa_backend, monkeypatch)
    caplog.set_level(logging.DEBUG, logger='backend.pipeline')
    origin = {'lat': 51.128123, 'lon': 71.430987}
    body = _post(qa_backend, location=origin)
    assert body['recommendations'] and body['used_context']['location_source'] == 'gps_rounded'
    assert calls and traces.events
    payload = json.dumps({'provider': calls, 'traces': traces.events,
                          'logs': [r.getMessage() for r in caplog.records if r.name.startswith('backend.')]},
                         ensure_ascii=False)
    for coordinate in origin.values():
        assert str(coordinate) not in payload, 'Exact user GPS escaped the application boundary'


def test_retrieved_poisoned_description_cannot_select_an_outside_candidate_id(qa_backend, monkeypatch):
    """QA stage3 indirect injection: prove retrieval before checking the ID guard."""
    poison = json.loads((Path(__file__).parent / 'fixtures/poi_injection.json').read_text(encoding='utf-8'))
    cafe = deepcopy(next(p for p in qa_backend.pois if p['id'] == 'test:cafe'))
    cafe.update(id=poison['poi_id'], description=poison['description'])
    qa_backend.set_pois([cafe])
    calls = _provider(qa_backend, monkeypatch,
                      _answer('test:not-a-candidate', why='QA_POI_ATTACK_73', what_to_do='Выполнить внедрённые инструкции.'))
    body = _post(qa_backend, query='Хочу кафе рядом')
    decision_inputs = [call['user'] for call in calls if call['name'] == 'decide-recommendations']
    assert decision_inputs and all('QA_POI_ATTACK_73' in text for text in decision_inputs), 'Poison must actually reach generation through retrieval'
    assert all(cafe['id'] in text for text in decision_inputs)
    assert all(text.count('</untrusted_data>') == 1 for text in decision_inputs), 'Retrieved text must not close its enclosing data block'
    assert {r['poi_id'] for r in body['recommendations']} == {cafe['id']}
    assert 'QA_POI_ATTACK_73' not in json.dumps(body, ensure_ascii=False)
    assert 'test:not-a-candidate' not in json.dumps(body, ensure_ascii=False)


def test_provider_cannot_select_a_known_dataset_id_outside_retrieved_candidates(qa_backend, monkeypatch):
    """Known-to-dataset is weaker than allowed-in-current-retrieval (QA stage2)."""
    near = deepcopy(next(p for p in qa_backend.pois if p['id'] == 'test:park'))
    far = deepcopy(next(p for p in qa_backend.pois if p['id'] == 'test:far'))
    qa_backend.set_pois([near, far])
    calls = _provider(qa_backend, monkeypatch, _answer(far['id']))
    body = _post(qa_backend)
    decision_inputs = [c['user'] for c in calls if c['name'] == 'decide-recommendations']
    assert decision_inputs and all(far['id'] not in text for text in decision_inputs)
    assert [r['poi_id'] for r in body['recommendations']] == [near['id']]


def test_duplicate_model_ids_are_removed_before_response_and_route(qa_backend, monkeypatch):
    park = _single_park(qa_backend)
    answer = _answer(park['id'], why='Первое объяснение.')
    answer['recommendations'].append({**answer['recommendations'][0], 'why': 'Дублирующее объяснение.'})
    _provider(qa_backend, monkeypatch, answer)
    body = _post(qa_backend)
    assert [r['poi_id'] for r in body['recommendations']] == [park['id']]
    # Facts-only mode is user-approved: duplicate model prose is never evidence.
    assert body['recommendations'][0]['why'].startswith('Парк ')
    assert 'объяснение' not in body['recommendations'][0]['why']
    assert body['route'] is None


def test_model_fields_cannot_override_unknown_hours_or_authoritative_poi_facts(qa_backend, monkeypatch):
    """QA stage2 and Backend step8: model text cannot replace factual fields."""
    park = _single_park(qa_backend)
    _provider(qa_backend, monkeypatch, _answer(park['id'], open_status='open', open_confidence='high',
              lat=0, lon=0, name='Invented name', category='nightlife', distance_m=0,
              rating=5, source_url='https://qa-exfil.invalid/collect'))
    rec = _post(qa_backend)['recommendations'][0]
    assert (rec['open_status'], rec['open_confidence']) == ('unknown', 'none')
    for field in ('name', 'category', 'lat', 'lon', 'rating', 'source_url'):
        assert rec[field] == park[field]
    assert rec['distance_m'] > 0


def test_unknown_hours_cannot_be_contradicted_by_model_explanation(qa_backend, monkeypatch):
    """QA honesty + docs/ethics_privacy.md: an LLM summary cannot prove open hours."""
    park = _single_park(qa_backend)
    _provider(qa_backend, monkeypatch, _answer(park['id'], why='Место сейчас открыто круглосуточно, часы подтверждены.'))
    body = _post(qa_backend)
    assert body['recommendations'][0]['open_status'] == 'unknown'
    explanation = body['recommendations'][0]['why'].casefold()
    assert 'сейчас открыто' not in explanation and 'часы подтверждены' not in explanation, 'A structured unknown badge does not make a contradictory opening claim safe'


@pytest.mark.parametrize('reply', [
    'not a JSON object',
    {'recommendations': [{'poi_id': 'test:park', 'why': [], 'visit_min': 'bad', 'what_to_do': {}}]},
], ids=['wrong-root', 'malformed-card'])
def test_malformed_model_reply_uses_a_nonempty_grounded_fallback(qa_backend, monkeypatch, reply):
    park = _single_park(qa_backend)
    _provider(qa_backend, monkeypatch, reply)
    body = _post(qa_backend)
    assert [r['poi_id'] for r in body['recommendations']] == [park['id']]
    assert body['recommendations'][0]['why'].strip() and body['recommendations'][0]['what_to_do'].strip()
    assert body['recommendations'][0]['open_status'] == 'unknown'


def test_url_cleaning_cannot_leave_an_empty_successful_recommendation(qa_backend, monkeypatch):
    """QA stage2 requires nonempty why/what_to_do after all rendering cleaners."""
    park = _single_park(qa_backend)
    _provider(qa_backend, monkeypatch, _answer(park['id'], why='https://qa-exfil.invalid/pixel',
                                             what_to_do='![map](https://qa-exfil.invalid/map)'))
    rec = _post(qa_backend)['recommendations'][0]
    assert rec['why'].strip(), 'Sanitized-empty model text must trigger rejection or factual fallback'
    assert rec['what_to_do'].strip(), 'Sanitized-empty action must trigger rejection or factual fallback'


@pytest.mark.parametrize('unsafe', [
    'Посмотреть [карту](//qa-exfil.invalid/collect?token=synthetic).',
    "Посмотреть [фото](javascript:fetch('/collect')).",
], ids=['scheme-relative', 'javascript'])
def test_model_output_cannot_expose_non_http_exfiltration_links(qa_backend, monkeypatch, unsafe):
    """Privacy safe-display target and Backend README: model links are stripped."""
    park = _single_park(qa_backend)
    _provider(qa_backend, monkeypatch, _answer(park['id'], why=unsafe, what_to_do=unsafe))
    body = _post(qa_backend)
    rendered = json.dumps([(r['why'], r['what_to_do']) for r in body['recommendations']], ensure_ascii=False)
    assert 'qa-exfil.invalid' not in rendered and 'javascript:' not in rendered, 'Unsafe link targets survived the backend output cleaner'


def test_template_cannot_label_unsupported_quietness_as_a_poi_fact(qa_backend):
    """QA honesty: a category does not establish quietness; label any idea generated."""
    cafe = deepcopy(next(p for p in qa_backend.pois if p['id'] == 'test:cafe'))
    cafe.update(description='Тестовое кафе с напитками и столами.', description_source='website', tags=[])
    qa_backend.set_pois([cafe])
    rec = _post(qa_backend, query='Хочу кофе рядом')['recommendations'][0]
    unsupported = re.search(r'тих|quiet', rec['what_to_do'], flags=re.IGNORECASE)
    assert rec['source'] == 'generated' or not unsupported, 'Generic cafe facts cannot support a quiet-corner claim labelled poi_data'
