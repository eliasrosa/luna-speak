"""Regressão do toggle global de engine persistente (#22): POST/GET /mode.

Cobre:
- POST /mode {engine} altera o estado global; GET /mode e /health expõem;
- request com `engine` explícito VENCE o global (override da #18 preservado);
- request SEM `engine` usa o estado global;
- `engine` inválido -> 400 (no /mode e no request);
- persistência: o estado sobrevive a um "restart" (reload do módulo lê o state.json).

Usa um STATE_DIR temporário por teste (tmp_path) pra não tocar em /data.
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


def _load(state_dir: str):
    os.environ["STATE_DIR"] = state_dir
    os.environ.pop("FORCE_PIPER", None)
    os.environ["SAY_MAX_CHARS"] = "0"
    import app.main as main
    importlib.reload(main)
    return main


@pytest.fixture()
def main(tmp_path, monkeypatch):
    m = _load(str(tmp_path))
    calls = {"edge": 0, "piper": 0}

    async def fake_edge(text, ogg_out):
        calls["edge"] += 1
        open(ogg_out, "wb").close()

    def fake_piper(text, ogg_out):
        calls["piper"] += 1
        open(ogg_out, "wb").close()

    async def fake_send(chat_id, ogg_path, caption):
        pass

    monkeypatch.setattr(m, "_edge_tts", fake_edge)
    monkeypatch.setattr(m, "_piper_tts", fake_piper)
    monkeypatch.setattr(m, "_send_voice", fake_send)
    m._calls = calls
    return m


def test_factory_default_is_auto(main):
    c = TestClient(main.app, raise_server_exceptions=False)
    assert c.get("/mode").json()["engine"] == "auto"
    assert c.get("/health").json()["global_engine"] == "auto"


def test_post_mode_sets_global(main):
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.post("/mode", json={"engine": "offline"})
    assert r.status_code == 200 and r.json()["engine"] == "offline"
    assert c.get("/mode").json()["engine"] == "offline"


def test_request_without_engine_uses_global(main):
    c = TestClient(main.app, raise_server_exceptions=False)
    c.post("/mode", json={"engine": "offline"})
    r = c.post("/say", json={"text": "oi", "chat_id": "1"})   # sem engine -> global
    assert r.json()["engine"] == "piper"
    assert main._calls["edge"] == 0


def test_explicit_request_engine_wins_over_global(main):
    c = TestClient(main.app, raise_server_exceptions=False)
    c.post("/mode", json={"engine": "offline"})               # global = offline
    r = c.post("/say", json={"text": "oi", "chat_id": "1", "engine": "auto"})  # override
    assert r.json()["engine"] == "edge"                       # request venceu o global
    assert main._calls["edge"] == 1


def test_voice_maybe_uses_global(main):
    c = TestClient(main.app, raise_server_exceptions=False)
    c.post("/mode", json={"engine": "offline"})
    r = c.post("/voice/maybe", json={"text": "oi", "chat_id": "1", "intent": "explicit"})
    body = r.json()
    assert body["decided"] == "audio" and body["engine"] == "piper"
    assert main._calls["edge"] == 0


def test_invalid_engine_400(main):
    c = TestClient(main.app, raise_server_exceptions=False)
    assert c.post("/mode", json={"engine": "gpu"}).status_code == 400
    assert c.post("/say", json={"text": "oi", "chat_id": "1", "engine": "gpu"}).status_code == 400


def test_state_persists_across_restart(main, tmp_path):
    c = TestClient(main.app, raise_server_exceptions=False)
    c.post("/mode", json={"engine": "offline"})
    # "restart": recarrega o módulo apontando pro MESMO STATE_DIR -> lê o state.json
    reloaded = _load(str(tmp_path))
    assert reloaded.GLOBAL_ENGINE == "offline"
    assert TestClient(reloaded.app).get("/mode").json()["engine"] == "offline"
