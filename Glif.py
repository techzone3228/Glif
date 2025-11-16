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

# Thread-safe session management
user_sessions = {}
session_lock = threading.Lock()

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

def get_available_qualities(url):
    """Get available qualities for YouTube URL"""
    try:
        ensure_cookies()
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.youtube.com/'
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or 'formats' not in info:
                return None
            
            quality_map = {}
            for fmt in info.get('formats', []):
                if fmt.get('vcodec') != 'none':
                    height = fmt.get('height', 0)
                    if height >= 1080: quality_map['1080p'] = fmt['format_id']
                    if height >= 720: quality_map['720p'] = fmt['format_id']
                    if height >= 480: quality_map['480p'] = fmt['format_id']
                    if height >= 360: quality_map['360p'] = fmt['format_id']
                    if height >= 144: quality_map['144p'] = fmt['format_id']
            
            quality_map['best'] = 'bestvideo+bestaudio/best'
            quality_map['mp3'] = 'bestaudio/best'
            return {q: quality_map[q] for q in ['144p', '360p', '480p', '720p', '1080p', 'best', 'mp3'] if q in quality_map}
    except Exception as e:
        logger.error(f"YouTube quality error: {str(e)}")
        return None

def send_quality_options(session_key, url, chat_id=None):
    """Send available quality options"""
    send_whatsapp_message("🔍 *Checking available video qualities...*", chat_id)
    
    try:
        quality_map = get_available_qualities(url)
        if not quality_map:
            raise Exception("No qualities available")
        
        with session_lock:
            user_sessions[session_key] = {
                'url': url,
                'quality_map': quality_map,
                'awaiting_quality': True,
                'option_map': {},
                'chat_id': chat_id
            }
            
            options_text = "📺 *Available download options (Max 100MB):*\n\n"
            option_number = 1
            
            for qual in quality_map:
                if qual == 'mp3':
                    options_text += f"{option_number}. *MP3* _(Audio only)_ 🎵\n"
                    user_sessions[session_key]['option_map'][str(option_number)] = ('mp3', None)
                elif qual == 'best':
                    options_text += f"{option_number}. *Best available quality* 🌟\n"
                    user_sessions[session_key]['option_map'][str(option_number)] = ('best', quality_map[qual])
                else:
                    options_text += f"{option_number}. *{qual}* 📹\n"
                    user_sessions[session_key]['option_map'][str(option_number)] = (qual, quality_map[qual])
                option_number += 1
            
            options_text += "\n_Reply with the number of your choice_"
            send_whatsapp_message(options_text, chat_id)
    except Exception as e:
        error_msg = "⚠️ *Error checking video qualities. Please try again later.*"
        send_whatsapp_message(error_msg, chat_id)
        logger.error(f"Quality options error: {str(e)}")

def download_media(url, quality, format_id=None):
    """Download media with selected quality - IMPROVED VERSION"""
    try:
        ensure_cookies()
        
        temp_dir = tempfile.mkdtemp()
        
        # Base yt-dlp options
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
        
        # IMPROVED: Better format selection based on quality
        if quality == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            # Use specific format selection for each quality
            format_selector = {
                '144p': 'bestvideo[height<=144][vcodec^=avc1]+bestaudio/best[height<=144]',
                '360p': 'bestvideo[height<=360][vcodec^=avc1]+bestaudio/best[height<=360]',
                '480p': 'bestvideo[height<=480][vcodec^=avc1]+bestaudio/best[height<=480]',
                '720p': 'bestvideo[height<=720][vcodec^=avc1]+bestaudio/best[height<=720]',
                '1080p': 'bestvideo[height<=1080][vcodec^=avc1]+bestaudio/best[height<=1080]',
                'best': 'bestvideo[ext=mp4][vcodec^=avc1]+bestaudio/best'
            }.get(quality, 'bestvideo+bestaudio/best')
            
            ydl_opts['format'] = format_selector
            ydl_opts['merge_output_format'] = 'mp4'
        
        logger.info(f"Starting download with quality: {quality}, format: {ydl_opts['format']}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Get info first to verify format availability
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown Title')
            logger.info(f"Video title: {title}")
            
            # Now download with the selected format
            ydl.download([url])
            
            # Find the downloaded file
            downloaded_files = []
            for file in os.listdir(temp_dir):
                if file.endswith(('.mp4', '.mp3', '.webm', '.m4a')):
                    file_path = os.path.join(temp_dir, file)
                    downloaded_files.append(file_path)
            
            if not downloaded_files:
                return None, "❌ *No file found after download*"
            
            # Use the first found file
            file_path = downloaded_files[0]
            
            # Check file size (max 100MB)
            if os.path.getsize(file_path) > 100 * 1024 * 1024:
                os.remove(file_path)
                return None, "📛 *File size exceeds 100MB limit*"
            
            # For MP3 files, ensure proper extension
            if quality == 'mp3':
                if not file_path.endswith('.mp3'):
                    mp3_file = file_path.rsplit('.', 1)[0] + '.mp3'
                    if os.path.exists(mp3_file):
                        return mp3_file, title
                    else:
                        # Convert to MP3 if needed
                        converted_file = file_path.rsplit('.', 1)[0] + '.mp3'
                        subprocess.run([
                            'ffmpeg', '-i', file_path, '-codec:a', 'libmp3lame', 
                            '-q:a', '2', converted_file, '-y'
                        ], capture_output=True)
                        if os.path.exists(converted_file):
                            os.remove(file_path)
                            return converted_file, title
            
            # For video files, check if they have audio
            if file_path.endswith('.mp4') and not check_audio(file_path):
                logger.warning("Video has no audio, trying format with audio")
                os.remove(file_path)
                # Try with format that guarantees audio
                ydl_opts['format'] = 'best[acodec!=none][vcodec!=none]/best'
                with yt_dlp.YoutubeDL(ydl_opts) as ydl_retry:
                    ydl_retry.download([url])
                    # Find the new file
                    for retry_file in os.listdir(temp_dir):
                        if retry_file.endswith('.mp4'):
                            retry_path = os.path.join(temp_dir, retry_file)
                            if os.path.getsize(retry_path) <= 100 * 1024 * 1024:
                                return retry_path, title
                return None, "❌ *No suitable format with audio found*"
            
            return file_path, title
        
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp Download error: {str(e)}")
        
        # IMPROVED: Try alternative format selectors instead of just fallback
        alternative_formats = [
            f'bestvideo[height<={quality.replace("p", "")}]+bestaudio/best',
            f'best[height<={quality.replace("p", "")}]',
            'best[ext=mp4]',
            'best'
        ]
        
        for alt_format in alternative_formats:
            try:
                logger.info(f"Trying alternative format: {alt_format}")
                fallback_opts = {
                    'outtmpl': os.path.join(temp_dir, '%(title).100s.%(ext)s'),
                    'format': alt_format,
                    'merge_output_format': 'mp4' if quality != 'mp3' else None,
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': '*/*'
                    },
                    'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None
                }
                
                if quality == 'mp3':
                    fallback_opts['format'] = 'bestaudio/best'
                    fallback_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]
                
                with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                    ydl.download([url])
                    
                    for file in os.listdir(temp_dir):
                        if file.endswith(('.mp4', '.mp3')):
                            file_path = os.path.join(temp_dir, file)
                            if os.path.getsize(file_path) <= 100 * 1024 * 1024:
                                return file_path, f"Downloaded ({quality} attempt)"
                
            except Exception as alt_error:
                logger.warning(f"Alternative format {alt_format} failed: {str(alt_error)}")
                continue
        
        return None, "❌ *YouTube is blocking downloads. Try again later.*"
            
    except Exception as e:
        logger.error(f"Unexpected download error: {str(e)}")
        return None, f"❌ *Download error: {str(e)}*"

def process_user_message(session_key, message, chat_id, sender):
    """Process user message"""
    try:
        with session_lock:
            session_data = user_sessions.get(session_key, {})
        
        # Handle quality selection
        if session_data.get('awaiting_quality'):
            choice = message.strip()
            option_map = session_data.get('option_map', {})
            
            if choice in option_map:
                quality, format_id = option_map[choice]
                url = session_data['url']
                
                with session_lock:
                    if session_key in user_sessions:
                        del user_sessions[session_key]
                
                if quality == 'mp3':
                    send_whatsapp_message("⬇️ *Downloading MP3 audio...* 🎵", chat_id)
                    file_path, title_or_error = download_media(url, 'mp3')
                    if file_path:
                        send_whatsapp_file(file_path, f"🎵 *{title_or_error}*", is_video=False, chat_id=chat_id)
                        os.remove(file_path)
                        os.rmdir(os.path.dirname(file_path))
                    else:
                        error_msg = title_or_error if isinstance(title_or_error, str) else "❌ *Failed to download audio. Please try again.*"
                        send_whatsapp_message(error_msg, chat_id)
                else:
                    send_whatsapp_message(f"⬇️ *Downloading {quality} quality...* 🎬", chat_id)
                    file_path, title_or_error = download_media(url, quality, format_id)
                    if file_path:
                        send_whatsapp_file(file_path, f"🎥 *{title_or_error}*\n*Quality:* {quality}", is_video=True, chat_id=chat_id)
                        os.remove(file_path)
                        os.rmdir(os.path.dirname(file_path))
                    else:
                        error_msg = title_or_error if isinstance(title_or_error, str) else "❌ *Failed to download media. Please try again.*"
                        send_whatsapp_message(error_msg, chat_id)
            else:
                send_whatsapp_message("❌ *Invalid choice. Please select one of the available options.*", chat_id)
                with session_lock:
                    if session_key in user_sessions:
                        url = user_sessions[session_key]['url']
                send_quality_options(session_key, url, chat_id)
            return

        # Check if it's a YouTube URL
        if any(domain in message.lower() for domain in ['youtube.com', 'youtu.be']):
            send_quality_options(session_key, message, chat_id)
        
        elif message.lower() in ['hi', 'hello', 'hey', '/help', 'help']:
            help_text = """👋 *YouTube Downloader Bot*

📥 *Media Download:*
Simply paste any YouTube URL to download
Choose from multiple quality options

⚡ *Features:*
- Multiple video qualities (144p to 1080p)
- MP3 audio downloads
- 100MB file size limit
- Quality selection menu

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

        # Create unique session key
        session_key = f"{chat_id}_{sender}"

        # Allow processing if in authorized group or from admin
        if chat_id == AUTHORIZED_GROUP or (sender == ADMIN_NUMBER and not chat_id.endswith('@g.us')):
            process_user_message(session_key, message, chat_id, sender)
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
        "service": "YouTube Downloader with Quality Options",
        "timestamp": "2025-11-16T03:40:00Z"
    })

if __name__ == '__main__':
    ensure_cookies()
    
    logger.info(f"""
    ============================================
    YouTube Downloader Bot READY
    Features: Multiple quality options + MP3
    Max file size: 100MB
    Cookies: Enabled
    Improved format selection
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
