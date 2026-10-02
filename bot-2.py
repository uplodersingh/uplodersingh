import os
import re
import sys
import glob
import json
import asyncio
import subprocess
import urllib.request

from pyrogram import Client, filters, idle
from yt_dlp import YoutubeDL


def need(name):
    v = os.environ.get(name, "").strip()
    if not v or v.startswith("YOUR_"):
        print(f"ERROR: {name} set nahi hai. config.env mein asli value daalo.")
        sys.exit(1)
    return v


try:
    API_ID = int(need("API_ID"))
except ValueError:
    print("ERROR: API_ID sirf number hona chahiye.")
    sys.exit(1)
API_HASH = need("API_HASH")
BOT_TOKEN = need("BOT_TOKEN")

MAX_SIZE = 2000 * 1024 * 1024          # Telegram limit ~2GB
DOC_EXT = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
           ".zip", ".rar", ".epub")
VIDEO_SEND_EXT = (".mp4", ".mov", ".m4v")

app = Client("uploader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

stop_flags = {}     # chat_id -> True agar /stop dabaya
running = {}        # chat_id -> job chal raha hai
procs = {}          # chat_id -> ffmpeg process
quality = {}        # chat_id -> max height (default 720)


# ---------- helpers ----------
def clean_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n]+', " ", s or "").strip()
    return s[:100] or "file"


def parse_text(text):
    """Har line: 'Title:URL' ya sirf 'URL' -> [(title|None, url)]"""
    items = []
    for line in text.splitlines():
        m = re.search(r'https?://[^\s"\'<>]+', line)
        if not m:
            continue
        title = line[: m.start()].strip().rstrip(":").strip()
        items.append((title or None, m.group(0)))
    return items


def url_ext(url):
    return os.path.splitext(url.lower().split("?")[0].split("#")[0])[1]


def is_doc(url):
    return url_ext(url) in DOC_EXT or ".pdf" in url.lower()


def cleanup(base):
    for f in glob.glob(base + ".*"):
        try:
            os.remove(f)
        except OSError:
            pass


def probe(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=60,
        ).stdout
        d = json.loads(out)
        st = d["streams"][0]
        return int(float(d["format"]["duration"])), st["width"], st["height"]
    except Exception:
        return 0, 0, 0


def make_thumb(path, out):
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", path,
             "-vframes", "1", "-vf", "scale=320:-1", out],
            timeout=60,
        )
        return out if os.path.exists(out) else None
    except Exception:
        return None


# ---------- downloaders ----------
def download_doc(url, out, chat_id):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(out, "wb") as f:
        while True:
            if stop_flags.get(chat_id):
                raise Exception("stopped")
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    if out.endswith(".pdf"):
        with open(out, "rb") as f:
            if f.read(5) != b"%PDF-":
                raise RuntimeError(
                    "ye PDF nahi hai (link login/token wala ya expire ho gaya)"
                )


def expand(url):
    """Playlist ho toh uski sab videos, warna [(title, url)]"""
    opts = {
        "quiet": True, "no_warnings": True,
        "extract_flat": "in_playlist", "skip_download": True,
        "js_runtimes": {"node": {}},
    }
    try:
        with YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
    except Exception:
        return [(None, url)]
    if info and info.get("entries"):
        out = []
        for e in info["entries"]:
            if not e:
                continue
            u = e.get("url") or e.get("webpage_url")
            if u:
                out.append((e.get("title"), u))
        return out or [(None, url)]
    return [((info or {}).get("title"), url)]


def dl_ytdlp(url, base, chat_id):
    q = quality.get(chat_id, 720)

    def hook(d):
        if stop_flags.get(chat_id):
            raise Exception("stopped")

    opts = {
        "outtmpl": base + ".%(ext)s",
        "format": f"bv*[height<={q}]+ba/b[height<={q}]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True, "no_warnings": True,
        "retries": 5, "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "js_runtimes": {"node": {}},
        "progress_hooks": [hook],
    }
    with YoutubeDL(opts) as y:
        y.download([url])
    files = [f for f in glob.glob(base + ".*")
             if not f.endswith((".part", ".ytdl"))]
    if not files:
        raise RuntimeError("file nahi bani")
    return max(files, key=os.path.getsize)


def dl_ffmpeg(url, base, chat_id):
    out = base + ".mp4"
    p = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-user_agent", "Mozilla/5.0", "-i", url, "-c", "copy", out,
    ])
    procs[chat_id] = p
    rc = p.wait()
    procs.pop(chat_id, None)
    if rc != 0:
        raise RuntimeError(f"ffmpeg exit code {rc}")
    return out


def dl_direct(url, base, chat_id):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        ctype = r.headers.get("Content-Type", "")
        if not (ctype.startswith("video/") or "octet-stream" in ctype):
            raise RuntimeError(f"video nahi hai ({ctype or 'unknown'})")
        ext = url_ext(url)
        if ext not in (".mp4", ".mkv", ".webm", ".mov", ".avi", ".ts"):
            ext = ".mp4"
        out = base + ext
        with open(out, "wb") as f:
            while True:
                if stop_flags.get(chat_id):
                    raise Exception("stopped")
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    return out


# ---------- main job ----------
async def send_video(message, path, name, caption):
    ext = os.path.splitext(path)[1].lower()
    fname = clean_name(name) + ext
    if ext in VIDEO_SEND_EXT:
        dur, w, h = await asyncio.to_thread(probe, path)
        thumb = await asyncio.to_thread(make_thumb, path, path + ".thumb.jpg")
        await message.reply_video(
            path, file_name=fname, caption=caption, supports_streaming=True,
            duration=dur, width=w, height=h, thumb=thumb,
        )
    else:
        await message.reply_document(path, file_name=fname, caption=caption)


async def run_job(message, items):
    chat_id = message.chat.id
    if running.get(chat_id):
        return await message.reply("Pehle wala kaam chal raha hai. Rokne ke liye /stop")
    running[chat_id] = True
    stop_flags[chat_id] = False
    n = done = 0
    try:
        await message.reply(f"{len(items)} links mile. Rokne ke liye /stop")
        for title, url in items:
            if stop_flags.get(chat_id):
                break
            doc = is_doc(url)
            if doc:
                entries = [(title, url)]
            else:
                entries = await asyncio.to_thread(expand, url)
                if len(entries) == 1 and title:
                    entries = [(title, entries[0][1])]
                elif len(entries) > 1:
                    await message.reply(f"Playlist: {len(entries)} videos mili")

            for etitle, eurl in entries:
                if stop_flags.get(chat_id):
                    break
                n += 1
                name = etitle or "file"
                caption = f"Index: {n}\nTitle: {name}"
                base = f"dl_{message.id}_{n}"
                try:
                    if doc:
                        ext = url_ext(eurl) if url_ext(eurl) in DOC_EXT else ".pdf"
                        path = base + ext
                        await asyncio.to_thread(download_doc, eurl, path, chat_id)
                        fname = clean_name(name)
                        if fname.lower().endswith(ext):
                            fname = fname[: -len(ext)]
                        await message.reply_document(
                            path, file_name=fname + ext, caption=caption
                        )
                    else:
                        await message.reply(f"Download: {n}. {name}")
                        path, errors = None, []
                        for fn in (dl_ytdlp, dl_ffmpeg, dl_direct):
                            if stop_flags.get(chat_id):
                                break
                            try:
                                path = await asyncio.to_thread(
                                    fn, eurl, base, chat_id
                                )
                                break
                            except Exception as e:
                                errors.append(f"{fn.__name__}: {str(e)[:120]}")
                                print(fn.__name__, eurl, e, flush=True)
                                cleanup(base)
                        if not path:
                            if stop_flags.get(chat_id):
                                raise Exception("stopped")
                            raise RuntimeError("\n".join(errors))
                        if os.path.getsize(path) > MAX_SIZE:
                            raise RuntimeError(
                                "file 2GB se badi hai. /quality 480 try karo"
                            )
                        await send_video(message, path, name, caption)
                    done += 1
                except Exception as e:
                    if stop_flags.get(chat_id):
                        break
                    print("FAIL", eurl, e, flush=True)
                    await message.reply(f"Fail ({n}) {name}\n{str(e)[:300]}")
                finally:
                    cleanup(base)
    finally:
        running[chat_id] = False

    if stop_flags.get(chat_id):
        await message.reply(f"Stopped. {done} file ho chuki.")
    else:
        await message.reply(f"Done. {done}/{n} files bheji.")


# ---------- handlers ----------
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply(
        "Upload txt file ya seedha link bhejo\n\n"
        "Txt format (har line mein):\nTitle:https://link\n\n"
        "YouTube, playlist, m3u8, mp4 aur PDF links chalte hain.\n"
        "/quality 480 - video quality (360/480/720/1080)\n"
        "/stop - rokne ke liye"
    )


@app.on_message(filters.command("stop"))
async def stop(client, message):
    chat_id = message.chat.id
    stop_flags[chat_id] = True
    p = procs.get(chat_id)
    if p:
        p.terminate()
    await message.reply("Stop kar raha hoon...")


@app.on_message(filters.command("quality"))
async def set_quality(client, message):
    parts = message.text.split()
    if len(parts) == 2 and parts[1] in ("144", "240", "360", "480", "720", "1080"):
        quality[message.chat.id] = int(parts[1])
        return await message.reply(f"Quality {parts[1]}p set ho gayi")
    await message.reply("Aise likho: /quality 480")


@app.on_message(filters.document)
async def on_file(client, message):
    name = message.document.file_name or ""
    if not name.lower().endswith(".txt"):
        return await message.reply("Sirf .txt file bhejo")
    path = await message.download()
    with open(path, encoding="utf-8", errors="ignore") as f:
        items = parse_text(f.read())
    os.remove(path)
    if not items:
        return await message.reply("File mein koi link nahi mila")
    await run_job(message, items)


@app.on_message(filters.text & ~filters.command(["start", "stop", "quality"]))
async def on_text(client, message):
    items = parse_text(message.text)
    if items:
        await run_job(message, items)


async def main():
    await app.start()
    me = await app.get_me()
    print(f"Bot chalu hai: @{me.username}", flush=True)
    await idle()
    await app.stop()


app.run(main())
