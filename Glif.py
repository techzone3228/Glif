from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
from datetime import datetime
import yt_dlp
import os
import tempfile
import subprocess

app = Flask(__name__)

# ======================
# CONFIGURATION
# ======================
GREEN_API = {
    "idInstance": "7105258364",
    "apiToken": "9f9e1a1a2611446baed68fd648dba823d34e655958e54b28bb",
    "apiUrl": "https://7105.api.greenapi.com",
    "mediaUrl": "https://7105.media.greenapi.com"
}
AUTHORIZED_NUMBER = "923401809397"
COOKIES_FILE = "cookies.txt"

# Fallback resolution options when format detection fails
FALLBACK_RESOLUTIONS = {
    '1': {'name': '144p', 'format': '160'},
    '2': {'name': '360p', 'format': '18'},
    '3': {'name': '480p', 'format': '135'},
    '4': {'name': '720p', 'format': '22'},
    '5': {'name': '1080p', 'format': 'bestvideo[height<=1080]+bestaudio'},
    '6': {'name': 'Best', 'format': 'bestvideo+bestaudio'},
    '7': {'name': 'MP3', 'format': 'bestaudio/best', 'ext': 'mp3'}
}

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
    """Send text message to authorized number"""
    url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/sendMessage/{GREEN_API['apiToken']}"
    payload = {
        "chatId": f"{AUTHORIZED_NUMBER}@c.us",
        "message": text
    }
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"Message sent: {text[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {str(e)}")
        return False

def send_whatsapp_file(file_path, caption, is_video=False):
    """Send file (video or image) with caption"""
    try:
        url = f"{GREEN_API['mediaUrl']}/waInstance{GREEN_API['idInstance']}/sendFileByUpload/{GREEN_API['apiToken']}"
        
        with open(file_path, 'rb') as file:
            files = {
                'file': (os.path.basename(file_path), file, 'video/mp4' if is_video else 'audio/mpeg' if file_path.endswith('.mp3') else 'image/jpeg')
            }
            data = {
                'chatId': f"{AUTHORIZED_NUMBER}@c.us",
                'caption': caption
            }
            
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            logger.info(f"File sent with caption: {caption[:50]}...")
            return True
            
    except Exception as e:
        logger.error(f"File upload failed: {str(e)}")
        return False

def get_available_formats(url):
    """Get available formats for the media"""
    try:
        ydl_opts = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            return formats
    except Exception as e:
        logger.error(f"Error getting formats: {str(e)}")
        return None

def download_media(url, format_id=None):
    """Download media with selected format"""
    try:
        temp_dir = tempfile.mkdtemp()
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            'writethumbnail': True,
            'postprocessors': [
                {'key': 'FFmpegMetadata'},
                {'key': 'EmbedThumbnail'}
            ],
        }

        if format_id:
            ydl_opts['format'] = format_id
        else:
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
            ydl_opts['merge_output_format'] = 'mp4'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Find the actual downloaded file
            base_name = os.path.splitext(filename)[0]
            for f in os.listdir(temp_dir):
                if f.startswith(os.path.basename(base_name)):
                    actual_file = os.path.join(temp_dir, f)
                    return actual_file, info.get('title', 'media')
            
            return filename, info.get('title', 'media')
            
    except Exception as e:
        logger.error(f"Error downloading media: {str(e)}")
        return None, None
    finally:
        # Clean up other files in temp directory except the downloaded file
        pass

def send_fallback_options(sender, url):
    """Send fallback resolution options when format detection fails"""
    options_text = "📺 Default Download Options (automatic detection failed):\n\n"
    for key, res in FALLBACK_RESOLUTIONS.items():
        options_text += f"{key}. {res['name']}\n"
    
    options_text += "\n🔢 Reply with the number (1-7) of your choice"
    
    # Store the URL in user session
    user_sessions[sender] = {
        'url': url,
        'awaiting_fallback': True
    }
    
    send_whatsapp_message(options_text)

def send_format_options(sender, url):
    """Send available format options to user"""
    formats = get_available_formats(url)
    
    if formats is None:  # Error occurred during format detection
        send_whatsapp_message("⚠️ Could not detect formats. Using fallback options...")
        send_fallback_options(sender, url)
        return

    if not formats:  # No formats found
        send_whatsapp_message("⚠️ No formats found. Using fallback options...")
        send_fallback_options(sender, url)
        return

    # Group formats by quality
    video_formats = {}
    audio_formats = {}
    
    for f in formats:
        if f.get('acodec') != 'none' and f.get('vcodec') != 'none':
            # Video format
            res = f.get('height', 0)
            if res not in video_formats:
                video_formats[res] = f['format_id']
        elif f.get('acodec') != 'none':
            # Audio format
            abr = f.get('abr', 0)
            if abr not in audio_formats:
                audio_formats[abr] = f['format_id']

    # Prepare options text
    options_text = "📺 Available Download Options:\n\n"
    options_text += "🎥 Video Formats:\n"
    for res, fmt_id in sorted(video_formats.items(), reverse=True):
        options_text += f"- {res}p (ID: {fmt_id})\n"
    
    options_text += "\n🎧 Audio Formats:\n"
    for abr, fmt_id in sorted(audio_formats.items(), reverse=True):
        options_text += f"- {abr}kbps (ID: {fmt_id})\n"
    
    options_text += "\n🔢 Reply with the format ID of your choice"
    options_text += "\n⚡ Or reply 'best' for automatic best quality"
    
    # Store the URL in user session
    user_sessions[sender] = {
        'url': url,
        'awaiting_format': True
    }
    
    send_whatsapp_message(options_text)

# ======================
# WEBHOOK HANDLER
# ======================
@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.json
        logger.info(f"RAW WEBHOOK DATA:\n{data}")

        # Verify sender
        sender = data.get('senderData', {}).get('sender', '')
        if not sender.endswith(f"{AUTHORIZED_NUMBER}@c.us"):
            logger.warning(f"Ignoring message from: {sender}")
            return jsonify({'status': 'ignored'}), 200

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

        logger.info(f"PROCESSING MESSAGE FROM {AUTHORIZED_NUMBER}: {message}")

        # Check if this is a format selection
        if sender in user_sessions and user_sessions[sender].get('awaiting_format'):
            url = user_sessions[sender]['url']
            del user_sessions[sender]  # Clear the session
            
            if message.lower() == 'best':
                format_id = None
                send_whatsapp_message("⬇️ Downloading best quality...")
            else:
                format_id = message.strip()
                send_whatsapp_message(f"⬇️ Downloading format {format_id}...")
            
            file_path, title = download_media(url, format_id)
            if file_path:
                is_video = file_path.endswith(('.mp4', '.mkv', '.webm'))
                send_whatsapp_file(file_path, f"📦 {title}", is_video=is_video)
                os.remove(file_path)
                os.rmdir(os.path.dirname(file_path))
            else:
                send_whatsapp_message("❌ Failed to download media. Please try again.")
            return jsonify({'status': 'processed'})

        # Check if this is a fallback resolution selection
        if sender in user_sessions and user_sessions[sender].get('awaiting_fallback'):
            url = user_sessions[sender]['url']
            choice = message.strip()
            del user_sessions[sender]  # Clear the session
            
            if choice in FALLBACK_RESOLUTIONS:
                resolution = FALLBACK_RESOLUTIONS[choice]
                send_whatsapp_message(f"⬇️ Downloading {resolution['name']} quality...")
                
                if choice == '7':  # MP3 option
                    file_path, title = download_media(url, resolution['format'])
                    if file_path:
                        send_whatsapp_file(file_path, f"🎵 {title}", is_video=False)
                        os.remove(file_path)
                        os.rmdir(os.path.dirname(file_path))
                    else:
                        send_whatsapp_message("❌ Failed to download audio. Please try again.")
                else:
                    file_path, title = download_media(url, resolution['format'])
                    if file_path:
                        send_whatsapp_file(file_path, f"🎥 {title}\nQuality: {resolution['name']}", is_video=True)
                        os.remove(file_path)
                        os.rmdir(os.path.dirname(file_path))
                    else:
                        send_whatsapp_message("❌ Failed to download media. Please try again.")
            else:
                send_whatsapp_message("❌ Invalid choice. Please try again.")
            return jsonify({'status': 'processed'})

        # Check if message contains a URL
        if any(proto in message.lower() for proto in ['http://', 'https://']):
            send_whatsapp_message("🔍 Analyzing URL...")
            send_format_options(sender, message)
            return jsonify({'status': 'processed'})

        # Command handling
        if message.lower() in ['hi', 'hello', 'hey']:
            help_text = """👋 Hi! Here's what I can do:
- Send any video URL to download
- I support 1000+ sites including YouTube, Instagram, Twitter, etc.
- I'll show you available quality options"""
            send_whatsapp_message(help_text)
            return jsonify({'status': 'processed'})
        
        # Default response
        send_whatsapp_message("📌 Please send me a video URL to download")
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
        "authorized_number": AUTHORIZED_NUMBER,
        "instance_id": GREEN_API['idInstance'],
        "timestamp": datetime.now().isoformat()
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
    WhatsApp Media Bot READY
    ONLY responding to: {AUTHORIZED_NUMBER}
    GreenAPI Instance: {GREEN_API['idInstance']}
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
