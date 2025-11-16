from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
import yt_dlp
import os
import tempfile
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# ======================
# CONFIGURATION
# ======================
GREEN_API = {
    "idInstance": "7105261536",
    "apiToken": "13a4bbfd70394a1c862c5d709671333fb1717111737a4f7998",
    "apiUrl": "https://7105.api.greenapi.com",
    "mediaUrl": "https://7105.media.greenapi.com"
}
AUTHORIZED_GROUP = "120363421227499361@g.us"
BOT_NUMBER = "923400315734@c.us"
ADMIN_NUMBER = "923247220362@c.us"

# Cookie configuration
YT_COOKIES_FILE = "cookies.txt"
YT_COOKIES_DRIVE_URL = "https://drive.google.com/uc?export=download&id=13iX8xpx47W3PAedGyhGpF5CxZRFz4uaF"

# Thread pool for concurrent processing
executor = ThreadPoolExecutor(max_workers=5)

# ======================
# LOGGING SETUP
# ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def download_file(url, filename):
    """Download file from Google Drive"""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        logger.info(f"Downloaded {filename} successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to download {filename}: {str(e)}")
        return False

def ensure_cookies():
    """Ensure YouTube cookies file exists"""
    if not os.path.exists(YT_COOKIES_FILE):
        logger.info("Downloading YouTube cookies...")
        return download_file(YT_COOKIES_DRIVE_URL, YT_COOKIES_FILE)
    return True

def send_whatsapp_message(text, chat_id=None):
    """Send text message to authorized group or specified chat"""
    try:
        target_chat = chat_id if chat_id else AUTHORIZED_GROUP
        response = requests.post(
            f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/sendMessage/{GREEN_API['apiToken']}",
            json={"chatId": target_chat, "message": text},
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        logger.info(f"Message sent to {target_chat}: {text[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Message send error: {str(e)}")
        return False

def send_whatsapp_file(file_path, caption, is_video=False, chat_id=None):
    """Send file with caption to group or specified chat"""
    try:
        target_chat = chat_id if chat_id else AUTHORIZED_GROUP
        with open(file_path, 'rb') as file:
            response = requests.post(
                f"{GREEN_API['mediaUrl']}/waInstance{GREEN_API['idInstance']}/sendFileByUpload/{GREEN_API['apiToken']}",
                files={'file': (os.path.basename(file_path), file, 
                      'video/mp4' if is_video else 'audio/mpeg')},
                data={'chatId': target_chat, 'caption': caption}
            )
            response.raise_for_status()
            logger.info(f"File sent to {target_chat}: {caption[:50]}...")
            return True
    except Exception as e:
        logger.error(f"File send error: {str(e)}")
        return False

def check_audio(filename):
    """Check if file has audio stream"""
    try:
        result = subprocess.run(
            ['ffprobe', '-i', filename, '-show_streams', '-select_streams', 'a', '-loglevel', 'error'],
            capture_output=True,
            text=True
        )
        return "codec_type=audio" in result.stdout
    except Exception as e:
        logger.error(f"Audio check error: {str(e)}")
        return False

def download_media(url, quality):
    """Download media with selected quality - FIXED VERSION"""
    try:
        ensure_cookies()
        
        temp_dir = tempfile.mkdtemp()
        
        # Updated yt-dlp options with better error handling
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title).100s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True,
            'extract_flat': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.youtube.com/'
            }
        }
        
        # Add cookies if available
        if os.path.exists(YT_COOKIES_FILE):
            ydl_opts['cookiefile'] = YT_COOKIES_FILE
            logger.info("Using cookies for YouTube download")
        
        # Handle different quality options
        if quality == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            # Use adaptive format selection for better compatibility
            ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
            ydl_opts['merge_output_format'] = 'mp4'
        
        logger.info(f"Starting download with options: {ydl_opts}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # First get info without downloading
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown Title')
            logger.info(f"Video title: {title}")
            
            # Now download
            ydl.download([url])
            
            # Find the downloaded file
            for file in os.listdir(temp_dir):
                if file.endswith(('.mp4', '.mp3', '.webm')):
                    file_path = os.path.join(temp_dir, file)
                    
                    # Check file size (max 100MB)
                    if os.path.getsize(file_path) > 100 * 1024 * 1024:
                        os.remove(file_path)
                        return None, "📛 *File size exceeds 100MB limit*"
                    
                    # For video files, check if they have audio
                    if file.endswith('.mp4') and not check_audio(file_path):
                        logger.warning("Video has no audio, trying different format")
                        os.remove(file_path)
                        # Try with different format
                        ydl_opts['format'] = 'best[acodec!=none][vcodec!=none]'
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl_retry:
                            ydl_retry.download([url])
                            # Find the new file
                            for retry_file in os.listdir(temp_dir):
                                if retry_file.endswith(('.mp4', '.mp3', '.webm')):
                                    return os.path.join(temp_dir, retry_file), title
                        return None, "❌ *No suitable format with audio found*"
                    
                    return file_path, title
        
        return None, "❌ *No file found after download*"
        
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp Download error: {str(e)}")
        
        # Try fallback method without cookies
        try:
            logger.info("Trying fallback download without cookies")
            fallback_opts = {
                'outtmpl': os.path.join(temp_dir, '%(title).100s.%(ext)s'),
                'format': 'best[height<=480]',
                'merge_output_format': 'mp4',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*'
                }
            }
            
            with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                ydl.download([url])
                
                for file in os.listdir(temp_dir):
                    if file.endswith(('.mp4', '.mp3')):
                        return os.path.join(temp_dir, file), "Downloaded Video"
            
            return None, "❌ *Download failed even with fallback method*"
            
        except Exception as fallback_error:
            logger.error(f"Fallback download also failed: {str(fallback_error)}")
            return None, "❌ *YouTube is blocking downloads. Try again later.*"
            
    except Exception as e:
        logger.error(f"Unexpected download error: {str(e)}")
        return None, f"❌ *Download error: {str(e)}*"

def process_youtube_download(url, chat_id):
    """Process YouTube download request"""
    try:
        send_whatsapp_message("⬇️ *Starting YouTube download...*", chat_id)
        
        # Try MP3 first (usually more reliable)
        file_path, result = download_media(url, 'mp3')
        
        if file_path:
            if file_path.endswith('.mp3'):
                send_whatsapp_file(file_path, "🎵 *YouTube Audio*", is_video=False, chat_id=chat_id)
            else:
                send_whatsapp_file(file_path, "🎥 *YouTube Video*", is_video=True, chat_id=chat_id)
            
            # Cleanup
            os.remove(file_path)
            os.rmdir(os.path.dirname(file_path))
        else:
            send_whatsapp_message(result, chat_id)
            
    except Exception as e:
        logger.error(f"YouTube download processing error: {str(e)}")
        send_whatsapp_message("❌ *Failed to process YouTube download*", chat_id)

def process_user_message(message, chat_id, sender):
    """Process user message"""
    try:
        # Check if it's a YouTube URL
        if any(domain in message.lower() for domain in ['youtube.com', 'youtu.be']):
            executor.submit(process_youtube_download, message, chat_id)
        
        elif message.lower() in ['hi', 'hello', 'hey', '/help', 'help']:
            help_text = """👋 *YouTube Downloader Bot*

📥 *Media Download:*
Simply paste any YouTube URL to download as MP3 audio

⚡ *Features:*
- Automatic MP3 conversion
- 100MB file size limit
- Fast downloads

*Just send me a YouTube link!*"""
            send_whatsapp_message(help_text, chat_id)

    except Exception as e:
        logger.error(f"Message processing error: {str(e)}")
        send_whatsapp_message("❌ *An error occurred. Please try again.*", chat_id)

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.json
        logger.info(f"RAW WEBHOOK DATA:\n{data}")

        sender_data = data.get('senderData', {})
        sender = sender_data.get('sender', '')
        chat_id = sender_data.get('chatId', '')
        
        # Ignore messages from the bot itself
        if BOT_NUMBER in sender:
            logger.info("Ignoring message from bot itself")
            return jsonify({'status': 'ignored'}), 200
        
        # Get message content
        message_data = data.get('messageData', {})
        if message_data.get('typeMessage') == 'textMessage':
            message = message_data.get('textMessageData', {}).get('textMessage', '').strip()
        elif message_data.get('typeMessage') == 'extendedTextMessage':
            message = message_data.get('extendedTextMessageData', {}).get('text', '').strip()
        else:
            logger.warning(f"Unsupported message type: {message_data.get('typeMessage')}")
            return jsonify({'status': 'unsupported_type'}), 200

        if not message:
            logger.warning("Received empty message")
            return jsonify({'status': 'empty_message'}), 200

        logger.info(f"PROCESSING MESSAGE FROM {sender} IN CHAT {chat_id}: {message}")

        # Allow processing if in authorized group or from admin
        if chat_id == AUTHORIZED_GROUP or (sender == ADMIN_NUMBER and not chat_id.endswith('@g.us')):
            process_user_message(message, chat_id, sender)
            return jsonify({'status': 'processing'}), 200
        else:
            logger.warning(f"Ignoring message from unauthorized chat: {chat_id}")
            return jsonify({'status': 'ignored'}), 200

    except Exception as e:
        logger.error(f"WEBHOOK ERROR: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/')
def health_check():
    return jsonify({
        "status": "active",
        "service": "YouTube Downloader",
        "timestamp": "2025-11-16T03:00:00Z"
    })

if __name__ == '__main__':
    ensure_cookies()
    
    logger.info(f"""
    ============================================
    YouTube Downloader Bot READY
    Features: YouTube to MP3 downloads
    Max file size: 100MB
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
