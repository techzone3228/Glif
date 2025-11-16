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

def get_available_qualities(url):
    """Get available qualities for URL - PROPER QUALITY MAPPING"""
    try:
        ensure_cookies()
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None,
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
            
            # PROPER QUALITY MAPPING - Store actual format combinations
            quality_map = {}
            formats = info.get('formats', [])
            
            # Find best formats for each quality
            for fmt in formats:
                height = fmt.get('height', 0)
                format_id = fmt.get('format_id', '')
                
                # Only consider formats with video
                if fmt.get('vcodec') != 'none':
                    if 140 <= height <= 144 and '144p' not in quality_map:
                        quality_map['144p'] = format_id
                    elif 230 <= height <= 360 and '360p' not in quality_map:
                        quality_map['360p'] = format_id
                    elif 370 <= height <= 480 and '480p' not in quality_map:
                        quality_map['480p'] = format_id
                    elif 550 <= height <= 720 and '720p' not in quality_map:
                        quality_map['720p'] = format_id
                    elif 870 <= height <= 1080 and '1080p' not in quality_map:
                        quality_map['1080p'] = format_id
            
            # Add best quality option
            quality_map['best'] = 'bestvideo+bestaudio/best'
            quality_map['mp3'] = 'bestaudio/best'
            
            logger.info(f"Available qualities: {quality_map}")
            return quality_map
            
    except Exception as e:
        logger.error(f"YouTube quality error: {str(e)}")
        return None

def download_media_with_quality(url, quality, format_id=None):
    """Download media with EXACT quality selection"""
    try:
        ensure_cookies()
        
        temp_dir = tempfile.mkdtemp()
        
        # yt-dlp options with modern settings
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title).100s.%(ext)s'),
            'merge_output_format': 'mp4',
            'quiet': True,
            'retries': 3,
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
        
        # EXACT QUALITY SELECTION LOGIC
        if quality == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        elif quality == 'best':
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
        else:
            # USE SPECIFIC FORMAT ID FOR EXACT QUALITY
            if format_id and format_id != 'bestvideo+bestaudio/best':
                ydl_opts['format'] = format_id
            else:
                # Fallback to height-based selection
                height_map = {
                    '144p': 'best[height<=144]',
                    '360p': 'best[height<=360]',
                    '480p': 'best[height<=480]',
                    '720p': 'best[height<=720]',
                    '1080p': 'best[height<=1080]'
                }
                ydl_opts['format'] = height_map.get(quality, 'best')
        
        logger.info(f"Downloading with quality: {quality}, format: {ydl_opts['format']}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_files = []
            
            # Find all downloaded files
            for file in os.listdir(temp_dir):
                if any(file.endswith(ext) for ext in ['.mp4', '.mp3', '.webm', '.m4a']):
                    file_path = os.path.join(temp_dir, file)
                    downloaded_files.append(file_path)
            
            if not downloaded_files:
                return None, "No file downloaded"
            
            # Use the main file (usually the first one)
            main_file = downloaded_files[0]
            file_size = os.path.getsize(main_file)
            
            # Check file size limit
            if file_size > 100 * 1024 * 1024:
                for f in downloaded_files:
                    os.remove(f)
                return None, "📛 *File size exceeds 100MB limit*"
            
            title = info.get('title', 'Unknown Title')
            
            # For MP3, ensure proper extension
            if quality == 'mp3' and not main_file.endswith('.mp3'):
                mp3_file = main_file.rsplit('.', 1)[0] + '.mp3'
                if os.path.exists(mp3_file):
                    return mp3_file, title
                else:
                    # Convert to MP3 if needed
                    converted_file = main_file.rsplit('.', 1)[0] + '.mp3'
                    try:
                        subprocess.run([
                            'ffmpeg', '-i', main_file, '-codec:a', 'libmp3lame', 
                            '-q:a', '2', converted_file, '-y'
                        ], capture_output=True, timeout=30)
                        if os.path.exists(converted_file):
                            os.remove(main_file)
                            return converted_file, title
                    except:
                        pass
            
            return main_file, title
            
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return None, f"Download failed: {str(e)}"
    finally:
        # Cleanup temp directory
        try:
            for file in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(temp_dir)
        except:
            pass

def send_quality_options(session_key, url, chat_id=None):
    """Send available quality options"""
    send_whatsapp_message("🔍 *Checking available video qualities...*", chat_id)
    
    try:
        quality_map = get_available_qualities(url)
        if not quality_map:
            send_whatsapp_message("❌ *No qualities available for this video*", chat_id)
            return
        
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
            
            # Show available qualities in order
            quality_order = ['144p', '360p', '480p', '720p', '1080p', 'best', 'mp3']
            
            for qual in quality_order:
                if qual in quality_map:
                    if qual == 'mp3':
                        options_text += f"{option_number}. *MP3* _(Audio only)_ 🎵\n"
                        user_sessions[session_key]['option_map'][str(option_number)] = ('mp3', quality_map[qual])
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
                    file_path, title_or_error = download_media_with_quality(url, 'mp3', format_id)
                else:
                    send_whatsapp_message(f"⬇️ *Downloading {quality} quality...* 🎬", chat_id)
                    file_path, title_or_error = download_media_with_quality(url, quality, format_id)
                
                if file_path:
                    is_video = not file_path.endswith('.mp3')
                    quality_display = 'MP3' if not is_video else quality
                    caption = f"🎵 *{title_or_error}*" if not is_video else f"🎥 *{title_or_error}*\n*Quality:* {quality}"
                    
                    if send_whatsapp_file(file_path, caption, is_video=is_video, chat_id=chat_id):
                        # Cleanup
                        try:
                            os.remove(file_path)
                            os.rmdir(os.path.dirname(file_path))
                        except:
                            pass
                    else:
                        send_whatsapp_message("❌ *Failed to send file*", chat_id)
                else:
                    error_msg = title_or_error if isinstance(title_or_error, str) else "❌ *Failed to download media*"
                    send_whatsapp_message(error_msg, chat_id)
            else:
                send_whatsapp_message("❌ *Invalid choice. Please select a valid number.*", chat_id)
            return

        # Handle URLs
        elif any(proto in message.lower() for proto in ['http://', 'https://']):
            ensure_cookies()
            send_quality_options(session_key, message, chat_id)
        
        # Handle commands
        elif message.lower() in ['hi', 'hello', 'hey', '/help', 'help']:
            help_text = """👋 *YouTube Downloader Bot*

📥 *Media Download:*
Send any YouTube URL to download

🎯 *Quality Options:*
- 144p, 360p, 480p, 720p, 1080p
- Best available quality
- MP3 audio

⚡ *Features:*
- Exact quality selection
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
        "service": "YouTube Downloader with Exact Quality Selection",
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    ensure_cookies()
    
    logger.info(f"""
    ============================================
    YouTube Downloader Bot READY
    Features: Exact quality selection
    Max file size: 100MB
    yt-dlp: 2025.10.14
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
