# Uploader Bot (Telegram)

Txt file ya seedha link bhejo. Public YouTube/playlist, m3u8, mp4 aur PDF/doc links nikal ke Telegram pe bhejta hai (2GB tak).

## Termux setup (ek baar)
    git clone https://github.com/USERNAME/REPO.git
    cd REPO
    bash setup.sh

## config.env banao (ye file GitHub pe upload mat karna)
    cat > config.env << 'EOT'
    API_ID=YOUR_API_ID
    API_HASH=YOUR_API_HASH
    BOT_TOKEN=YOUR_BOT_TOKEN
    EOT

## Chalao
    tmux new -s bot
    ./run.sh

Terminal mein "Bot chalu hai: @naam" dikhe toh Telegram pe /start bhejo.
Bahar aane ke liye Ctrl+B phir D.

## Update
    git pull
    pip install -U yt-dlp yt-dlp-ejs

Sirf public links chalte hain. Login, encrypted ya DRM wale links nahi chalte.
