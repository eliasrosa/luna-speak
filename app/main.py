"""LunaSpeak — microserviço TTS com fallback (Edge-TTS Francisca -> Piper faber) e envio via Telegram sendVoice."""
import asyncio
import logging
import os
import subprocess
import tempfile
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# --- observabilidade ---
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("lunaspeak")

# lógica de política de voz, apartada em app/gate/ (extraível pra serviço próprio)
from .gate.policy import decide as gate_decide  # noqa: E402
gate_log = logging.getLogger("lunaspeak.gate")

# contador de uso acumulado por engine (reinicia a cada boot do processo)
ENGINE_COUNTS = {"edge": 0, "piper": 0}

app = FastAPI(title="LunaSpeak", version="0.1.0")

# Voice Gate — domínio de política de voz (app/gate), apartado do TTS.
# Registro tardio no fim do módulo (após synth_and_send existir) evita ciclo.

# --- config (env) ---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
EDGE_VOICE = os.environ.get("EDGE_VOICE", "pt-BR-FranciscaNeural")
EDGE_TIMEOUT = float(os.environ.get("EDGE_TIMEOUT", "8"))
PIPER_BIN = os.environ.get("PIPER_BIN", "/opt/piper/piper")
PIPER_MODEL = os.environ.get("PIPER_MODEL", "/voices/pt_BR-faber-medium.onnx")
OPUS_BITRATE = os.environ.get("OPUS_BITRATE", "32k")
# gate de "resposta curta": teto de caracteres do texto a sintetizar. Acima disso o /say
# recusa com 413 (sinal estruturado) em vez de gerar um áudio longo e ruim de ouvir.
# 0 (ou negativo) desliga o gate. Default ~600 chars ≈ até ~1 min de fala.
SAY_MAX_CHARS = int(os.environ.get("SAY_MAX_CHARS", "600"))
# hook de teste: força o fallback Piper (pula o Edge-TTS) sem precisar cortar a rede
FORCE_PIPER = os.environ.get("FORCE_PIPER", "").lower() in ("1", "true", "yes")

# override de engine por request (#18): "auto" = comportamento atual (Edge -> fallback
# Piper por falha); "offline" = pula o Edge e sintetiza direto no Piper local (rede
# instável / privacidade / cortar latência). O serviço é STATELESS quanto a isso — o
# "modo offline" sticky mora no orquestrador, que passa engine=offline em cada chamada.
VALID_ENGINES = ("auto", "offline")


def _validate_engine(engine: str) -> str:
    if engine not in VALID_ENGINES:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "reason": "invalid_engine", "engine": engine, "allowed": list(VALID_ENGINES)},
        )
    return engine


# estado GLOBAL de engine, persistente no serviço (#22). Supersede o "sticky no
# orquestrador" da #18: liga uma vez via POST /mode, vale pra todos os requests que
# NÃO mandarem engine, e sobrevive a restart (gravado num arquivo em volume).
# Precedência ao sintetizar: engine do request (explícito) > estado global > "auto".
STATE_DIR = os.environ.get("STATE_DIR", "/data")
_STATE_FILE = os.path.join(STATE_DIR, "state.json")
_FACTORY_ENGINE = "auto"


def _load_global_engine() -> str:
    """Lê o estado global do arquivo de volume; default de fábrica se ausente/ilegível."""
    try:
        import json
        with open(_STATE_FILE, encoding="utf-8") as f:
            eng = json.load(f).get("engine")
        return eng if eng in VALID_ENGINES else _FACTORY_ENGINE
    except (OSError, ValueError):
        return _FACTORY_ENGINE


def _save_global_engine(engine: str) -> None:
    """Persiste o estado global no arquivo de volume (best-effort, cria o dir)."""
    import json
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = _STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"engine": engine}, f)
    os.replace(tmp, _STATE_FILE)  # troca atômica


GLOBAL_ENGINE = _load_global_engine()


def _resolve_engine(req_engine: str | None) -> str:
    """Precedência: engine explícito do request vence; senão o estado global."""
    return _validate_engine(req_engine) if req_engine is not None else GLOBAL_ENGINE


class SayRequest(BaseModel):
    text: str
    chat_id: str
    caption: str | None = None
    engine: str | None = None     # omitido -> estado global; "auto"|"offline" = override


def _to_ogg(src: str, dst: str) -> None:
    """Converte áudio (wav/mp3) para OGG/Opus (formato voice message do Telegram)."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-c:a", "libopus", "-b:a", OPUS_BITRATE, dst],
        check=True, capture_output=True,
    )


async def _edge_tts(text: str, ogg_out: str) -> None:
    """Gera OGG com Edge-TTS (Francisca). Levanta em falha/timeout."""
    import edge_tts  # import tardio: só quando usado

    mp3 = ogg_out.replace(".ogg", ".mp3")
    comm = edge_tts.Communicate(text, EDGE_VOICE)
    await asyncio.wait_for(comm.save(mp3), timeout=EDGE_TIMEOUT)
    _to_ogg(mp3, ogg_out)


def _piper_tts(text: str, ogg_out: str) -> None:
    """Fallback offline: gera OGG com Piper (faber, local)."""
    wav = ogg_out.replace(".ogg", ".wav")
    env = {**os.environ, "LD_LIBRARY_PATH": os.path.dirname(PIPER_BIN)}
    subprocess.run(
        [PIPER_BIN, "-m", PIPER_MODEL, "-f", wav],
        input=text.encode(), check=True, capture_output=True, env=env,
    )
    _to_ogg(wav, ogg_out)


async def _send_voice(chat_id: str, ogg_path: str, caption: str | None) -> None:
    if not BOT_TOKEN:
        raise HTTPException(500, "TELEGRAM_BOT_TOKEN não configurado")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice"
    async with httpx.AsyncClient(timeout=30) as client:
        with open(ogg_path, "rb") as f:
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            r = await client.post(url, data=data, files={"voice": ("voice.ogg", f, "audio/ogg")})
    if r.status_code != 200 or not r.json().get("ok"):
        raise HTTPException(502, f"Telegram sendVoice falhou: {r.text[:200]}")


async def synth_and_send(text: str, chat_id: str, caption: str | None = None, engine: str = "auto") -> dict:
    """Sintetiza `text` (Edge->Piper), converte e envia via Telegram sendVoice.

    Núcleo reusável do /say: o handler HTTP e o Voice Gate (app/gate) chamam
    esta função. Levanta em falha (o chamador decide o fallback).

    `engine`: "auto" tenta o Edge-TTS e cai pro Piper por FALHA; "offline" pula o
    Edge e sintetiza direto no Piper local (nenhuma chamada de rede ao Edge).
    """
    _validate_engine(engine)
    if not text.strip():
        raise HTTPException(400, "text vazio")
    # gate de "resposta curta": texto acima do teto vira áudio longo e ruim de ouvir.
    # Recusamos com 413 e um payload estruturado para o chamador cair pra texto.
    # (Não resumimos aqui — este serviço não tem LLM; e não truncamos, que cortaria
    #  no meio de uma frase. Truncar/resumir/enviar-texto é decisão do orquestrador.)
    if SAY_MAX_CHARS > 0 and len(text) > SAY_MAX_CHARS:
        log.info("say recusado too_long chars=%d limit=%d", len(text), SAY_MAX_CHARS)
        raise HTTPException(
            status_code=413,
            detail={
                "ok": False,
                "reason": "too_long",
                "chars": len(text),
                "limit": SAY_MAX_CHARS,
            },
        )
    workdir = tempfile.mkdtemp(prefix="lunaspeak_")
    ogg = os.path.join(workdir, f"{uuid.uuid4().hex}.ogg")
    edge_error = None  # motivo que disparou o fallback (tipo + mensagem), se houver
    started = time.perf_counter()
    try:
        if FORCE_PIPER or engine == "offline":
            # caminho offline EXPLÍCITO (não é o fallback por falha): pula o Edge e
            # sintetiza direto no Piper. Nenhuma chamada de rede ao Edge-TTS.
            engine_used = "piper"
            _piper_tts(text, ogg)
        else:
            engine_used = "edge"
            try:
                await _edge_tts(text, ogg)  # 1) padrão: Francisca online
            except Exception as e:
                # CA#2: registra o erro do Edge que causou o fallback (sem o texto do usuário)
                edge_error = f"{type(e).__name__}: {e}"
                log.warning("edge-tts falhou, caindo pro piper: %s", edge_error)
                engine_used = "piper"       # 2) fallback offline: Piper faber
                _piper_tts(text, ogg)
        await _send_voice(chat_id, ogg, caption)  # 3) envia voice message
        ENGINE_COUNTS[engine_used] = ENGINE_COUNTS.get(engine_used, 0) + 1
        # CA#1: log estruturado com engine + duração por request
        log.info(
            "say ok engine=%s mode=%s duration_ms=%d chars=%d fallback_reason=%s",
            engine_used, engine, (time.perf_counter() - started) * 1000, len(text), edge_error or "-",
        )
        return {"ok": True, "engine": engine_used, "duration_ms": round((time.perf_counter() - started) * 1000)}
    except Exception:
        log.exception(
            "say erro engine=%s duration_ms=%d",
            engine_used, (time.perf_counter() - started) * 1000,
        )
        raise
    finally:
        # limpeza best-effort
        for f in os.listdir(workdir):
            try:
                os.remove(os.path.join(workdir, f))
            except OSError:
                pass
        try:
            os.rmdir(workdir)
        except OSError:
            pass


@app.post("/say")
async def say(req: SayRequest):
    return await synth_and_send(req.text, req.chat_id, req.caption, _resolve_engine(req.engine))


class ModeRequest(BaseModel):
    engine: str                   # "auto" | "offline"


@app.post("/mode")
def set_mode(req: ModeRequest):
    """Grava o estado GLOBAL de engine do serviço (persistente entre restarts).

    Vale pra todo request que NÃO mandar `engine`. Um `engine` explícito no
    request continua vencendo (override pontual, #18). Default de fábrica: auto.
    """
    global GLOBAL_ENGINE
    _validate_engine(req.engine)
    _save_global_engine(req.engine)
    GLOBAL_ENGINE = req.engine
    log.info("mode set global_engine=%s", GLOBAL_ENGINE)
    return {"ok": True, "engine": GLOBAL_ENGINE}


@app.get("/mode")
def get_mode():
    """Estado global vigente + precedência efetiva."""
    return {"engine": GLOBAL_ENGINE, "precedence": "request > global > factory(auto)"}


@app.get("/health")
def health():
    return {
        "ok": True,
        "edge_voice": EDGE_VOICE,
        "piper_model": PIPER_MODEL,
        "piper_available": os.path.exists(PIPER_BIN),
        "token_configured": bool(BOT_TOKEN),
        "force_piper": FORCE_PIPER,
        "say_max_chars": SAY_MAX_CHARS,
        "engines": list(VALID_ENGINES),
        "global_engine": GLOBAL_ENGINE,
        "engine_counts": ENGINE_COUNTS,
    }


# --- Voice Gate: política de voz (o "quando" da issue #3) ---
# A LÓGICA (decisão + normalização) vive apartada em app/gate/. Só o handler HTTP
# mora aqui, pra reusar `app` e `synth_and_send` sem import tardio nem ciclo.
class MaybeRequest(BaseModel):
    text: str
    chat_id: str
    intent: str = "auto"          # "explicit" (usuário pediu voz) | "auto"
    channel: str = "telegram"
    caption: str | None = None
    engine: str | None = None     # omitido -> estado global; "auto"|"offline" = override


@app.post("/voice/maybe")
async def voice_maybe(req: MaybeRequest):
    """Entrada do orquestrador (Kiro): 'cabe áudio?'. Nunca é o caminho crítico
    da resposta — o Kiro já entregou o texto pelo seu próprio canal."""
    engine = _resolve_engine(req.engine)  # 400 em engine inválido; None -> estado global
    d = gate_decide(req.text, req.intent, req.channel, SAY_MAX_CHARS)
    if not d.audio:
        gate_log.info("gate decided=text reason=%s chars=%d", d.reason, len(req.text))
        return {"decided": "text", "reason": d.reason}
    try:
        result = await synth_and_send(d.text, req.chat_id, req.caption, engine)
    except Exception as e:  # o gate absorve a falha do TTS: 1 ponto de falha pro Kiro
        gate_log.warning("gate approved but synth failed: %s: %s", type(e).__name__, e)
        return {"decided": "text", "reason": "service_down"}
    gate_log.info("gate decided=audio reason=%s engine=%s", d.reason, result.get("engine"))
    return {"decided": "audio", "reason": d.reason, **result}
