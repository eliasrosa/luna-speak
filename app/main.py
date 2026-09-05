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

# contador de uso acumulado por engine (reinicia a cada boot do processo)
ENGINE_COUNTS = {"edge": 0, "piper": 0}

app = FastAPI(title="LunaSpeak", version="0.1.0")

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


class SayRequest(BaseModel):
    text: str
    chat_id: str
    caption: str | None = None


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


@app.post("/say")
async def say(req: SayRequest):
    if not req.text.strip():
        raise HTTPException(400, "text vazio")
    # gate de "resposta curta": texto acima do teto vira áudio longo e ruim de ouvir.
    # Recusamos com 413 e um payload estruturado para o chamador cair pra texto.
    # (Não resumimos aqui — este serviço não tem LLM; e não truncamos, que cortaria
    #  no meio de uma frase. Truncar/resumir/enviar-texto é decisão do orquestrador.)
    if SAY_MAX_CHARS > 0 and len(req.text) > SAY_MAX_CHARS:
        log.info("say recusado too_long chars=%d limit=%d", len(req.text), SAY_MAX_CHARS)
        raise HTTPException(
            status_code=413,
            detail={
                "ok": False,
                "reason": "too_long",
                "chars": len(req.text),
                "limit": SAY_MAX_CHARS,
            },
        )
    workdir = tempfile.mkdtemp(prefix="lunaspeak_")
    ogg = os.path.join(workdir, f"{uuid.uuid4().hex}.ogg")
    engine = "edge"
    edge_error = None  # motivo que disparou o fallback (tipo + mensagem), se houver
    started = time.perf_counter()
    try:
        try:
            if FORCE_PIPER:
                raise RuntimeError("FORCE_PIPER ligado: pulando Edge-TTS")
            await _edge_tts(req.text, ogg)  # 1) padrão: Francisca online
        except Exception as e:
            # CA#2: registra o erro do Edge que causou o fallback (sem o texto do usuário)
            edge_error = f"{type(e).__name__}: {e}"
            log.warning("edge-tts falhou, caindo pro piper: %s", edge_error)
            engine = "piper"                # 2) fallback offline: Piper faber
            _piper_tts(req.text, ogg)
        await _send_voice(req.chat_id, ogg, req.caption)  # 3) envia voice message
        ENGINE_COUNTS[engine] = ENGINE_COUNTS.get(engine, 0) + 1
        # CA#1: log estruturado com engine + duração por request
        log.info(
            "say ok engine=%s duration_ms=%d chars=%d fallback_reason=%s",
            engine, (time.perf_counter() - started) * 1000, len(req.text), edge_error or "-",
        )
        return {"ok": True, "engine": engine, "duration_ms": round((time.perf_counter() - started) * 1000)}
    except Exception:
        log.exception(
            "say erro engine=%s duration_ms=%d",
            engine, (time.perf_counter() - started) * 1000,
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
        "engine_counts": ENGINE_COUNTS,
    }
