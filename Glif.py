from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
import yt_dlp
import os
import tempfile
import subprocess
import threading
import random
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
    """Download media with selected quality - COMPREHENSIVE FIX"""
    try:
        ensure_cookies()
        
        temp_dir = tempfile.mkdtemp()
        
        # Multiple User-Agent strings to rotate
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]
        
        # STRATEGY 1: Try with comprehensive headers and cookies first
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title).100s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'extract_flat': False,
            'http_headers': {
                'User-Agent': random.choice(user_agents),
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://www.youtube.com/',
                'Origin': 'https://www.youtube.com',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site',
                'DNT': '1',
                'Connection': 'keep-alive',
            },
            'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'webpage']
                }
            }
        }
        
        # Format selection
        if quality == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            # Try different format combinations
            format_options = [
                f'bestvideo[height<={quality.replace("p", "")}]+bestaudio/best',
                f'best[height<={quality.replace("p", "")}]',
                'best[ext=mp4]',
                'best'
            ]
            ydl_opts['format'] = format_options[0]
            ydl_opts['merge_output_format'] = 'mp4'
        
        logger.info(f"STRATEGY 1: Starting download with quality: {quality}")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Unknown Title')
                logger.info(f"Video title: {title}")
                
                ydl.download([url])
                
                # Check for downloaded files
                for file in os.listdir(temp_dir):
                    if file.endswith(('.mp4', '.mp3', '.webm', '.m4a')):
                        file_path = os.path.join(temp_dir, file)
                        if os.path.getsize(file_path) <= 100 * 1024 * 1024:
                            return file_path, title
                
                return None, "❌ *No file found after download*"
                
        except Exception as e:
            logger.warning(f"Strategy 1 failed: {str(e)}")
        
        # STRATEGY 2: Try with different extractor arguments
        logger.info("STRATEGY 2: Trying different extractor arguments")
        ydl_opts_2 = {
            'outtmpl': os.path.join(temp_dir, '%(title).100s.%(ext)s'),
            'format': 'best[height<=720]/best[height<=480]/best',
            'merge_output_format': 'mp4',
            'http_headers': {
                'User-Agent': random.choice(user_agents),
                'Accept': '*/*',
                'Referer': 'https://www.youtube.com/',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android_embed'],
                    'skip': ['dash', 'hls']
                }
            },
            'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None,
        }
        
        if quality == 'mp3':
            ydl_opts_2['format'] = 'bestaudio/best'
            ydl_opts_2['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts_2) as ydl:
                ydl.download([url])
                
                for file in os.listdir(temp_dir):
                    if file.endswith(('.mp4', '.mp3')):
                        file_path = os.path.join(temp_dir, file)
                        if os.path.getsize(file_path) <= 100 * 1024 * 1024:
                            return file_path, "Downloaded Video"
        except Exception as e:
            logger.warning(f"Strategy 2 failed: {str(e)}")
        
        # STRATEGY 3: Try without cookies (sometimes cookies cause issues)
        logger.info("STRATEGY 3: Trying without cookies")
        ydl_opts_3 = {
            'outtmpl': os.path.join(temp_dir, '%(title).100s.%(ext)s'),
            'format': 'best[height<=480]/best',
            'merge_output_format': 'mp4',
            'http_headers': {
                'User-Agent': random.choice(user_agents),
                'Accept': '*/*',
                'Referer': 'https://www.youtube.com/',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_html5', 'web']
                }
            }
        }
        
        if quality == 'mp3':
            ydl_opts_3['format'] = 'bestaudio/best'
            ydl_opts_3['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts_3) as ydl:
                ydl.download([url])
                
                for file in os.listdir(temp_dir):
                    if file.endswith(('.mp4', '.mp3')):
                        file_path = os.path.join(temp_dir, file)
                        if os.path.getsize(file_path) <= 100 * 1024 * 1024:
                            return file_path, "Downloaded Video"
        except Exception as e:
            logger.warning(f"Strategy 3 failed: {str(e)}")
        
        # STRATEGY 4: Last resort - try with minimal options
        logger.info("STRATEGY 4: Trying minimal options")
        ydl_opts_4 = {
            'outtmpl': os.path.join(temp_dir, '%(title).100s.%(ext)s'),
            'format': 'best',
            'merge_output_format': 'mp4',
        }
        
        if quality == 'mp3':
            ydl_opts_4['format'] = 'bestaudio/best'
            ydl_opts_4['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts_4) as ydl:
                ydl.download([url])
                
                for file in os.listdir(temp_dir):
                    if file.endswith(('.mp4', '.mp3')):
                        file_path = os.path.join(temp_dir, file)
                        if os.path.getsize(file_path) <= 100 * 1024 * 1024:
                            return file_path, "Downloaded Video (Fallback)"
        except Exception as e:
            logger.warning(f"Strategy 4 failed: {str(e)}")
        
        return None, "❌ *All download strategies failed. YouTube is blocking downloads.*"
        
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
        "service": "YouTube Downloader with Multiple Strategies",
        "timestamp": "2025-11-16T03:45:00Z"
    })

if __name__ == '__main__':
    ensure_cookies()
    
    logger.info(f"""
    ============================================
    YouTube Downloader Bot READY
    Features: Multiple bypass strategies
    Max file size: 100MB
    Cookies: Enabled
    Multiple fallback strategies
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
