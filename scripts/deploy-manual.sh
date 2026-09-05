#!/usr/bin/env bash
# Deploy manual do LunaSpeak no ZimaOS via SSH — mesmo padrão do wallet-app.
#
# Por que existe: espelha o que o workflow .github/workflows/deploy-zimaos.yaml faria,
# rodando do SEU host (fallback enquanto não há runner self-hosted dedicado).
#
# Uso:
#   1. cp .env.deploy.example .env.deploy   # e preencha TELEGRAM_BOT_TOKEN
#   2. ./scripts/deploy-manual.sh
#
# Pré-requisitos no host: ssh + rsync (cai para tar-over-ssh se faltar rsync).
# No ZimaOS: docker + docker compose. Idempotente (--force-recreate).

set -euo pipefail

# ---- Configuração (OBRIGATÓRIO exportar ZIMA_HOST e ZIMA_USER; repo público) -----
# Ex.: ZIMA_HOST=192.168.x.y ZIMA_USER=youruser ./scripts/deploy-manual.sh
ZIMA_USER="${ZIMA_USER:?defina ZIMA_USER (usuário SSH do host ZimaOS)}"
ZIMA_HOST="${ZIMA_HOST:?defina ZIMA_HOST (IP/host do ZimaOS)}"
APP_DIR="${APP_DIR:-/var/lib/casaos/apps/luna-speak}"
BUILD_DIR="${BUILD_DIR:-/media/ZimaOS-HD/AppData/luna-speak/build}"
IMAGE="${IMAGE:-luna-speak:latest}"
SSH_OPTS="-F /dev/null -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DEPLOY="${REPO_ROOT}/.env.deploy"
SSH="ssh ${SSH_OPTS} ${ZIMA_USER}@${ZIMA_HOST}"

# ---- 1. Valida os secrets locais -------------------------------------------------
if [[ ! -f "${ENV_DEPLOY}" ]]; then
  echo "ERRO: ${ENV_DEPLOY} não existe. Copie .env.deploy.example e preencha." >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a; source "${ENV_DEPLOY}"; set +a
: "${TELEGRAM_BOT_TOKEN:?defina TELEGRAM_BOT_TOKEN em .env.deploy}"
EDGE_VOICE="${EDGE_VOICE:-pt-BR-FranciscaNeural}"
EDGE_TIMEOUT="${EDGE_TIMEOUT:-8}"
OPUS_BITRATE="${OPUS_BITRATE:-32k}"

echo "==> Deploy do LunaSpeak em ${ZIMA_USER}@${ZIMA_HOST}"

# ---- 2. Prepara dirs no ZimaOS ---------------------------------------------------
echo "==> Preparando diretórios no ZimaOS"
${SSH} "mkdir -p '${APP_DIR}' '${BUILD_DIR}'"

# ---- 3. Envia o build context (repo) para o ZimaOS -------------------------------
echo "==> Enviando build context"
EXCLUDES=(.git .env '.env.*' '*.ogg' '*.wav' '*.mp3' __pycache__ 'voices/*.onnx')
if command -v rsync >/dev/null 2>&1; then
  RSYNC_EXCL=(); for e in "${EXCLUDES[@]}"; do RSYNC_EXCL+=(--exclude "$e"); done
  rsync -az --delete "${RSYNC_EXCL[@]}" -e "ssh ${SSH_OPTS}" \
    "${REPO_ROOT}/" "${ZIMA_USER}@${ZIMA_HOST}:${BUILD_DIR}/"
else
  TAR_EXCL=(); for e in "${EXCLUDES[@]}"; do TAR_EXCL+=(--exclude="./$e"); done
  ${SSH} "rm -rf '${BUILD_DIR}'/* '${BUILD_DIR}'/.[!.]* 2>/dev/null; mkdir -p '${BUILD_DIR}'"
  tar -C "${REPO_ROOT}" "${TAR_EXCL[@]}" -czf - . \
    | ${SSH} "tar -C '${BUILD_DIR}' -xzf -"
fi

# ---- 4. Copia o compose para o APP_DIR e gera o .env de prod (umask 077) ----------
echo "==> Instalando compose e gerando .env de produção"
${SSH} "cp '${BUILD_DIR}/docker-compose-zimaos.yml' '${APP_DIR}/docker-compose.yml'"
# .env remoto via stdin, para não expor o token em ps/args.
${SSH} "umask 077; cat > '${APP_DIR}/.env'" <<EOF
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
EDGE_VOICE=${EDGE_VOICE}
EDGE_TIMEOUT=${EDGE_TIMEOUT}
OPUS_BITRATE=${OPUS_BITRATE}
FORCE_PIPER=
EOF

# ---- 5. Build da imagem no ZimaOS ------------------------------------------------
echo "==> Build da imagem ${IMAGE} no ZimaOS"
${SSH} "cd '${BUILD_DIR}' && docker build -t '${IMAGE}' ."

# ---- 6. Sobe a stack -------------------------------------------------------------
echo "==> docker compose up -d"
${SSH} "cd '${APP_DIR}' && docker compose up -d --force-recreate --remove-orphans"

# ---- 7. Status -------------------------------------------------------------------
echo "==> Estado do serviço"
${SSH} "cd '${APP_DIR}' && docker compose ps"
echo "==> Deploy concluído. Health: http://${ZIMA_HOST}:8093/health"
