"""Small cached HTTP client; only public source responses are persisted."""
import hashlib
import json
import time
import urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / 'raw'
USER_AGENT = 'SeruendeshAI/1.0 (https://github.com/Abegerov4/SeruendeshAI)'

def get_json(url, body=None, refresh=False, pause=1.1):
    RAW.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode() + (body or b'')).hexdigest()
    path = RAW / f'{key}.json'
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding='utf-8'))
    for attempt in range(3):
        try:
            time.sleep(pause)
            req = urllib.request.Request(url, data=body, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=150) as response:
                result = json.load(response)
            if isinstance(result, dict) and result.get('remark'):
                raise ValueError(result['remark'])
            path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
            return result
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
