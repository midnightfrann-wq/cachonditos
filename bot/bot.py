import os
import asyncio
import tempfile
import shutil
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

TOKEN = os.environ["TELEGRAM_TOKEN"]

YOUTUBE_RE = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)[\w\-]+"
)

SEARCH_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "extractor_args": {"youtubetab": {"skip": ["authcheck"]}},
}

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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎵 Envíame el nombre de una canción, artista o un link de YouTube."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if not text:
        return

    loop = asyncio.get_event_loop()
    tmpdir = tempfile.mkdtemp()

    try:
        if YOUTUBE_RE.search(text):
            # Direct YouTube URL — download single track
            url = YOUTUBE_RE.search(text).group(0)
            if not url.startswith("http"):
                url = "https://" + url

            info, mp3_path = await loop.run_in_executor(
                None, _download_single, url, tmpdir
            )
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
                    os.remove(mp3_path)
        else:
            # Text search — top 5 results downloaded in parallel
            entries = await loop.run_in_executor(None, _search_youtube, text)
            if not entries:
                return

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
                            performer=entry.get("uploader", ""),
                            read_timeout=120,
                            write_timeout=120,
                        )
                finally:
                    if os.path.exists(mp3_path):
                        os.remove(mp3_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
