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
}

def build_download_opts(output_path: str) -> dict:
    return {
        "format": "bestaudio/best",
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
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎵 *Bot de Música*\n\n"
        "Envíame el nombre de un artista o canción y te buscaré "
        "los primeros 5 resultados en YouTube, los convertiré a MP3 "
        "y te los enviaré directamente aquí.\n\n"
        "Ejemplo: _Bad Bunny_ o _Bohemian Rhapsody_",
        parse_mode="Markdown",
    )


async def search_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text.strip()
    if not query:
        return

    status_msg = await update.message.reply_text(f"🔍 Buscando: *{query}*...", parse_mode="Markdown")

    loop = asyncio.get_event_loop()

    try:
        entries = await loop.run_in_executor(None, _search_youtube, query)
    except Exception as e:
        await status_msg.edit_text(f"❌ Error al buscar: {e}")
        return

    if not entries:
        await status_msg.edit_text("❌ No se encontraron resultados.")
        return

    await status_msg.edit_text(
        f"✅ Encontré *{len(entries)}* resultado(s). Descargando...",
        parse_mode="Markdown",
    )

    tmpdir = tempfile.mkdtemp()
    try:
        for i, entry in enumerate(entries, 1):
            video_id = entry.get("id", "")
            title = entry.get("title") or f"Pista {i}"
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            duration = entry.get("duration")
            duration_str = f" ({int(duration // 60)}:{int(duration % 60):02d})" if duration else ""

            await update.message.reply_text(
                f"⬇️ *({i}/{len(entries)})* {title}{duration_str}",
                parse_mode="Markdown",
            )

            output_template = os.path.join(tmpdir, f"track_{i}.%(ext)s")
            mp3_path = os.path.join(tmpdir, f"track_{i}.mp3")

            try:
                await loop.run_in_executor(
                    None, _download_mp3, video_url, output_template
                )

                if not os.path.exists(mp3_path):
                    raise FileNotFoundError("Archivo MP3 no generado")

                with open(mp3_path, "rb") as audio_file:
                    await update.message.reply_audio(
                        audio=audio_file,
                        title=title,
                        performer="YouTube",
                        read_timeout=120,
                        write_timeout=120,
                    )

                os.remove(mp3_path)

            except Exception as e:
                await update.message.reply_text(f"❌ No se pudo descargar *{title}*: {e}", parse_mode="Markdown")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    await update.message.reply_text("✅ ¡Listo! Todos los MP3 han sido enviados.")


def _search_youtube(query: str) -> list:
    with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
        info = ydl.extract_info(f"ytsearch5:{query}", download=False)
        return info.get("entries", []) if info else []


def _download_mp3(url: str, output_template: str) -> None:
    opts = build_download_opts(output_template)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_and_send))
    print("Bot iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
