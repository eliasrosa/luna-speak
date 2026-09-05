"""MCP server 'voice-gate' — expõe a tool `voice_maybe` pro orquestrador.

Peça do lado do ORQUESTRADOR (Kiro Crew) da integração: o agente chama esta
tool ao produzir uma resposta candidata a áudio; ela repassa ao Voice Gate do
LunaSpeak (`POST /voice/maybe`), que decide áudio×texto e, se aprovar, sintetiza
e envia o voice message no Telegram.

Wrapper fino e sem estado: nenhuma decisão de política vive aqui (mora no gate,
`app/gate/`). O endereço do serviço vem SÓ da env `LUNASPEAK_URL` — nunca
hardcoded, nunca commitado. Nada pessoal/local neste arquivo (repo público).

Registro: ver README.md deste diretório.
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("voice-gate")

# URL do serviço LunaSpeak. Obrigatória; definida no registro do MCP server
# (env), fora do repo. Ex.: http://<host>:<porta>
LUNASPEAK_URL = os.environ.get("LUNASPEAK_URL", "").rstrip("/")
HTTP_TIMEOUT = float(os.environ.get("VOICE_GATE_TIMEOUT", "20"))


@mcp.tool()
async def voice_maybe(text: str, chat_id: str, intent: str = "auto") -> dict:
    """Talvez responder em áudio via LunaSpeak (o texto JÁ foi entregue no chat).

    Chame ao terminar uma resposta que caiba em voz. O gate decide de fato se
    vira áudio; áudio é camada opcional e nunca é o caminho crítico da resposta.

    Args:
        text: a resposta a falar (pode ter markdown — o gate normaliza).
        chat_id: id da conversa atual do Telegram (destino do voice message).
        intent: "explicit" (o usuário pediu voz / mandou áudio) ou
                "auto" (resposta curta/conversacional). Em dúvida, use "auto".

    Returns:
        {"decided": "audio"|"text", "reason": str, "engine"?: str, "duration_ms"?: int}
        decided="text" = não virou áudio (reprovado no gate ou serviço fora);
        nesse caso nada mais é preciso — o usuário já tem o texto.
    """
    if not LUNASPEAK_URL:
        return {"decided": "text", "reason": "lunaspeak_url_unset"}
    payload = {"text": text, "chat_id": chat_id, "intent": intent, "channel": "telegram"}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(f"{LUNASPEAK_URL}/voice/maybe", json=payload)
    except Exception as e:
        # serviço fora/inatingível: cai pra texto sem quebrar o turno
        return {"decided": "text", "reason": f"unreachable:{type(e).__name__}"}
    if r.status_code != 200:
        return {"decided": "text", "reason": f"http_{r.status_code}"}
    return r.json()


if __name__ == "__main__":
    mcp.run()
