---
inclusion: auto
name: conventions
description: Use ao contribuir com o LunaSpeak — padrão de config por env, higiene de repositório público, e estilo de issue/commit.
---

# Convenções — LunaSpeak

## Config por env (sem rebuild)

Toda opção de runtime é uma **variável de ambiente** com default sensato, lida uma
vez no topo de `app/main.py` (ou `app/gate/policy.py` para política). Trocar
comportamento é editar o `.env` e reiniciar o container — **nunca** rebuildar a
imagem. Regras:

- Todo env novo entra no `.env.example` com um comentário curto do que faz + default.
- Quando fizer sentido, exponha o valor efetivo no `GET /health` (ex. `edge_voice`,
  `say_max_chars`, `engines`) — facilita confirmar o que está no ar.
- Default = comportamento seguro/atual. Uma flag nova nunca muda o comportamento de
  quem não a setou.

Envs atuais: `TELEGRAM_BOT_TOKEN`, `EDGE_VOICE`, `EDGE_TIMEOUT`, `PIPER_BIN`,
`PIPER_MODEL`, `OPUS_BITRATE`, `SAY_MAX_CHARS`, `FORCE_PIPER`, `VOICE_OVERFLOW_MODE`,
`LOG_LEVEL`. Tabela com defaults no `README.md`.

## Higiene de repositório PÚBLICO

Este repo é **público**. Nunca versione dado local/pessoal/de infra:

- **Zero** IP de host, path de host (ex. de `/var/...` ou storage local), `chat_id`,
  token, nome de máquina ou de rede doméstica — em código, README, steering, issues
  ou mensagens de commit.
- Use **placeholders genéricos**: `<HOST>`, `<APP_DIR>`, `<CHAT_ID>`, porta genérica.
- Segredos (ex. `TELEGRAM_BOT_TOKEN`) vivem só em `.env`/`.env.deploy` (gitignored) ou
  no secret store — nunca no repo.
- Utilitários que leem `.env` (ex. `integrations/kiro-mcp/whichbot.py`) leem o valor
  **no corpo do script**, nunca o ecoam, e nunca recebem o segredo na linha de comando.

## Estilo de código

- Python 3.12, FastAPI. I/O em `app/main.py`; lógica pura (sem I/O) em `app/gate/`.
- Logs **estruturados** por request (engine, duração, motivo), **sem** vazar o texto do
  usuário nem o `chat_id`.
- Toda feature de comportamento observável vem com **teste de regressão** que **falha
  antes e passa depois** (`tests/`, pytest + `TestClient`, engines/rede mockadas).

## Estilo de issue

Templates em `.github/ISSUE_TEMPLATE/`. Feature/Task segue **Contexto/Problema →
Proposta → Critérios de aceite (checklist verificável) → Notas técnicas**; Bug segue
**O que aconteceu → Esperado → Como reproduzir → Ambiente/logs**. Issues objetivas,
com critério de aceite verificável, para o fluxo de triagem/execução funcionar bem.

## Commits & PRs

- Mensagem no imperativo, escopo no título (`feat:`, `docs:`, `fix:` …), com o número
  da issue. Corpo explica o **porquê** e o que ficou fora de escopo.
- `Fixes #<n>` no corpo do PR (fecha a issue no merge). PR diz o que mudou, como foi
  verificado e quais vermelhos (se houver) vieram da base.
