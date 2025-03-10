import os
import time
import zipfile
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# Replace 'YOUR_BOT_TOKEN' with the token from BotFather
TOKEN = 'YOUR_BOT_TOKEN'

# Directory to store temporary files
WORKING_DIR = "temp_files"
if not os.path.exists(WORKING_DIR):
    os.makedirs(WORKING_DIR)

# Global variable to store download state
download_state = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "Hi! Send me a URL to a Fastboot ROM (ZIP file), and I'll download it, extract the boot.img, and send it back to you. I'll also tell you how long it takes!"
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the URL sent by the user and prompt for download options."""
    url = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Check if the message is a valid URL
    if not url.startswith("http"):
        await update.message.reply_text("Please send a valid URL starting with http or https.")
        return

    try:
        response = requests.head(url, allow_redirects=True)
        response.raise_for_status()
        file_size = int(response.headers.get('content-length', 0))
        file_name = os.path.basename(url) if 'content-disposition' not in response.headers else response.headers['content-disposition'].split('filename=')[1].strip('"')
        file_size_mb = file_size / (1024 * 1024) if file_size else 0

        download_state[chat_id] = {'url': url, 'file_name': file_name, 'file_size': file_size, 'downloaded': 0}

        keyboard = [
            [InlineKeyboardButton("Download", callback_data='download'),
             InlineKeyboardButton("Rename & Download", callback_data='rename')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"📤 How would you like to upload this link?\n"
            f"Name: {file_name}\n"
            f"Size: {file_size_mb:.2f} MB",
            reply_markup=reply_markup
        )

    except requests.RequestException as e:
        await update.message.reply_text(f"Failed to get file info: {str(e)}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    data = query.data

    if chat_id not in download_state:
        await query.edit_message_text("No download session found. Please send a new URL.")
        return

    if data == 'download':
        download_state[chat_id]['confirm'] = True
        await query.edit_message_text("Confirm download? (Yes/No)")
    elif data == 'rename':
        download_state[chat_id]['rename'] = True
        await query.edit_message_text("Enter new file name:")

async def handle_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user responses after button clicks."""
    chat_id = update.effective_chat.id
    message_text = update.message.text.strip()

    if chat_id in download_state:
        if 'confirm' in download_state[chat_id]:
            if message_text.lower() == 'yes':
                await update.message.reply_text("Starting download...")
                await download_and_process(chat_id, context)
            elif message_text.lower() == 'no':
                await update.message.reply_text("Download cancelled.")
            del download_state[chat_id]['confirm']

        elif 'rename' in download_state[chat_id]:
            download_state[chat_id]['file_name'] = message_text + '.zip'
            await update.message.reply_text(f"Renamed to {message_text}.zip. Confirm download? (Yes/No)")
            download_state[chat_id]['confirm'] = True
            del download_state[chat_id]['rename']

async def download_and_process(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Download the file and process it with progress updates."""
    state = download_state[chat_id]
    url = state['url']
    rom_filename = os.path.join(WORKING_DIR, state['file_name'])

    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        total_size = state['file_size']
        chunk_size = 8192
        downloaded_size = 0

        with open(rom_filename, 'wb') as f:
            start_time = time.time()
            last_update_time = 0

            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    state['downloaded'] = downloaded_size

                    percentage = (downloaded_size / total_size) * 100 if total_size else 0
                    elapsed_time = time.time() - start_time
                    speed = downloaded_size / elapsed_time / (1024 * 1024) if elapsed_time else 0
                    eta = ((total_size - downloaded_size) / (speed * 1024 * 1024)) if speed else 0

                    if elapsed_time - last_update_time >= 2:  # Update every 2 seconds
                        last_update_time = elapsed_time
                        progress_msg = (
                            f"Downloading: {percentage:.2f}%\n"
                            f"Speed: {speed:.2f} MB/sec\n"
                            f"ETA: {eta:.0f}s"
                        )

                        if 'progress_msg_id' in state:
                            await context.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=state['progress_msg_id'],
                                text=progress_msg
                            )
                        else:
                            msg = await context.bot.send_message(chat_id=chat_id, text=progress_msg)
                            state['progress_msg_id'] = msg.message_id

            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=state['progress_msg_id'],
                text="Download completed!"
            )
            del state['progress_msg_id']

            boot_img_path = await extract_boot_img(rom_filename, chat_id, context)
            if boot_img_path:
                await send_boot_img(boot_img_path, chat_id, context)

            end_time = time.time()
            time_taken = end_time - start_time
            await context.bot.send_message(chat_id, f"Process completed in {time_taken:.2f} seconds!")

            cleanup_files(rom_filename, boot_img_path)

    except requests.RequestException as e:
        await context.bot.send_message(chat_id, f"Failed to download the file: {str(e)}")
    finally:
        download_state.pop(chat_id, None)

async def extract_boot_img(rom_path: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Extract the boot.img file from the Fastboot ROM."""
    try:
        with zipfile.ZipFile(rom_path, 'r') as zip_ref:
            for file in zip_ref.namelist():
                if file.endswith("boot.img"):
                    zip_ref.extract(file, WORKING_DIR)
                    boot_img_path = os.path.join(WORKING_DIR, file)
                    await context.bot.send_message(chat_id, "Extracted boot.img successfully.")
                    return boot_img_path
            await context.bot.send_message(chat_id, "No boot.img found in the ROM.")
            return None
    except zipfile.BadZipFile:
        await context.bot.send_message(chat_id, "The downloaded file is not a valid ZIP.")
        return None

async def send_boot_img(boot_img_path: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the extracted boot.img file to the user."""
    with open(boot_img_path, 'rb') as f:
        await context.bot.send_document(chat_id=chat_id, document=f, filename="boot.img")

def main() -> None:
    """Run the bot."""
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling()

if __name__ == '__main__':
    main()
