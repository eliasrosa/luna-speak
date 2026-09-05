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
  -d '{"text":"Oi Elias!","chat_id":"<seu_chat_id>"}'
```

> ⚠️ O `docker-compose.yml` usa `env_file: .env`. Se você pular o `cp .env.example .env`,
> o `docker compose up` falha com `env file .env not found`. Copie o `.env` **antes** de subir.

**Validar o fallback Piper sem cortar a rede:** ligue `FORCE_PIPER=1` no `.env` (ou
`FORCE_PIPER=1 docker compose up`). Com a flag, o `/say` pula o Edge-TTS e vai direto pro
Piper — a resposta volta com `"engine":"piper"`. Deixe vazio em produção.

### ZimaOS (produção)
Deploy via `docker-compose-zimaos.yml` (imagem local, sem registry). Colocar o `.env` ao lado do compose no diretório do app e `docker compose up -d`.

## Endpoints
- `POST /say { text, chat_id }` — sintetiza e envia voice message. Retorna `{ok, engine, duration}`.
- `GET /health` — status + engines disponíveis (inclui `piper_available`, `token_configured`, `force_piper`).

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

## Segurança
- `TELEGRAM_BOT_TOKEN` só no `.env` (gitignored) / secrets. Nunca versionado.
