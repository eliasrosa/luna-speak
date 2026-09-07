"""Testes do endpoint POST /notify (#28): envia mensagem de TEXTO via Bot API sendMessage.

Cobrimos: sucesso (mock do httpx -> ok:true + message_id), token ausente (500),
e falha do Telegram (502 propagando o motivo). O httpx é mockado pra não bater na rede.
"""
import importlib
import os

import httpx
from fastapi.testclient import TestClient


class _FakeResp:
    def __init__(self, status_code, payload, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


class _FakeClient:
    """Substitui httpx.AsyncClient como context manager assíncrono."""
    _resp = _FakeResp(200, {"ok": True, "result": {"message_id": 42}})

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return self._resp


def _client(token="dummy-token", resp=None):
    if token is None:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    else:
        os.environ["TELEGRAM_BOT_TOKEN"] = token
    import app.main as main
    importlib.reload(main)
    if resp is not None:
        _FakeClient._resp = resp
    else:
        _FakeClient._resp = _FakeResp(200, {"ok": True, "result": {"message_id": 42}})
    main.httpx.AsyncClient = _FakeClient
    return TestClient(main.app, raise_server_exceptions=False)


def test_notify_success():
    client = _client()
    r = client.post("/notify", json={"chat_id": "-100123", "text": "alerta de teste"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["message_id"] == 42
    assert body["chat_id"] == "-100123"


def test_notify_no_token_returns_500():
    client = _client(token=None)
    r = client.post("/notify", json={"chat_id": "-100123", "text": "oi"})
    assert r.status_code == 500


def test_notify_telegram_failure_returns_502():
    bad = _FakeResp(400, {"ok": False, "description": "Bad Request: chat not found"},
                    text='{"ok":false,"description":"Bad Request: chat not found"}')
    client = _client(resp=bad)
    r = client.post("/notify", json={"chat_id": "-100999", "text": "oi"})
    assert r.status_code == 502
