#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
if [ ! -f config.env ]; then
  echo "config.env nahi mili. Pehle ye file banao (README dekho)."
  exit 1
fi
set -a
. ./config.env
set +a
termux-wake-lock 2>/dev/null
exec python bot.py
