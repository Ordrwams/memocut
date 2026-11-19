"""Озвучка ElevenLabs на локальному фейковому сервері: запит, кеш, таймкоди слів, підгін сцен."""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from memocut.core import tts
from memocut.core.brief import Brief, Slot


class Fake(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("xi-api-key") != "good":
            return self._send(401, {"detail": {"message": "invalid key"}})
        self._send(200, {"voices": [{"voice_id": "v2", "name": "Rachel", "labels": {"gender": "female"}},
                                    {"voice_id": "v1", "name": "adam", "labels": {}}]})

    def do_POST(self):
        Fake.calls.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        text = Fake.calls[-1][1]["text"]
        chars = list(text)
        self._send(200, {"audio_base64": base64.b64encode(b"ID3fake").decode(),
                         "alignment": {"characters": chars,
                                       "character_start_times_seconds": [i * 0.1 for i in range(len(chars))],
                                       "character_end_times_seconds": [i * 0.1 + 0.1 for i in range(len(chars))]}})


@pytest.fixture
def server(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(tts, "API", f"http://127.0.0.1:{srv.server_port}")
    Fake.calls = []
    yield
    srv.shutdown()


def test_voices_and_bad_key(server):
    assert [v["name"] for v in tts.list_voices("good")] == ["adam", "Rachel"]
    with pytest.raises(tts.TTSError, match="не прийняв"):
        tts.list_voices("bad")
    with pytest.raises(tts.TTSError, match="API-ключ"):
        tts.list_voices("")


def test_synthesize_cached(server, tmp_path):
    cfg = tts.TTSConfig(api_key="good", voice_id="v2")
    mp3, words = tts.synthesize("Teach your kid  to ask", cfg, tmp_path)
    assert mp3.read_bytes() == b"ID3fake"
    assert [w["w"] for w in words] == ["Teach", "your", "kid", "to", "ask"]
    assert words[0] == {"w": "Teach", "s": 0.0, "e": 0.5} and words[3]["s"] == 1.6
    path, body = Fake.calls[0]
    assert path.startswith("/v1/text-to-speech/v2/with-timestamps") and body["model_id"] == tts.DEFAULT_MODEL
    tts.synthesize("Teach your kid  to ask", cfg, tmp_path)          # з кешу — без запиту
    assert len(Fake.calls) == 1
    tts.synthesize("Teach your kid  to ask", cfg, tmp_path, voice_id="v1")  # інший голос — новий запит
    assert len(Fake.calls) == 2


def test_fit_slots():
    from memocut.core.project import fit_slots
    b = Brief(name="x", source_dir=".", slots=[Slot(any=True, duration=3), Slot(any=True, duration=7.5),
                                                Slot(clip="a.mp4", start=0, end=2), Slot(find="ок")])
    fit_slots(b, 28.0)                       # 2 с фіксовані, 26 с ділимо пропорційно 3 : 7.5 : 3
    assert [s.duration for s in b.slots] == [5.78, 14.44, None, 5.78]
