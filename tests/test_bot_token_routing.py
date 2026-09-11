"""Testa o roteamento de bot por request (bot_token opcional, fallback pro env).

Cenário multi-conta/multi-canal: o chamador pode mandar `bot_token` no request pra
rotear a entrega pra um bot específico (ex. bot da empresa vs. bot pessoal). Se
omitido, cai no TELEGRAM_BOT_TOKEN do env (retrocompatível).
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def main(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "ENV_TOKEN")
    monkeypatch.setenv("STATE_DIR", "/tmp")
    import app.main as m
    importlib.reload(m)
    return m


def _mock_synthesis(monkeypatch, m, captured):
    async def fake_edge(text, ogg_out):
        open(ogg_out, "wb").close()

    def fake_piper(text, ogg_out):
        open(ogg_out, "wb").close()

    async def fake_send(chat_id, ogg_path, caption, bot_token=None):
        captured["chat_id"] = chat_id
        captured["bot_token"] = bot_token

    monkeypatch.setattr(m, "_edge_tts", fake_edge)
    monkeypatch.setattr(m, "_piper_tts", fake_piper)
    monkeypatch.setattr(m, "_send_voice", fake_send)


def test_say_bot_token_from_request_is_passed(main, monkeypatch):
    captured = {}
    _mock_synthesis(monkeypatch, main, captured)
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/say", json={"text": "oi", "chat_id": "99", "bot_token": "EMPRESA_TOKEN"})
    assert r.status_code == 200
    assert captured["bot_token"] == "EMPRESA_TOKEN"  # request vence
    assert captured["chat_id"] == "99"


def test_say_bot_token_omitted_falls_back_to_env(main, monkeypatch):
    captured = {}
    _mock_synthesis(monkeypatch, main, captured)
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/say", json={"text": "oi", "chat_id": "1"})
    assert r.status_code == 200
    # bot_token None -> _send_voice cai no BOT_TOKEN do env (o fake recebe None e o
    # fallback real acontece dentro de _send_voice, que aqui está mockado)
    assert captured["bot_token"] is None


def test_voice_maybe_passes_bot_token(main, monkeypatch):
    captured = {}
    _mock_synthesis(monkeypatch, main, captured)
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post(
        "/voice/maybe",
        json={"text": "oi", "chat_id": "5", "intent": "explicit", "bot_token": "B"},
    )
    assert r.status_code == 200
    assert r.json()["decided"] == "audio"
    assert captured["bot_token"] == "B"
