"""Transport security regressions; no real providers or Telegram network."""
import asyncio
import io
import struct
import zlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import vision
from backend.app.main import api_recommend_photo, app


def png_header(width, height):
    data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', data) + chunk(b'IDAT', zlib.compress(b'\0' * 4)) + chunk(b'IEND', b'')



def test_image_bomb_returns_client_error():
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post('/api/recommend/photo', files={'image': ('bomb.png', png_header(100000, 100000), 'image/png')})
    assert response.status_code in (413, 422)


def test_image_pixel_budget_checked_before_rgb_decode(monkeypatch):
    image = Image.new('RGB', (20, 20))
    data = io.BytesIO()
    image.save(data, format='PNG')
    monkeypatch.setattr(vision, 'MAX_PIXELS', 100, raising=False)
    with pytest.raises(vision.PhotoError):
        vision.prepare_image(data.getvalue(), 'image/png')


def test_photo_upload_read_is_bounded():
    class OversizeUpload:
        content_type = 'image/jpeg'
        async def read(self, size=-1):
            assert 0 < size <= vision.MAX_BYTES + 1, 'upload must use bounded read'
            return b'x' * size
    async def run():
        with pytest.raises(HTTPException) as error:
            await api_recommend_photo(image=OversizeUpload(), query='where', time_budget_min=None, mode=None,
                                      lang=None, now=None, with_kids=False, tourist=False, accessibility=False, group_size=1)
        assert error.value.status_code in (413, 422)
    asyncio.run(run())


def test_mcp_search_masks_pii_at_retrieval_boundary(monkeypatch):
    from backend.mcp_server import server
    seen = []
    monkeypatch.setattr(server.rag, 'search', lambda query, *a, **kw: seen.append(query) or [])
    server.search_pois('coffee synthetic@example.com +7 777 123 45 67 123456789012')
    assert seen == ['coffee [EMAIL] [PHONE] [IIN]']
    with pytest.raises(ValueError):
        server.search_pois('x' * 1001)


def test_telegram_location_expires_without_new_update(monkeypatch):
    from backend.telegram_bot import bot
    async def run():
        callbacks = []
        clock = [0.0]
        def schedule(delay, callback):
            handle = SimpleNamespace(cancelled=False)
            handle.cancel = lambda: setattr(handle, 'cancelled', True)
            callbacks.append((clock[0] + delay, callback, handle))
            return handle
        monkeypatch.setattr(bot.time, 'monotonic', lambda: clock[0])
        monkeypatch.setattr(bot.asyncio, 'get_running_loop', lambda: SimpleNamespace(call_later=schedule))
        context = SimpleNamespace(chat_data={})
        async def reply(*a, **kw):
            pass
        update = SimpleNamespace(message=SimpleNamespace(location=SimpleNamespace(latitude=51.1, longitude=71.4), reply_text=reply))
        await bot.on_location(update, context)
        assert 'loc' in context.chat_data
        clock[0] = 1801.0
        for deadline, callback, handle in callbacks:
            if deadline <= clock[0] and not handle.cancelled:
                callback()
        assert 'loc' not in context.chat_data
    asyncio.run(run())


def test_photo_decode_runs_outside_event_loop(monkeypatch):
    import threading
    main_thread = threading.get_ident()
    original = vision.prepare_image
    def checked_decode(*args):
        assert threading.get_ident() != main_thread
        return original(*args)
    monkeypatch.setattr(vision, 'prepare_image', checked_decode)
    image = Image.new('RGB', (20, 20))
    content = io.BytesIO()
    image.save(content, format='JPEG')
    class Upload:
        content_type = 'image/jpeg'
        async def read(self, size):
            return content.getvalue()[:size]
    async def run():
        result = await api_recommend_photo(image=Upload(), query='where', time_budget_min=None, mode=None,
                                          lang=None, now=None, with_kids=False, tourist=False,
                                          accessibility=False, group_size=1)
        assert result.recommendations == []
    asyncio.run(run())


def test_mcp_query_is_masked_at_actual_embedding_provider(monkeypatch, tmp_path):
    import json
    import sys
    import openai
    from collections import Counter
    from backend.mcp_server import server
    from rag import retriever
    manifest = tmp_path / 'rag/chroma/manifest.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'sha256': 'synthetic', 'provider': 'openai', 'model': 'test', 'collection': 'test'}))
    poi = {'id': 'local', 'name': 'Coffee', 'category': 'cafe', 'lat': 51.1, 'lon': 71.4, 'tags': []}
    monkeypatch.setattr(retriever, 'ROOT', tmp_path)
    monkeypatch.setattr(retriever, 'catalog', lambda: {'pois': [poi], 'eligible': {0}, 'docs': [Counter({'coffee': 1})],
                                                     'frequencies': Counter({'coffee': 1}), 'average': 1, 'digest': 'synthetic'})
    monkeypatch.setenv('RAG_SEARCH_MODE', 'hybrid')
    monkeypatch.setattr(server.rag, '_retriever', retriever)
    monkeypatch.setattr(server.rag, '_backend', 'real')
    monkeypatch.setitem(sys.modules, 'chromadb', SimpleNamespace(PersistentClient=lambda **kw: SimpleNamespace(
        get_collection=lambda name: SimpleNamespace(query=lambda **kw: {'ids': [['local']]}))))
    seen = []
    def create(**kw):
        seen.extend(kw['input'])
        return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1.0])])
    monkeypatch.setattr(openai, 'OpenAI', lambda **kw: SimpleNamespace(embeddings=SimpleNamespace(create=create)))
    result = server.search_pois('coffee synthetic@example.com +7 777 123 45 67 123456789012')
    assert result.results[0].poi_id == 'local'
    assert seen == ['coffee [EMAIL] [PHONE] [IIN]']


def test_photo_request_size_is_rejected_before_body_is_consumed():
    # ASGI receive must not be invoked for a known oversized photo request.
    async def run():
        sent = []
        async def receive():
            pytest.fail('oversized Content-Length should be rejected before reading')
        async def send(message):
            sent.append(message)
        await app({'type': 'http', 'asgi': {'version': '3.0'}, 'method': 'POST', 'path': '/api/recommend/photo',
                   'raw_path': b'/api/recommend/photo', 'query_string': b'', 'scheme': 'http',
                   'headers': [(b'content-length', b'100000000'), (b'content-type', b'multipart/form-data; boundary=x')],
                   'client': ('local', 1), 'server': ('local', 80)}, receive, send)
        assert sent[0]['status'] == 413
    asyncio.run(run())


def test_chunked_photo_request_stops_at_limit_without_consuming_remainder():
    async def run():
        sent = []
        calls = [0]
        prefix = b'--x\r\nContent-Disposition: form-data; name="image"; filename="x.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
        chunks = [prefix] + [b'x' * (1024 * 1024)] * 20 + [b'\r\n--x--\r\n']
        async def receive():
            chunk = chunks[calls[0]]
            calls[0] += 1
            return {'type': 'http.request', 'body': chunk, 'more_body': calls[0] < len(chunks)}
        async def send(message):
            sent.append(message)
        await app({'type': 'http', 'asgi': {'version': '3.0'}, 'method': 'POST', 'path': '/api/recommend/photo',
                   'raw_path': b'/api/recommend/photo', 'query_string': b'', 'scheme': 'http',
                   'headers': [(b'content-type', b'multipart/form-data; boundary=x')],
                   'client': ('local', 1), 'server': ('local', 80)}, receive, send)
        assert sent[0]['status'] == 413
        assert calls[0] < len(chunks)
    asyncio.run(run())
