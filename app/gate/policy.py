"""Política de voz: decide áudio vs texto (o "quando" da issue #3).

Gate = AND de duas portas:
  A) intenção  — usuário pediu voz (explicit) OU é papo curto/conversacional (auto)
  B) elegibilidade — cabe no limite, sem código/tabela, canal suportado

O LIMITE de tamanho NÃO é definido aqui: é o mesmo `SAY_MAX_CHARS` do /say
(uma fonte de verdade), passado como parâmetro `max_chars` por quem chama.
O gate decide `too_long` ANTES de sintetizar (evita a chamada e dá um motivo
limpo); o /say ainda revalida o mesmo teto como defesa em profundidade.
"""
import os
from dataclasses import dataclass

from .normalize import has_structural_content, normalize

# modo no estouro (política de voz, não é o limite): "text" (cai pra texto) |
# "truncate" (corta no limite e ainda fala). Default "text", coerente com o /say.
OVERFLOW_MODE = os.environ.get("VOICE_OVERFLOW_MODE", "text").lower()
SUPPORTED_CHANNELS = {"telegram"}


@dataclass
class Decision:
    audio: bool
    reason: str           # motivo legível (aprovado ou por que reprovou)
    text: str             # texto normalizado pra TTS (só relevante se audio=True)


def decide(text: str, intent: str, channel: str, max_chars: int) -> Decision:
    """Aplica o gate. `intent` = 'explicit' | 'auto'.

    `max_chars` = teto de caracteres (o SAY_MAX_CHARS do serviço). <=0 desliga
    a checagem de tamanho (igual ao /say).
    """
    if channel not in SUPPORTED_CHANNELS:
        return Decision(False, f"unsupported_channel:{channel}", "")

    # Porta B (elegibilidade de conteúdo) vale pras duas intenções
    if has_structural_content(text):
        return Decision(False, "has_code_or_table", "")

    spoken = normalize(text)
    if not spoken:
        return Decision(False, "empty_after_normalize", "")

    over = max_chars > 0 and len(spoken) > max_chars

    # Porta A: explicit passa direto; auto exige que caiba (proxy de "curto")
    if intent == "explicit":
        if over and OVERFLOW_MODE == "truncate":
            spoken = spoken[:max_chars].rstrip()
        elif over:
            return Decision(False, "too_long", "")
        return Decision(True, "explicit_request", spoken)

    # intent == "auto": só vira áudio se for curto (conversacional)
    if over:
        if OVERFLOW_MODE == "truncate":
            return Decision(True, "auto_truncated", spoken[:max_chars].rstrip())
        return Decision(False, "too_long", "")
    return Decision(True, "auto_conversational", spoken)
