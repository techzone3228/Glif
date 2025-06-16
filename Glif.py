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

def send_format_options(sender, url):
    """Send available format options to user with numbered choices"""
    formats = get_available_formats(url)
    
    if formats is None or not formats:
        send_whatsapp_message("⚠️ Could not detect formats. Trying best quality...")
        file_path, title = download_media(url)
        if file_path:
            is_video = file_path.endswith(('.mp4', '.mkv', '.webm'))
            send_whatsapp_file(file_path, f"📦 {title}", is_video=is_video)
            os.remove(file_path)
            os.rmdir(os.path.dirname(file_path))
        else:
            send_whatsapp_message("❌ Failed to download media. Please try again.")
        return

    # Group formats by quality
    video_formats = []
    audio_formats = []
    
    for f in formats:
        if f.get('acodec') != 'none' and f.get('vcodec') != 'none':
            # Video format
            res = f.get('height', 0)
            video_formats.append({
                'id': f['format_id'],
                'quality': f"{res}p",
                'type': 'video'
            })
        elif f.get('acodec') != 'none':
            # Audio format
            abr = f.get('abr', 0)
            audio_formats.append({
                'id': f['format_id'],
                'quality': f"{abr}kbps",
                'type': 'audio'
            })

    # Remove duplicate qualities
    seen_video = set()
    unique_video = []
    for v in sorted(video_formats, key=lambda x: int(x['quality'].replace('p', '')), reverse=True):
        if v['quality'] not in seen_video:
            seen_video.add(v['quality'])
            unique_video.append(v)
    
    seen_audio = set()
    unique_audio = []
    for a in sorted(audio_formats, key=lambda x: int(x['quality'].replace('kbps', '')), reverse=True):
        if a['quality'] not in seen_audio:
            seen_audio.add(a['quality'])
            unique_audio.append(a)

    # Prepare options text
    options_text = "📺 Available Download Options:\n\n"
    options_list = []
    
    # Add video options
    options_text += "🎥 Video Formats:\n"
    for i, fmt in enumerate(unique_video, 1):
        options_text += f"{i}. {fmt['quality']}\n"
        options_list.append({
            'number': str(i),
            'id': fmt['id'],
            'type': 'video'
        })
    
    # Add audio options
    options_text += "\n🎧 Audio Formats:\n"
    audio_start = len(unique_video) + 1
    for i, fmt in enumerate(unique_audio, audio_start):
        options_text += f"{i}. {fmt['quality']} (Audio Only)\n"
        options_list.append({
            'number': str(i),
            'id': fmt['id'],
            'type': 'audio'
        })
    
    # Add best quality option
    best_num = len(options_list) + 1
    options_text += f"\n{best_num}. Best Available Quality (Auto)\n"
    options_list.append({
        'number': str(best_num),
        'id': None,
        'type': 'best'
    })
    
    options_text += "\n🔢 Reply with the number of your choice"
    
    # Store the options and URL in user session
    user_sessions[sender] = {
        'url': url,
        'awaiting_choice': True,
        'options': {opt['number']: opt for opt in options_list}
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
        if sender in user_sessions and user_sessions[sender].get('awaiting_choice'):
            url = user_sessions[sender]['url']
            options = user_sessions[sender]['options']
            del user_sessions[sender]  # Clear the session
            
            if message in options:
                choice = options[message]
                if choice['type'] == 'best':
                    send_whatsapp_message("⬇️ Downloading best quality...")
                    file_path, title = download_media(url)
                else:
                    send_whatsapp_message(f"⬇️ Downloading {choice['type']} {choice['quality'] if 'quality' in choice else ''}...")
                    file_path, title = download_media(url, choice['id'])
                
                if file_path:
                    is_video = file_path.endswith(('.mp4', '.mkv', '.webm'))
                    send_whatsapp_file(file_path, f"📦 {title}", is_video=is_video)
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
