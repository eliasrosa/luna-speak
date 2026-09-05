#!/usr/bin/env python3
"""getMe seguro: descobre id + @username de um bot a partir do TELEGRAM_BOT_TOKEN
de um arquivo .env, SEM imprimir o token. Uso:

    python3 whichbot.py /caminho/do/.env

Lê a linha TELEGRAM_BOT_TOKEN=... do .env, chama a API getMe do Telegram e
imprime apenas: bot_id, username, first_name. O token nunca é exibido nem logado.
"""
import re
import sys
import urllib.request
import json

if len(sys.argv) < 2:
    print("uso: python3 whichbot.py /caminho/do/.env")
    sys.exit(2)

env_path = sys.argv[1]
token = None
with open(env_path, "r", encoding="utf-8") as f:
    for line in f:
        m = re.match(r"\s*TELEGRAM_BOT_TOKEN\s*=\s*(.+?)\s*$", line)
        if m:
            token = m.group(1).strip().strip('"').strip("'")
            break

if not token:
    print(f"TELEGRAM_BOT_TOKEN não encontrado em {env_path}")
    sys.exit(1)

# id do bot = parte antes dos ':' (já é público); não imprime o token inteiro
bot_id = token.split(":", 1)[0]
try:
    with urllib.request.urlopen(
        f"https://api.telegram.org/bot{token}/getMe", timeout=10
    ) as r:
        data = json.load(r)
    res = data.get("result", {})
    print(f"bot_id={res.get('id', bot_id)}  username=@{res.get('username')}  name={res.get('first_name')}")
except Exception as e:
    # mesmo offline, o id (parte pública) já ajuda a comparar
    print(f"bot_id={bot_id}  (getMe falhou: {type(e).__name__}: {e})")
