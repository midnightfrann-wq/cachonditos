import os
import asyncio
import tempfile
import shutil
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

TOKEN = os.environ["TELEGRAM_TOKEN"]

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
    await update.message.reply_text("🎵 Envíame el nombre de una canción o artista.")


async def search_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text.strip()
    if not query:
        return

    loop = asyncio.get_event_loop()

    try:
        entries = await loop.run_in_executor(None, _search_youtube, query)
    except Exception:
        return

    if not entries:
        return

    tmpdir = tempfile.mkdtemp()
    try:
        tasks = [
            loop.run_in_executor(None, _download_mp3,
                                 f"https://www.youtube.com/watch?v={e.get('id', '')}",
                                 os.path.join(tmpdir, f"track_{i}.%(ext)s"),
                                 os.path.join(tmpdir, f"track_{i}.mp3"))
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


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_and_send))
    print("Bot iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
