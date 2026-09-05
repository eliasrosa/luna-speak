"""Regressão do gate de 'resposta curta' (#4): /say recusa texto acima de SAY_MAX_CHARS.

Antes da correção não havia gate: um texto longo seguia pra síntese (e, em teste, só
falharia lá na frente por falta de engine/token). Depois, /say responde 413 too_long
antes de qualquer síntese. Cobrimos: acima do teto -> 413 estruturado; no teto -> passa
do gate; gate desligado (0) -> passa do gate.
"""
import importlib
import os

from fastapi.testclient import TestClient


def _client(max_chars: str) -> TestClient:
    os.environ["SAY_MAX_CHARS"] = max_chars
    # sem token: garante que, SE passar do gate, o erro é outro (não 413) — isola o gate
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    import app.main as main
    importlib.reload(main)
    return TestClient(main.app, raise_server_exceptions=False)


def test_say_rejects_text_over_limit():
    client = _client("50")
    r = client.post("/say", json={"text": "x" * 51, "chat_id": "123"})
    assert r.status_code == 413
    detail = r.json()["detail"]
    assert detail["reason"] == "too_long"
    assert detail["chars"] == 51
    assert detail["limit"] == 50


def test_say_allows_text_at_limit_passes_gate():
    client = _client("50")
    # exatamente no teto: não é 413 (passa do gate). Sem engine/token vira 5xx, não 413.
    r = client.post("/say", json={"text": "x" * 50, "chat_id": "123"})
    assert r.status_code != 413


def test_gate_disabled_when_zero():
    client = _client("0")
    r = client.post("/say", json={"text": "x" * 5000, "chat_id": "123"})
    assert r.status_code != 413


def test_health_reports_limit():
    client = _client("600")
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["say_max_chars"] == 600
