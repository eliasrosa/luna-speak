---
inclusion: auto
name: deploy
description: Use quando o usuário perguntar sobre deploy, CI/CD, ZimaOS ou pipeline de entrega do LunaSpeak.
---

# Deploy — ZimaOS

Mesmo padrão do `wallet-app` / `roms-manager-server`: **imagem local (sem registry)**, deploy no host do homelab. O ideal é o CD por GitHub Actions + runner self-hosted; enquanto não há runner dedicado, usa-se a **rotina manual** `scripts/deploy-manual.sh`.

## Deploy manual (via SSH)

```bash
cp .env.deploy.example .env.deploy   # 1x: preencher TELEGRAM_BOT_TOKEN
./scripts/deploy-manual.sh           # roda do SEU host
```

O script faz:
1. lê os secrets de `.env.deploy` (gitignored)
2. cria `APP_DIR` e `BUILD_DIR` no ZimaOS
3. `rsync` (ou tar-over-ssh) do build context para `${BUILD_DIR}`
4. copia `docker-compose-zimaos.yml` para `${APP_DIR}/docker-compose.yml` e gera o `.env` de prod (umask 077, via stdin)
5. `docker build -t luna-speak:latest .` no próprio ZimaOS
6. `docker compose up -d --force-recreate`

Config por env: `ZIMA_USER`, `ZIMA_HOST`, `APP_DIR`, `BUILD_DIR`, `IMAGE`.

## Arquivos

| Arquivo | Papel |
|---------|-------|
| `Dockerfile` | Imagem (python-slim + ffmpeg + Piper + deps) |
| `docker-compose-zimaos.yml` | Compose de produção (imagem local, `pull_policy: never`, `x-casaos`) |
| `scripts/deploy-manual.sh` | Rotina de deploy manual via SSH |
| `.env.deploy.example` | Modelo dos secrets locais (o `.env.deploy` real é gitignored) |
| `.github/workflows/deploy-zimaos.yaml` | CD por runner (espelha o manual) |
| `docker-compose.yml` | Ambiente de **dev** (porta 8033) — não usado em prod |

## Infraestrutura ZimaOS

| Item | Valor |
|------|-------|
| IP | `<ZIMAOS_IP>` |
| Usuário SSH | `<ZIMAOS_USER>` |
| App dir (CasaOS) | `<APP_DIR>` — convenção CasaOS `…/casaos/apps/luna-speak`; subir por aí é o que dá o **card** no painel |
| Build dir | `<BUILD_DIR>` — pasta de build no storage do host |
| Porta | `<HOST_PORT>` (host) → `8080` (container) |

## Secrets

| Secret | Uso |
|--------|-----|
| `TELEGRAM_BOT_TOKEN` | Bot do Telegram (`sendVoice`). Rotacionar no @BotFather. |

## Regras

- Imagem local (`pull_policy: never`) — não publica em registry.
- O compose de produção é o `docker-compose-zimaos.yml` (não o `docker-compose.yml` de dev).
- `APP_DIR` deve ficar sob o dir de apps do CasaOS (convenção `…/casaos/apps/<app>`) — subir por aí (não pelo AppData) é o que registra o **card** no CasaOS.
- Nunca `sudo` no workflow; operações privilegiadas via SSH.
- Dados de infra pessoal (IP/usuário/paths/porta) só via placeholders — o repo é **público**.
