#!/data/data/com.termux/files/usr/bin/bash
pkg update -y && pkg upgrade -y
pkg install -y python git ffmpeg nodejs tmux clang
pip install -U pyrofork yt-dlp yt-dlp-ejs
pip install -U tgcrypto || echo "tgcrypto skip (bot chalega, bas upload thoda slow)"
echo ""
echo "Setup ho gaya. Ab config.env banao (README dekho), phir: ./run.sh"
