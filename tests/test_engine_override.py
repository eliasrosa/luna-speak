"""Regressão do override de engine por request (#18): engine=auto|offline.

Cobre:
- engine=offline NÃO chama o Edge-TTS (só Piper) e responde engine=piper;
- engine omitido/auto mantém o comportamento atual (tenta o Edge primeiro);
- engine inválido -> 400 estruturado (reason=invalid_engine) nos dois endpoints;
- /health expõe as engines suportadas.

Mockamos _edge_tts / _piper_tts / _send_voice pra testar o roteamento de engine
sem rede nem binário do Piper.
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


def _load():
    os.environ.pop("FORCE_PIPER", None)   # garante que o roteamento vem do param, não do env
    os.environ["SAY_MAX_CHARS"] = "0"     # desliga o gate de tamanho pra isolar a engine
    import app.main as main
    importlib.reload(main)
    return main


@pytest.fixture()
def main(monkeypatch):
    m = _load()
    calls = {"edge": 0, "piper": 0, "send": 0}

    async def fake_edge(text, ogg_out):
        calls["edge"] += 1
        open(ogg_out, "wb").close()

    def fake_piper(text, ogg_out):
        calls["piper"] += 1
        open(ogg_out, "wb").close()

    async def fake_send(chat_id, ogg_path, caption):
        calls["send"] += 1

    monkeypatch.setattr(m, "_edge_tts", fake_edge)
    monkeypatch.setattr(m, "_piper_tts", fake_piper)
    monkeypatch.setattr(m, "_send_voice", fake_send)
    m._calls = calls
    return m


def test_offline_skips_edge(main):
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/say", json={"text": "oi", "chat_id": "1", "engine": "offline"})
    assert r.status_code == 200
    assert r.json()["engine"] == "piper"
    assert main._calls["edge"] == 0      # NENHUMA chamada de rede ao Edge
    assert main._calls["piper"] == 1


def test_auto_tries_edge_first(main):
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/say", json={"text": "oi", "chat_id": "1", "engine": "auto"})
    assert r.status_code == 200
    assert r.json()["engine"] == "edge"
    assert main._calls["edge"] == 1
    assert main._calls["piper"] == 0


def test_engine_omitted_defaults_auto(main):
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/say", json={"text": "oi", "chat_id": "1"})
    assert r.status_code == 200
    assert r.json()["engine"] == "edge"
    assert main._calls["edge"] == 1


def test_say_invalid_engine_400(main):
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/say", json={"text": "oi", "chat_id": "1", "engine": "gpu"})
    assert r.status_code == 400
    assert r.json()["detail"]["reason"] == "invalid_engine"
    assert main._calls["edge"] == 0 and main._calls["piper"] == 0


def test_voice_maybe_offline_skips_edge(main):
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/voice/maybe", json={"text": "oi", "chat_id": "1", "intent": "explicit", "engine": "offline"})
    assert r.status_code == 200
    body = r.json()
    assert body["decided"] == "audio"
    assert body["engine"] == "piper"
    assert main._calls["edge"] == 0


def test_voice_maybe_invalid_engine_400(main):
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/voice/maybe", json={"text": "oi", "chat_id": "1", "engine": "gpu"})
    assert r.status_code == 400
    assert r.json()["detail"]["reason"] == "invalid_engine"


def test_health_reports_engines(main):
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["engines"] == ["auto", "offline"]
