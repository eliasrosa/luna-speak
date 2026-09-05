"""LunaSpeak — microserviço TTS com fallback (Edge-TTS Francisca -> Piper faber) e envio via Telegram sendVoice."""
import asyncio
import os
import subprocess
import tempfile
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="LunaSpeak", version="0.1.0")

# --- config (env) ---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
EDGE_VOICE = os.environ.get("EDGE_VOICE", "pt-BR-FranciscaNeural")
EDGE_TIMEOUT = float(os.environ.get("EDGE_TIMEOUT", "8"))
PIPER_BIN = os.environ.get("PIPER_BIN", "/opt/piper/piper")
PIPER_MODEL = os.environ.get("PIPER_MODEL", "/voices/pt_BR-faber-medium.onnx")
OPUS_BITRATE = os.environ.get("OPUS_BITRATE", "32k")
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
    workdir = tempfile.mkdtemp(prefix="lunaspeak_")
    ogg = os.path.join(workdir, f"{uuid.uuid4().hex}.ogg")
    engine = "edge"
    try:
        try:
            if FORCE_PIPER:
                raise RuntimeError("FORCE_PIPER ligado: pulando Edge-TTS")
            await _edge_tts(req.text, ogg)  # 1) padrão: Francisca online
        except Exception:
            engine = "piper"                # 2) fallback offline: Piper faber
            _piper_tts(req.text, ogg)
        await _send_voice(req.chat_id, ogg, req.caption)  # 3) envia voice message
        return {"ok": True, "engine": engine}
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
    }
