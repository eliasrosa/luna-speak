"""Normalização de texto pra TTS: tira o que a voz lê mal (markdown, código,
URLs cruas, emojis decorativos) e devolve texto falável.

Também detecta conteúdo NÃO-conversacional (blocos de código, tabelas), que a
política usa como sinal pra reprovar o áudio no modo `auto`.
"""
import re

# blocos de código ```...``` e tabelas markdown | a | b | são sinais fortes de
# conteúdo técnico — TTS lê péssimo.
_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]+`")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_URL = re.compile(r"https?://\S+")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")  # [texto](url) -> texto
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*|_|~~|#+\s?)")
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF]+",
    flags=re.UNICODE,
)
_MULTISPACE = re.compile(r"[ \t]{2,}")
_MULTINEWLINE = re.compile(r"\n{3,}")


def has_structural_content(text: str) -> bool:
    """True se o texto tem código/tabela — conteúdo que não deve virar áudio."""
    if _CODE_FENCE.search(text):
        return True
    if _TABLE_ROW.search(text):
        return True
    return False


def normalize(text: str) -> str:
    """Converte markdown/ruído em texto falável. Best-effort, não valida."""
    t = _CODE_FENCE.sub(" ", text)
    t = _MD_LINK.sub(r"\1", t)          # mantém o rótulo, descarta a URL
    t = _URL.sub(" ", t)
    t = _INLINE_CODE.sub(lambda m: m.group(0).strip("`"), t)
    t = _MD_EMPHASIS.sub("", t)
    t = _EMOJI.sub("", t)
    t = _MULTISPACE.sub(" ", t)
    t = _MULTINEWLINE.sub("\n\n", t)
    return t.strip()
