import os
import asyncio
import tempfile
import shutil
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
import yt_dlp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ["TELEGRAM_TOKEN"]
PORT = int(os.environ.get("PORT", 8080))

PLAYLIST_RE = re.compile(r"(https?://)?(www\.)?youtube\.com/playlist\?list=[\w\-]+")
YOUTUBE_RE = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)[\w\-]+"
)

SEARCH_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "extractor_args": {"youtubetab": {"skip": ["authcheck"]}},
}

MAX_PLAYLIST = 25


def build_download_opts(output_path: str) -> dict:
    return {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": output_path,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "concurrent_fragment_downloads": 4,
    }


# ── Bot handlers ──────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎵 Envíame el nombre de una canción, artista, link de YouTube o link de playlist."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if not text:
        return

    loop = asyncio.get_event_loop()
    tmpdir = tempfile.mkdtemp()

    try:
        if PLAYLIST_RE.search(text):
            url = PLAYLIST_RE.search(text).group(0)
            if not url.startswith("http"):
                url = "https://" + url
            entries = await loop.run_in_executor(None, _fetch_playlist, url)
            if not entries:
                return
            if len(entries) > MAX_PLAYLIST:
                await update.message.reply_text(
                    f"⚠️ Playlist con {len(entries)} canciones. Enviando las primeras {MAX_PLAYLIST}."
                )
                entries = entries[:MAX_PLAYLIST]
            await _send_parallel(update, loop, tmpdir, entries)

        elif YOUTUBE_RE.search(text):
            url = YOUTUBE_RE.search(text).group(0)
            if not url.startswith("http"):
                url = "https://" + url
            info, mp3_path = await loop.run_in_executor(None, _download_single, url, tmpdir)
            if mp3_path and os.path.exists(mp3_path):
                try:
                    with open(mp3_path, "rb") as f:
                        await update.message.reply_audio(
                            audio=f,
                            title=info.get("title", "Track"),
                            performer=info.get("uploader", ""),
                            read_timeout=120,
                            write_timeout=120,
                        )
                finally:
                    if os.path.exists(mp3_path):
                        os.remove(mp3_path)

        else:
            entries = await loop.run_in_executor(None, _search_youtube, text)
            if not entries:
                return
            await _send_parallel(update, loop, tmpdir, entries)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def _send_parallel(update, loop, tmpdir, entries):
    tasks = [
        loop.run_in_executor(
            None,
            _download_mp3,
            f"https://www.youtube.com/watch?v={e.get('id', '')}",
            os.path.join(tmpdir, f"track_{i}.%(ext)s"),
            os.path.join(tmpdir, f"track_{i}.mp3"),
        )
        for i, e in enumerate(entries, 1)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, (entry, result) in enumerate(zip(entries, results), 1):
        if isinstance(result, Exception):
            continue
        mp3_path = os.path.join(tmpdir, f"track_{i}.mp3")
        if not os.path.exists(mp3_path):
            continue
        try:
            with open(mp3_path, "rb") as f:
                await update.message.reply_audio(
                    audio=f,
                    title=entry.get("title", f"Track {i}"),
                    performer=entry.get("uploader", entry.get("channel", "")),
                    read_timeout=120,
                    write_timeout=120,
                )
        finally:
            if os.path.exists(mp3_path):
                os.remove(mp3_path)


def _fetch_playlist(url: str) -> list:
    opts = {**SEARCH_OPTS, "playlistend": MAX_PLAYLIST}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info.get("entries", []) if info else []


def _search_youtube(query: str) -> list:
    with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
        info = ydl.extract_info(f"ytsearch5:{query}", download=False)
        return info.get("entries", []) if info else []


def _download_mp3(url: str, output_template: str, mp3_path: str) -> None:
    opts = build_download_opts(output_template)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


def _download_single(url: str, tmpdir: str):
    output_template = os.path.join(tmpdir, "single.%(ext)s")
    mp3_path = os.path.join(tmpdir, "single.mp3")
    opts = build_download_opts(output_template)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return info, mp3_path


# ── FastAPI app ───────────────────────────────────────────────────────────────

ptb_app: Application = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ptb_app
    ptb_app = Application.builder().token(TOKEN).build()
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await ptb_app.initialize()
    await ptb_app.start()

    # Register webhook using REPLIT_DOMAINS
    domains = os.environ.get("REPLIT_DOMAINS", "")
    primary = domains.split(",")[0].strip() if domains else ""
    if primary:
        webhook_url = f"https://{primary}/webhook/{TOKEN}"
        await ptb_app.bot.set_webhook(url=webhook_url)
        print(f"Webhook registrado: {webhook_url}")
    else:
        print("REPLIT_DOMAINS no disponible — webhook no registrado")

    yield

    await ptb_app.bot.delete_webhook()
    await ptb_app.stop()
    await ptb_app.shutdown()


web = FastAPI(lifespan=lifespan)


@web.head("/")
async def head_index():
    return Response(status_code=200)


@web.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><title>Bot de Música</title></head>
    <body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f0f0f;color:#fff">
      <h1>🎵 Bot de Música</h1>
      <p style="color:#aaa">El bot está activo. Búscalo en Telegram y envíale una canción.</p>
      <p style="color:#4caf50;font-size:1.2em">✅ Online</p>
    </body>
    </html>
    """


@web.post(f"/webhook/{TOKEN}")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=200)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot.server:web", host="0.0.0.0", port=PORT)
