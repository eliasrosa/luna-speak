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
cp .env.example .env   # preencher TELEGRAM_BOT_TOKEN
docker compose up --build
# POST http://localhost:8080/say
curl -X POST localhost:8080/say -H 'Content-Type: application/json' \
  -d '{"text":"Oi Elias!","chat_id":"<seu_chat_id>"}'
```

### ZimaOS (produção)
Deploy via `docker-compose-zimaos.yml` (bind mounts em /DATA/AppData/lunaspeak, imagem local). Ver `.kiro/steering/deploy.md`.

## Endpoints
- `POST /say { text, chat_id }` — sintetiza e envia voice message. Retorna `{ok, engine, duration}`.
- `GET /health` — status + engines disponíveis.

## Segurança
- `TELEGRAM_BOT_TOKEN` só no `.env` (gitignored) / secrets. Nunca versionado.
