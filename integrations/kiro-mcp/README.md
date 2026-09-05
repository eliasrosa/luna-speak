# Integração: orquestrador → LunaSpeak (MCP `voice-gate`)

Lado do **orquestrador** da issue #3. O serviço LunaSpeak expõe o **Voice Gate**
(`POST /voice/maybe`, ver `app/gate/`); esta pasta traz o **cliente MCP** que o
orquestrador (um agente que fala com o usuário, ex. via Telegram) usa pra chamar
esse gate no seu próprio turno.

```
Agente compõe a resposta (texto, sempre entregue no chat)
   │ decide: cabe áudio? → chama a tool MCP:
   ▼  voice_maybe(text, chat_id, intent)
[voice-gate MCP] --HTTP--> POST {LUNASPEAK_URL}/voice/maybe
        ├─ gate reprova → {decided:"text"}
        └─ aprova → /say → Telegram sendVoice
```

O áudio é **camada opcional**: o texto já foi entregue; se o gate reprovar ou o
serviço estiver fora, a tool devolve `{"decided":"text", ...}` e nada mais é
preciso.

## O que é (e o que NÃO é)

- É um **wrapper fino e sem estado**: só repassa `{text, chat_id, intent, channel}`
  ao gate e devolve o JSON. Nenhuma regra de política vive aqui — ela mora no
  serviço (`app/gate/policy.py`).
- **Nada pessoal/local** neste diretório (repo público): o endereço do serviço
  vem só da env `LUNASPEAK_URL`; token do bot e `chat_id` reais **nunca** entram
  aqui.

## Instalação

1. Copie `voice_gate_mcp.py` para onde o orquestrador possa executá-lo.
2. Instale as deps: `pip install -r requirements.txt` (precisa do SDK `mcp` e `httpx`).
3. Registre o server na config MCP do agente (ver `kirocrew.mcp.example.json`),
   preenchendo o caminho absoluto do script e a `LUNASPEAK_URL`. Reinicie o agente
   e confirme que a tool `voice_maybe` ficou disponível.

## Contrato da tool

```
voice_maybe(text: str, chat_id: str, intent: "explicit"|"auto" = "auto") -> dict
→ {"decided": "audio", "engine": "edge"|"piper", "duration_ms": N, "reason": "..."}
→ {"decided": "text",  "reason": "too_long"|"has_code_or_table"|"unsupported_channel:<x>"
                                  |"service_down"|"unreachable:<E>"|"http_<code>"|"lunaspeak_url_unset"}
```

## Regra de ativação (o "quando") — cola no prompt/steering do orquestrador

> Ao terminar uma resposta que caiba em voz, chame `voice_maybe(text, chat_id, intent)`.
> - `intent="explicit"` se o usuário pediu áudio ou mandou um áudio (espera áudio de volta);
> - `intent="auto"` se a resposta é curta e conversacional (não técnica: sem código, tabela ou link);
> - Em dúvida, **não chame** — texto é o padrão.
> - `chat_id` é o da conversa atual do canal.
> - Ignore o retorno `decided:"text"` — o usuário já tem o texto.

## Notas de deploy

- O **limite de tamanho** é decidido pelo gate usando o `SAY_MAX_CHARS` do próprio
  serviço (fonte única) — o cliente não replica isso.
- Requer que o serviço LunaSpeak esteja no ar e alcançável em `LUNASPEAK_URL`.
- O `sendVoice` sai com o **token do bot configurado no serviço**: pra o áudio
  chegar na mesma conversa em que o usuário fala com o agente, o serviço deve usar
  o token **desse** bot (config do serviço, fora deste repo).
