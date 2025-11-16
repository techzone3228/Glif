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
from datetime import datetime

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
executor = ThreadPoolExecutor(max_workers=3)

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

def get_estimated_size(url, quality):
    """Estimate file size before downloading"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
                
            if 'filesize' in info and info['filesize']:
                return info['filesize']
                
            if 'duration' in info and 'format' in info:
                duration = info['duration']
                bitrate = 0
                
                if quality == 'mp3':
                    bitrate = 192  # kbps
                elif quality == '144p':
                    bitrate = 200  # kbps
                elif quality == '360p':
                    bitrate = 500  # kbps
                elif quality == '480p':
                    bitrate = 1000 # kbps
                elif quality == '720p':
                    bitrate = 2500 # kbps
                elif quality == '1080p':
                    bitrate = 5000 # kbps
                else:  # best or unknown
                    bitrate = 8000 # kbps
                
                estimated_size = (bitrate * 1000 * duration) / 8
                return estimated_size
                
        return None
    except Exception as e:
        logger.error(f"Size estimation error: {str(e)}")
        return None

def get_available_qualities(url):
    """Get available qualities for URL - ORIGINAL LOGIC"""
    try:
        ensure_cookies()
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None,
            # Updated for 2025
            "extractor_args": {
                "youtube": {
                    "player_skip": ["configs"],
                    "player_client": ["ios", "android", "web_safari", "web"]
                }
            },
            "nocheckcertificate": True,
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

def download_media(url, quality, format_id=None):
    """Download media with selected quality - ORIGINAL LOGIC"""
    try:
        ensure_cookies()
        
        estimated_size = get_estimated_size(url, quality)
        if estimated_size and estimated_size > 100 * 1024 * 1024:
            return None, "📛 *File size exceeds 100MB limit*"
        
        temp_dir = tempfile.mkdtemp()
        
        # Updated yt-dlp options for 2025
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'quiet': True,
            'retries': 3,
            # Updated for 2025
            "extractor_args": {
                "youtube": {
                    "player_skip": ["configs"],
                    "player_client": ["ios", "android", "web_safari", "web"]
                }
            },
            "nocheckcertificate": True,
        }
        
        if os.path.exists(YT_COOKIES_FILE):
            ydl_opts['cookiefile'] = YT_COOKIES_FILE
        
        if quality == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            # ORIGINAL QUALITY SELECTION LOGIC
            if is_youtube_url(url):
                ydl_opts['format'] = {
                    '144p': 'bestvideo[height<=144]+bestaudio/best',
                    '360p': 'bestvideo[height<=360]+bestaudio/best',
                    '480p': 'bestvideo[height<=480]+bestaudio/best',
                    '720p': 'bestvideo[height<=720]+bestaudio/best',
                    '1080p': 'bestvideo[height<=1080]+bestaudio/best',
                    'best': 'bestvideo+bestaudio/best'
                }.get(quality, 'bestvideo+bestaudio/best')
            else:
                ydl_opts['format'] = format_id or 'bestvideo+bestaudio/best'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if os.path.exists(filename) and os.path.getsize(filename) > 100 * 1024 * 1024:
                os.remove(filename)
                return None, "📛 *File size exceeds 100MB limit*"
            
            if quality == 'mp3':
                mp3_file = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
                if os.path.exists(mp3_file):
                    if os.path.getsize(mp3_file) > 100 * 1024 * 1024:
                        os.remove(mp3_file)
                        return None, "📛 *File size exceeds 100MB limit*"
                    return mp3_file, info.get('title', 'audio')
            else:
                if check_audio(filename):
                    new_filename = f"{os.path.splitext(filename)[0]}_{quality}.mp4"
                    os.rename(filename, new_filename)
                    return new_filename, info.get('title', 'video')
                
        return None, None
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return None, None
    finally:
        try:
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except Exception as e:
            logger.warning(f"Temp dir cleanup error: {str(e)}")

def is_youtube_url(url):
    """Check if URL is from YouTube"""
    return 'youtube.com' in url or 'youtu.be' in url

def send_quality_options(session_key, url, chat_id=None):
    """Send available quality options - ORIGINAL LOGIC"""
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
                if qual == 'mp3' or '(Audio)' in qual:
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

def process_user_message(session_key, message, chat_id, sender):
    """Process user message - ORIGINAL LOGIC"""
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
                
                if quality == 'mp3' or '(Audio)' in quality:
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

        # Command handling
        if message.lower() in ['hi', 'hello', 'hey']:
            help_text = """👋 *Hello! Here's what I can do:*

📥 *Media Download:*
Simply paste any video URL (YouTube, Instagram, TikTok, etc.) to download
_(Max file size: 100MB)_

🎯 *Quality Selection:*
- Exact quality selection (144p to 1080p)
- MP3 audio extraction
- Best available quality

*Just send me a YouTube link!*"""
            send_whatsapp_message(help_text, chat_id)
        
        elif message.lower().startswith(('/help', 'help', 'info')):
            help_text = """ℹ️ *Bot Help Menu* ℹ️

📥 *Media Download:*
Just send me a video URL from:
- YouTube
- Instagram  
- TikTok
- Facebook
- And many more!
_(Maximum file size: 100MB)_

🎯 *Quality Features:*
- Exact resolution selection
- MP3 audio conversion
- Smart quality detection

Need more help? Contact admin!"""
            send_whatsapp_message(help_text, chat_id)
        
        # Handle URLs
        elif any(proto in message.lower() for proto in ['http://', 'https://']):
            ensure_cookies()
            send_quality_options(session_key, message, chat_id)

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
        "authorized_group": AUTHORIZED_GROUP,
        "instance_id": GREEN_API['idInstance'],
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    ensure_cookies()
    
    logger.info(f"""
    ============================================
    WhatsApp Media Bot READY
    Responding to group: {AUTHORIZED_GROUP}
    And admin ({ADMIN_NUMBER}) in personal chat
    Ignoring messages from: {BOT_NUMBER}
    GreenAPI Instance: {GREEN_API['idInstance']}
    yt-dlp Version: 2025.10.14
    Max file size: 100MB
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
