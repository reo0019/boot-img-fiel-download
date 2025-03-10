import os
import time
import tarfile
import zipfile
import asyncio
import requests
import shutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

TOKEN = '7469030708:AAHu8ZEaYbGnAeTEoley1FB8XSg7NEPakWw'

WORKING_DIR = "temp_files"
if not os.path.exists(WORKING_DIR):
    os.makedirs(WORKING_DIR)

download_state = {}
user_download_state = {}  # Store users who activated the download command


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = (
        "------------------------\n"
        f"🤖 Welcome, {user.first_name}!\n"
        "------------------------\n"
        "📌 This bot helps you download and extract boot.img from Fastboot ROMs.\n"
        "\n"
        "✅ Send a TGZ file URL to get started.\n"
        "✅ Use /help to see all available commands.\n"
        "\n"
        "🚀 Let's begin!"
    )

    await update.message.reply_text(f"{message}", parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "------------------------\n"
        " 🤖 <b>Bot Commands</b>\n"
        "------------------------\n"
        "✅ <b>/start</b> - Start the bot\n"
        "✅ <b>/download</b> - Start downloading a ROM\n"
        "✅ <b>/showfiles</b> - Show all stored files\n"
        "✅ <b>/deletefiles</b> - Delete all stored files\n"
        "✅ <b>/help</b> - Show this help menu\n"
        "\n"
        "📤 <b>How to use:</b>\n"
        "\n"
        " ❗ Note ❗: Only TGZ files supported \n"
        "\n"
        "1️⃣ Send the command <code>/download</code>\n"
        "2️⃣ Send a <b>Fastboot ROM URL</b> (.tgz format)\n"
        "3️⃣ Click '<b>Download</b>' to process it\n"
        "4️⃣ Get the extracted <code>boot.img</code> file!\n"
    )

    await update.message.reply_text(message, parse_mode="HTML")


async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_download_state[chat_id] = True  # Mark the user as waiting for a URL
    await update.message.reply_text(
        "📥 Please send me the Fastboot ROM (TGZ file) URL to start downloading."
    )


async def handle_download_process(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"🔄 Processing URL: {url}\nDownloading...")

    # Add your existing download function logic here

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    # If the user didn't send /download first, ignore their URL
    if chat_id not in user_download_state or not user_download_state[chat_id]:
        return  # Ignore the message

    url = update.message.text.strip()

    # Validate URL
    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_text("❌ Invalid URL. Please send a valid link starting with http:// or https://.")
        return

    # Reset state after receiving a valid URL
    user_download_state[chat_id] = False  

    # Process the URL
    # Add your download logic here
    try:
        response = requests.head(url, allow_redirects=True)
        response.raise_for_status()

        # Get file size from headers
        file_size = int(response.headers.get('content-length', 0))

        # Extract file name from URL or content-disposition header
        if 'content-disposition' in response.headers:
            file_name = response.headers['content-disposition'].split('filename=')[-1].strip('"')
        else:
            file_name = os.path.basename(url) or "unknown_file"

        # Convert file size dynamically
        if file_size >= 1024 * 1024 * 1024:  # 1 GB or more
            file_size_display = f"{file_size / (1024 * 1024 * 1024):.2f} GB"
        elif file_size >= 1024 * 1024:  # 1 MB or more
            file_size_display = f"{file_size / (1024 * 1024):.2f} MB"
        elif file_size >= 1024:  # 1 KB or more
            file_size_display = f"{file_size / 1024:.2f} KB"
        else:
            file_size_display = f"{file_size} Bytes" if file_size > 0 else "Unknown Size"

        # Store the details
        download_state[chat_id] = {
            'url': url,
            'file_name': file_name,
            'file_size': file_size_display
        }

        keyboard = [
            [InlineKeyboardButton("Download", callback_data='download')],
            [InlineKeyboardButton("Cancel", callback_data='cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)


        await update.message.reply_text(
            f"📤 File Info:\nName: {file_name}\nSize: {file_size_display}",
            reply_markup=reply_markup
        )
    except requests.RequestException as e:
        await update.message.reply_text(f"Failed to get file info: {str(e)}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    data = query.data

    if chat_id not in download_state:
        await query.edit_message_text("No active download found. Please send a new URL.")
        return

    if data == 'download':
        message = await query.edit_message_text("Downloading... Please wait.")
        download_state[chat_id]['cancel'] = False  # Reset cancel flag
        await download_and_process(chat_id, context, message)

    elif data == 'cancel':
        download_state[chat_id]['cancel'] = True  # Mark as canceled
        await query.edit_message_text("🚫 Download canceled.")

async def download_and_process(chat_id: int, context: ContextTypes.DEFAULT_TYPE, message) -> None:
    state = download_state[chat_id]
    url = state['url']
    rom_filename = os.path.join(WORKING_DIR, state['file_name'])

    try:
        start_time = time.time()
        response = requests.get(url, stream=True)
        total_size = int(response.headers.get('content-length', 0))
        downloaded_size = 0
        chunk_size = 1024 * 1024  # 1 MB
        last_percentage = 0

        with open(rom_filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if download_state.get(chat_id, {}).get('cancel', False):  
                    await message.edit_text("🚫 Download canceled.")
                    os.remove(rom_filename)  # Delete incomplete file
                    return  

                f.write(chunk)
                downloaded_size += len(chunk)

                percentage = (downloaded_size / total_size) * 100 if total_size else 0
                speed = downloaded_size / (time.time() - start_time)
                time_remaining = (total_size - downloaded_size) / speed if speed > 0 else 0

                time_remaining_display = f"{time_remaining:.0f} sec" if time_remaining < 60 else f"{time_remaining / 60:.1f} min"

                progress_bar = "[" + "▪" * int(percentage // 10) + "▫" * (10 - int(percentage // 10)) + "]"
                file_size_display = f"{total_size / (1024 * 1024):.2f} MB" if total_size < (1024 * 1024 * 1024) else f"{total_size / (1024 * 1024 * 1024):.2f} GB"
                
           
                if int(percentage) > last_percentage:
                    last_percentage = int(percentage)
                    await message.edit_text(
                        f"Downloading: {percentage:.2f}%\n{progress_bar}\n"
                        f"{downloaded_size / (1024 * 1024):.2f} MB of {file_size_display}\n"
                        f"Speed: {speed / (1024 * 1024):.2f} MB/sec\n"
                        f"Time left: {time_remaining_display}",
                       
                    )
        time_taken = time.time() - start_time
        minutes = int(time_taken // 60)  # Get full minutes
        seconds = int(time_taken % 60)   # Get remaining seconds

        await message.edit_text(f"Download completed in {minutes} min {seconds} sec!")
        boot_img_path = await extract_boot_img(rom_filename, chat_id, context)
        if boot_img_path:
            await send_boot_img(boot_img_path, chat_id, context)
            await context.bot.send_message(chat_id, f"✅ Process completed ")


    except requests.RequestException as e:
        await message.edit_text(f"❌ Failed to download the file: {str(e)}")

    finally:
        download_state.pop(chat_id, None)  # Clean up after completion or cancellation

async def extract_boot_img(rom_path: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    try:
        with tarfile.open(rom_path, 'r:gz') as tar_ref:
            boot_img_found = False
            for file in tar_ref.getnames():
                if file.endswith("boot.img"):
                    tar_ref.extract(file, WORKING_DIR)  # Extract directly to WORKING_DIR
                    boot_img_path = os.path.join(WORKING_DIR, os.path.basename(file))
                    boot_img_found = True
                    await context.bot.send_message(chat_id, "✅ Extracted boot.img successfully.")
                    return boot_img_path
            if not boot_img_found:
                await context.bot.send_message(chat_id, "❌ No boot.img found in the ROM.")
                return None
    except tarfile.TarError:
        await context.bot.send_message(chat_id, "❌ The downloaded file is not a valid TGZ.")
        return None

async def send_boot_img(boot_img_path: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    zip_path = boot_img_path + ".zip"
    
    # Convert boot.img into a ZIP file
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(boot_img_path, "boot.img")

    file_size_mb = os.path.getsize(zip_path) / (1024 * 1024)

    if file_size_mb < 50:
        with open(zip_path, 'rb') as f:
            await context.bot.send_document(chat_id=chat_id, document=f, filename="boot.zip")
            os.remove(boot_img_path)  # After extraction
            os.remove(zip_path)      # After sending/uploading
    else:
        temp_url = await upload_to_temp(zip_path)
        await context.bot.send_message(chat_id, f"Download boot.zip here: {temp_url}")




async def upload_to_temp(file_path: str) -> str:
    for attempt in range(3):  # Retry 3 times
        try:
            with open(file_path, 'rb') as file:
                files = {'file': file}
                response = await asyncio.to_thread(requests.post, "https://tmpfiles.org/api/v1/upload", files=files)
                response.raise_for_status()
                return response.json().get("data", {}).get("url", "Failed to generate link")
        except requests.RequestException as e:
            if attempt == 2:  # Last attempt
                return f"Upload failed after retries: {str(e)}"
            await asyncio.sleep(2)  # Wait before retrying
    return "Failed to generate link"


async def show_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    files = os.listdir(WORKING_DIR)

    if files:
        file_list = "\n".join([f"{i + 1}) {file}" for i, file in enumerate(files)])
        message = (
            "------------------------\n"
            "\t📂<b> Total Files </b>\n"
            "------------------------\n"
            f"<i>{file_list}</i>"
        )
    else:
        message = (
            "------------------------\n"
            "\t📂<b> Total Files </b>\n"
            "------------------------\n"
            "No files found."
        )

    await update.message.reply_text(f"<pre>{message}</pre>", parse_mode="HTML")

async def delete_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if os.path.exists(WORKING_DIR):
        shutil.rmtree(WORKING_DIR)  # Delete the folder and all contents
        os.makedirs(WORKING_DIR)  # Recreate the empty folder
        await update.message.reply_text(f"🗑️ All files in {WORKING_DIR} have been deleted.")
    else:
        await update.message.reply_text("❌ Directory not found.")


def main() -> None:
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("download", download_file))
    application.add_handler(CommandHandler("showfiles", show_files))
    application.add_handler(CommandHandler("deletefiles", delete_files))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Handle URL **only if the user previously used /download**
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    application.run_polling()

if __name__ == '__main__':
    main()
