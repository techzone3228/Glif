from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
from datetime import datetime
import yt_dlp
import os
import tempfile
import subprocess
import re

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
ADMIN_NUMBERS = ["923190779215@c.us"]  # Add admin numbers with @c.us suffix
COOKIES_FILE = "cookies.txt"
MAX_FILE_SIZE_MB = 100  # Maximum allowed file size in MB

# User session data
user_sessions = {}

# ======================
# LOGGING SETUP
# ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ======================
# CORE FUNCTIONS
# ======================
def send_whatsapp_message(text):
    """Send text message to authorized group"""
    url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/sendMessage/{GREEN_API['apiToken']}"
    payload = {
        "chatId": AUTHORIZED_GROUP,
        "message": text
    }
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"Message sent to group: {text[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Failed to send message to group: {str(e)}")
        return False

def send_whatsapp_file(file_path, caption, is_video=False):
    """Send file (video or image) with caption to group"""
    try:
        # Check file size before sending
        file_size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
        if file_size > MAX_FILE_SIZE_MB:
            logger.warning(f"File too large: {file_size:.2f}MB")
            return False
            
        url = f"{GREEN_API['mediaUrl']}/waInstance{GREEN_API['idInstance']}/sendFileByUpload/{GREEN_API['apiToken']}"
        
        with open(file_path, 'rb') as file:
            files = {
                'file': (os.path.basename(file_path), file, 'video/mp4' if is_video else 'audio/mpeg' if file_path.endswith('.mp3') else 'image/jpeg')
            }
            data = {
                'chatId': AUTHORIZED_GROUP,
                'caption': caption
            }
            
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            logger.info(f"File sent to group with caption: {caption[:50]}...")
            return True
            
    except Exception as e:
        logger.error(f"File upload to group failed: {str(e)}")
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
        logger.error(f"Error checking audio: {str(e)}")
        return False

def is_youtube_url(url):
    """Check if URL is from YouTube"""
    youtube_pattern = r'(https?://)?(www\.)?(youtube|youtu)\.(com|be)/.+'
    return re.match(youtube_pattern, url) is not None

def is_supported_url(url):
    """Check if URL is from supported platforms"""
    supported_patterns = [
        r'(https?://)?(www\.)?(youtube|youtu)\.(com|be)/.+',
        r'(https?://)?(www\.)?instagram\.com/.+',
        r'(https?://)?(www\.)?tiktok\.com/.+',
        r'(https?://)?(www\.)?facebook\.com/.+',
        r'(https?://)?(www\.)?twitter\.com/.+',
        r'(https?://)?(www\.)?dailymotion\.com/.+',
        r'(https?://)?(www\.)?vimeo\.com/.+'
    ]
    return any(re.match(pattern, url) for pattern in supported_patterns)

def get_available_qualities(url):
    """Check available qualities for videos"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_generic_extractor': True,
            'cookiefile': COOKIES_FILE
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or 'formats' not in info:
                return None
            
            formats = info.get('formats', [])
            quality_map = {}
            
            for fmt in formats:
                if fmt.get('vcodec') != 'none':
                    height = fmt.get('height', 0)
                    if height >= 1080:
                        quality_map['1080p'] = fmt['format_id']
                    if height >= 720:
                        quality_map['720p'] = fmt['format_id']
                    if height >= 480:
                        quality_map['480p'] = fmt['format_id']
                    if height >= 360:
                        quality_map['360p'] = fmt['format_id']
                    if height >= 144:
                        quality_map['144p'] = fmt['format_id']
            
            # Add best and mp3 options
            quality_map['best'] = 'bestvideo+bestaudio/best'
            quality_map['mp3'] = 'bestaudio/best'
            
            resolution_order = ['144p', '360p', '480p', '720p', '1080p', 'best', 'mp3']
            return {q: quality_map[q] for q in resolution_order if q in quality_map}
            
    except Exception as e:
        logger.error(f"Error checking video qualities: {str(e)}")
        return {'best': 'bestvideo+bestaudio/best', 'mp3': 'bestaudio/best'}

def download_media(url, quality, format_id=None):
    """Download media with selected quality"""
    try:
        temp_dir = tempfile.mkdtemp()
        
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'cookiefile': COOKIES_FILE,
            'merge_output_format': 'mp4',
            'postprocessors': [
                {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
                {'key': 'FFmpegMetadata'},
                {'key': 'EmbedThumbnail'}
            ],
            'quiet': True,
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True
        }
        
        if quality == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            ydl_opts['format'] = format_id if format_id else 'bestvideo+bestaudio/best'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Check file size before proceeding
            if os.path.exists(filename):
                file_size = os.path.getsize(filename) / (1024 * 1024)  # Size in MB
                if file_size > MAX_FILE_SIZE_MB:
                    logger.warning(f"Downloaded file too large: {file_size:.2f}MB")
                    return None, None
            
            if quality == 'mp3':
                mp3_file = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
                if os.path.exists(mp3_file):
                    return mp3_file, info.get('title', 'audio')
            else:
                if check_audio(filename):
                    new_filename = f"{os.path.splitext(filename)[0]}_{quality}.mp4"
                    os.rename(filename, new_filename)
                    return new_filename, info.get('title', 'video')
                
        return None, None
        
    except Exception as e:
        logger.error(f"Error downloading video: {str(e)}")
        return None, None
    finally:
        try:
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except Exception as e:
            logger.warning(f"Error cleaning temp dir: {str(e)}")

def send_quality_options(sender, url):
    """Check available qualities and send options to group"""
    send_whatsapp_message("🔍 Analyzing video... Please wait...")
    
    if not is_supported_url(url):
        send_whatsapp_message("⚠️ Unsupported platform. Trying to download anyway...")
    
    quality_map = get_available_qualities(url)
    if not quality_map:
        send_whatsapp_message("⚠️ Could not determine available qualities. Using default options...")
        quality_map = {'best': 'bestvideo+bestaudio/best', 'mp3': 'bestaudio/best'}
    
    # Store available qualities in user session with format_ids
    user_sessions[sender] = {
        'url': url,
        'quality_map': quality_map,
        'awaiting_quality': True
    }
    
    # Build options message
    options_text = "📺 Available Download Options:\n\n"
    option_number = 1
    option_map = {}
    
    for qual in quality_map.keys():
        if qual == 'mp3':
            options_text += f"{option_number}. 🎵 MP3 Audio (Best Quality)\n"
            option_map[str(option_number)] = ('mp3', None)
        elif qual == 'best':
            options_text += f"{option_number}. 🏆 Best Available Quality\n"
            option_map[str(option_number)] = ('best', quality_map[qual])
        else:
            options_text += f"{option_number}. 🎬 {qual} Video\n"
            option_map[str(option_number)] = (qual, quality_map[qual])
        option_number += 1
    
    options_text += "\nReply with the number of your choice"
    
    # Store the option mapping in user session
    user_sessions[sender]['option_map'] = option_map
    
    send_whatsapp_message(options_text)

def reset_bot():
    """Reset bot by clearing all sessions and temporary files"""
    global user_sessions
    user_sessions = {}
    logger.info("Bot has been reset - all sessions cleared")
    return True

# ======================
# WEBHOOK HANDLER
# ======================
@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.json
        logger.info(f"Incoming webhook data: {data}")

        # Verify message is from our authorized group
        sender_data = data.get('senderData', {})
        chat_id = sender_data.get('chatId', '')
        
        if chat_id != AUTHORIZED_GROUP:
            logger.warning(f"Ignoring message from: {chat_id}")
            return jsonify({'status': 'ignored'}), 200

        # Extract sender number for session tracking
        sender = sender_data.get('sender', '')
        
        # Extract message text
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

        logger.info(f"Processing message from {sender} in group {AUTHORIZED_GROUP}: {message}")

        # Check admin commands first
        if message.lower() == '/reset' and sender in ADMIN_NUMBERS:
            reset_bot()
            send_whatsapp_message("🔄 Bot has been reset successfully")
            return jsonify({'status': 'processed'})

        # Check if this is a quality selection
        if sender in user_sessions and user_sessions[sender].get('awaiting_quality'):
            try:
                choice = message.strip()
                option_map = user_sessions[sender].get('option_map', {})
                
                if choice in option_map:
                    quality, format_id = option_map[choice]
                    url = user_sessions[sender]['url']
                    del user_sessions[sender]  # Clear the session
                    
                    if quality == 'mp3':
                        send_whatsapp_message("⬇️ Downloading audio... Please wait...")
                        file_path, title = download_media(url, 'mp3')
                        if file_path:
                            file_size = os.path.getsize(file_path) / (1024 * 1024)
                            if file_size > MAX_FILE_SIZE_MB:
                                send_whatsapp_message(f"❌ File size ({file_size:.1f}MB) exceeds maximum allowed {MAX_FILE_SIZE_MB}MB")
                                os.remove(file_path)
                            else:
                                send_whatsapp_file(file_path, f"🎵 {title}\n👤 Shared by: {sender.split('@')[0]}", is_video=False)
                                os.remove(file_path)
                            os.rmdir(os.path.dirname(file_path))
                        else:
                            send_whatsapp_message("❌ Failed to download audio. Please try again.")
                    else:
                        send_whatsapp_message(f"⬇️ Downloading {quality} quality... Please wait...")
                        file_path, title = download_media(url, quality, format_id)
                        if file_path:
                            file_size = os.path.getsize(file_path) / (1024 * 1024)
                            if file_size > MAX_FILE_SIZE_MB:
                                send_whatsapp_message(f"❌ File size ({file_size:.1f}MB) exceeds maximum allowed {MAX_FILE_SIZE_MB}MB")
                                os.remove(file_path)
                            else:
                                send_whatsapp_file(file_path, f"🎥 {title}\n📏 Quality: {quality}\n👤 Shared by: {sender.split('@')[0]}", is_video=True)
                                os.remove(file_path)
                            os.rmdir(os.path.dirname(file_path))
                        else:
                            send_whatsapp_message("❌ Failed to download media. Please try again.")
                else:
                    send_whatsapp_message("❌ Invalid choice. Please select one of the available options.")
                    # Resend options
                    url = user_sessions[sender]['url']
                    send_quality_options(sender, url)
                return jsonify({'status': 'processed'})
            except Exception as e:
                logger.error(f"Error processing quality choice: {str(e)}")
                send_whatsapp_message("❌ Invalid input. Please try again.")
                return jsonify({'status': 'processed'})

        # Command handling
        if message.lower() in ['hi', 'hello', 'hey', '/start']:
            help_text = """🤖 *Media Download Bot* 🤖

*Supported Platforms:*
- YouTube
- Instagram
- TikTok
- Facebook
- Twitter
- Dailymotion
- Vimeo

*How To Use:*
1. Simply paste any video URL
2. Select your preferred quality
3. Receive your media in the group

*Features:*
- Multiple quality options
- MP3 audio extraction
- Automatic thumbnail preservation
- Fast downloads

*Note:* Maximum file size is 100MB"""
            send_whatsapp_message(help_text)
        
        elif message.lower().startswith(('/help', 'help', 'info')):
            help_text = """ℹ️ *Bot Help Guide* ℹ️

*Available Commands:*
- Just paste any video URL to download
- /help - Show this message

*Supported Platforms:*
YouTube, Instagram, TikTok, Facebook, Twitter, Dailymotion, Vimeo

*Tips:*
- For best quality, select 'Best Available Quality'
- For audio only, select 'MP3 Audio'
- Maximum file size is 100MB"""
            send_whatsapp_message(help_text)
        
        # Check if message is a URL
        elif any(proto in message.lower() for proto in ['http://', 'https://']):
            send_quality_options(sender, message)

        return jsonify({'status': 'processed'})

    except Exception as e:
        logger.error(f"WEBHOOK ERROR: {str(e)}", exc_info=True)
        return jsonify({'status': 'error'}), 500

# ======================
# HEALTH CHECK
# ======================
@app.route('/')
def health_check():
    return jsonify({
        "status": "active",
        "authorized_group": AUTHORIZED_GROUP,
        "instance_id": GREEN_API['idInstance'],
        "timestamp": datetime.now().isoformat(),
        "sessions_active": len(user_sessions)
    })

# ======================
# START SERVER
# ======================
if __name__ == '__main__':
    # Verify cookies file exists
    if not os.path.exists(COOKIES_FILE):
        logger.warning(f"Cookies file not found at: {COOKIES_FILE}")
    else:
        logger.info(f"Using cookies file: {COOKIES_FILE}")
    
    logger.info(f"""
    ============================================
    WhatsApp Group Media Bot READY
    Authorized Group: {AUTHORIZED_GROUP}
    Admin Numbers: {ADMIN_NUMBERS}
    Max File Size: {MAX_FILE_SIZE_MB}MB
    GreenAPI Instance: {GREEN_API['idInstance']}
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
