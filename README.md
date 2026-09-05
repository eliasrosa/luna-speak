# LunaSpeak 🔊

Microserviço de **TTS (text-to-speech)** do assistente Luna/Kiro: recebe um texto, sintetiza voz em pt-BR e envia como **voice message** no Telegram.

Roda no homelab (ZimaOS). O Kiro (orquestrador) chama o LunaSpeak quando decide responder em áudio.

## Arquitetura — voz com fallback resiliente

```
POST /say { text, chat_id }
   │
   ├─ 1. Francisca (Edge-TTS, online, voz feminina natural)   ← padrão
   │        └─ timeout curto (default 8s)
   │
   ├─ 2. (falha/timeout/sem rede) → Piper faber (offline, local, sempre funciona)  ← fallback
   │
   ├─ 3. converte pra OGG/Opus (formato voice message)
   └─ 4. Telegram Bot API sendVoice → chat
        └─ responde { ok, engine: "edge"|"piper", duration }
```

- **Padrão:** Edge-TTS voz **pt-BR-FranciscaNeural** (feminina, natural, grátis, mas online).
- **Fallback:** **Piper** voz `pt_BR-faber-medium` (masculina, 100% offline/local, rápida ~1s) — garante que SEMPRE sai áudio, mesmo sem internet.
- Fallback dispara por **falha/timeout** do Edge-TTS, não só por demora.

## Stack
- Python 3.12 + FastAPI + uvicorn
- `edge-tts` (Francisca) · Piper binário standalone (fallback) · ffmpeg (→ ogg/opus)
- Telegram Bot API (`sendVoice`)

## Rodar

### Local (dev)
```bash
cp .env.example .env   # OBRIGATÓRIO: preencher TELEGRAM_BOT_TOKEN
docker compose up --build
# POST http://localhost:8033/say
curl -X POST localhost:8033/say -H 'Content-Type: application/json' \
  -d '{"text":"Olá, tudo certo?","chat_id":"<CHAT_ID>"}'
```

> ⚠️ O `docker-compose.yml` usa `env_file: .env`. Se você pular o `cp .env.example .env`,
> o `docker compose up` falha com `env file .env not found`. Copie o `.env` **antes** de subir.

**Validar o fallback Piper sem cortar a rede:** ligue `FORCE_PIPER=1` no `.env` (ou
`FORCE_PIPER=1 docker compose up`). Com a flag, o `/say` pula o Edge-TTS e vai direto pro
Piper — a resposta volta com `"engine":"piper"`. Deixe vazio em produção.

### ZimaOS (produção)
Deploy via `docker-compose-zimaos.yml` (imagem local, sem registry). Colocar o `.env` ao lado do compose no diretório do app e `docker compose up -d`.

## Endpoints
- `POST /say { text, chat_id, engine? }` — sintetiza e envia voice message. Retorna `{ok, engine, duration}`. Se o `text` passar de `SAY_MAX_CHARS`, responde **HTTP 413** com `{ok:false, reason:"too_long", chars, limit}` e **não** gera áudio (ver "Gate de resposta curta"). `engine` (`auto`|`offline`, default `auto`) escolhe a engine — ver "Modo offline".
- `POST /voice/maybe { text, chat_id, intent?, channel?, engine? }` — entrada do **orquestrador**: aplica o gate de política ("cabe áudio?") e, se aprovar, sintetiza e envia. Retorna `{decided:"audio", engine, duration_ms, reason}` ou `{decided:"text", reason}` (`reason` ∈ `too_long` | `has_code_or_table` | `empty_after_normalize` | `unsupported_channel:<x>` | `service_down`). `intent` = `explicit` (usuário pediu voz) | `auto` (conversacional, default).
- `GET /health` — status + engines disponíveis (inclui `edge_voice`, `piper_available`, `token_configured`, `force_piper`, `say_max_chars`, `engines`, `global_engine`).
- `POST /mode { engine }` — grava o **estado global** de engine do serviço (`auto`|`offline`), **persistente** entre restarts. `GET /mode` devolve o estado vigente. Ver "Modo offline".

## Configuração (env)

Tudo é configurável por env, **sem rebuild** (edite o `.env` e reinicie). Ver `.env.example`.

| Env | Default | O que faz |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *(vazio)* | Token do bot que envia o `sendVoice`. **Obrigatório**; só no `.env`/secrets. |
| `EDGE_VOICE` | `pt-BR-FranciscaNeural` | Voz do Edge-TTS (ver "Escolha de voz"). |
| `EDGE_TIMEOUT` | `8` | Timeout (s) do Edge-TTS antes de cair pro Piper. |
| `SAY_MAX_CHARS` | `600` | Teto de caracteres do `text`; acima disso recusa (ver "Gate de resposta curta"). `0` desliga. |
| `OPUS_BITRATE` | `32k` | Bitrate do OGG/Opus gerado pelo ffmpeg. |
| `FORCE_PIPER` | *(vazio)* | `1`/`true` força o Piper (pula o Edge) — hook de teste. Vazio em produção. |
| `VOICE_OVERFLOW_MODE` | `text` | Política do gate no estouro: `text` (cai pra texto) ou `truncate` (corta e fala). |
| `LOG_LEVEL` | `INFO` | Nível de log (`DEBUG`/`INFO`/`WARNING`/`ERROR`). |
| `PIPER_BIN` / `PIPER_MODEL` | *(paths do container)* | Binário e modelo do Piper (raramente mudam). |

O parâmetro `engine` (`auto`|`offline`) é **por request**, não env — ver "Modo offline".

## Integração com o orquestrador

O `POST /voice/maybe` é o ponto de entrada do **orquestrador** (o agente que fala com
o usuário). A pasta [`integrations/kiro-mcp/`](integrations/kiro-mcp/README.md) traz o
**cliente MCP** (`voice_maybe`) que o agente chama no seu turno, mais a regra de
ativação pra colar no steering dele. O cliente é um wrapper fino e sem estado; a
política de voz mora no serviço (`app/gate/`).

## Documentação interna

- [`.kiro/steering/architecture.md`](.kiro/steering/architecture.md) — decisões de design, fluxo de dados, fronteiras de módulo, os 3 eixos do gate.
- [`.kiro/steering/conventions.md`](.kiro/steering/conventions.md) — env/config, higiene de repo público, estilo de issue/commit.
- [`.kiro/steering/deploy.md`](.kiro/steering/deploy.md) — deploy no ZimaOS.

## Escolha de voz

A voz do Edge-TTS é configurável pela env `EDGE_VOICE` — **troca sem rebuild**:
edite o `.env` (ou passe a env na subida) e reinicie o container. O fallback
offline continua sendo o Piper `faber` automaticamente, independente da voz do Edge.

```bash
# trocar a voz padrão sem rebuildar a imagem
EDGE_VOICE=pt-BR-ThalitaNeural docker compose up
# ou, persistente: edite EDGE_VOICE no .env e `docker compose restart`
```

Confirme a voz ativa no `GET /health` (campo `edge_voice`).

### Vozes disponíveis

Vozes **femininas nativas pt-BR** do Edge-TTS:

| `EDGE_VOICE`             | Descrição                                  |
|--------------------------|--------------------------------------------|
| `pt-BR-FranciscaNeural`  | Feminina pt-BR, natural — **padrão**       |
| `pt-BR-ThalitaNeural`    | Feminina pt-BR, timbre alternativo         |

Vozes **multilíngues** (falam pt com sotaque levemente não-nativo, timbre mais
"assistente"):

| `EDGE_VOICE`                 | Descrição                                  |
|------------------------------|--------------------------------------------|
| `en-US-AvaMultilingual`      | Multilíngue, expressiva                     |
| `en-US-EmmaMultilingual`     | Multilíngue, conversacional                 |

> Para a lista completa de vozes suportadas: `edge-tts --list-voices`.
> O Piper (fallback offline) usa sempre `pt_BR-faber-medium` (masculina) e **não**
> é afetado por `EDGE_VOICE`.

## Gate de resposta curta

Áudio de resposta longa é ruim de ouvir; o serviço foca em respostas curtas. A env
`SAY_MAX_CHARS` define o **teto de caracteres** do `text` — **configurável sem rebuild**:

```bash
SAY_MAX_CHARS=600 docker compose up     # ~600 chars ≈ até ~1 min de fala (default)
SAY_MAX_CHARS=0   docker compose up      # desliga o gate (aceita qualquer tamanho)
```

Quando o `text` passa do teto, o `/say` responde **HTTP 413** e **não** sintetiza:

```json
{ "ok": false, "reason": "too_long", "chars": 812, "limit": 600 }
```

Esse 413 é um **sinal pro chamador (o orquestrador) cair pra texto** — mandar a
resposta escrita em vez de áudio. O LunaSpeak deliberadamente **não** trunca (cortaria
no meio de uma frase) nem resume (este serviço não tem LLM): truncar, resumir ou enviar
texto é decisão de quem chama o `/say`. Confirme o teto ativo no `GET /health`
(campo `say_max_chars`).

## Modo offline (`engine`)

`POST /say` e `POST /voice/maybe` aceitam um parâmetro opcional `engine`:

| `engine`  | Comportamento                                                        |
|-----------|----------------------------------------------------------------------|
| `auto`    | **default** — tenta o Edge-TTS (online) e cai pro Piper por **falha** |
| `offline` | pula o Edge e sintetiza **direto no Piper local** — nenhuma chamada de rede ao Edge |

```jsonc
POST /say      { "text": "...", "chat_id": "<CHAT_ID>", "engine": "offline" }
POST /voice/maybe { "text": "...", "chat_id": "<CHAT_ID>", "intent": "explicit", "engine": "offline" }
```

Use `offline` quando a rede estiver instável, por privacidade (não bater em servidor
externo), ou pra cortar latência de rede. `engine` inválido → **HTTP 400**
`{ok:false, reason:"invalid_engine", allowed:["auto","offline"]}`.

### Estado global + precedência (toggle)

O modo tem duas formas de ser escolhido, com **precedência clara**:

**request > estado global > default de fábrica (`auto`)**

- **Por request** (override pontual): mande `engine` no `/say` ou `/voice/maybe`. Vence sempre.
- **Estado global** (persistente no serviço): `POST /mode { "engine": "offline" }` liga o
  modo pra **todos** os requests que **não** mandarem `engine`; `GET /mode` (ou o campo
  `global_engine` no `/health`) mostra o vigente. O estado é gravado num `state.json` num
  volume (`STATE_DIR`, default `/data`) e **sobrevive a restart/recreate** do container.
- **Default de fábrica:** `auto` (quando não há estado gravado).

```jsonc
POST /mode { "engine": "offline" }   // liga o modo offline pro serviço todo
GET  /mode                            // { "engine": "offline", "precedence": "request > global > factory(auto)" }
```

Assim o **orquestrador não precisa manter estado**: chama `/mode` uma vez ao ligar/desligar,
em vez de repetir `engine=offline` em toda chamada. `engine` inválido → **HTTP 400**
`{ok:false, reason:"invalid_engine", allowed:["auto","offline"]}`.

Isto é ortogonal ao gate de tamanho (`SAY_MAX_CHARS`) e ao gate de ativação: `engine`
só escolhe **qual** engine sintetiza, não **se** sintetiza.

## Segurança
- `TELEGRAM_BOT_TOKEN` só no `.env` (gitignored) / secrets. Nunca versionado.
