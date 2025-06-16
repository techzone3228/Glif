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

# GLIF Configuration
GLIF_ID = "cm0zceq2a00023f114o6hti7w"
GLIF_TOKENS = [
    "glif_a4ef6d3aa5d8575ea8448b29e293919a42a6869143fcbfc32f2e4a7dbe53199a",
    "glif_51d216db54438b777c4170cd8913d628ff0af09789ed5dbcbd718fa6c6968bb1",
    "glif_c9dc66b31537b5a423446bbdead5dc2dbd73dc1f4a5c47a9b77328abcbc7b755",
    "glif_f5a55ee6d767b79f2f3af01c276ec53d14475eace7cabf34b22f8e5968f3fef5",
    "glif_c3a7fd4779b59f59c08d17d4a7db46beefa3e9e49a9ebc4921ecaca35c556ab7",
    "glif_b31fdc2c9a7aaac0ec69d5f59bf05ccea0c5786990ef06b79a1d7db8e37ba317"
]

# Supported domains for downloader
SUPPORTED_DOMAINS = {
    'youtube': ['youtube.com', 'youtu.be'],
    'facebook': ['facebook.com', 'fb.watch']
}

# Resolution mapping with improved format selection
RESOLUTION_MAP = {
    '144p': {'format': 'bestvideo[height<=144]+bestaudio/best', 'height': 144},
    '360p': {'format': 'bestvideo[height<=360]+bestaudio/best', 'height': 360},
    '480p': {'format': 'bestvideo[height<=480]+bestaudio/best', 'height': 480},
    '720p': {'format': 'bestvideo[height<=720]+bestaudio/best', 'height': 720},
    '1080p': {'format': 'bestvideo[height<=1080]+bestaudio/best', 'height': 1080},
    'best': {'format': 'bestvideo+bestaudio/best', 'height': float('inf')},
    'mp3': {'format': 'bestaudio/best', 'ext': 'mp3'}
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

def generate_thumbnail(prompt):
    """Generate thumbnail using GLIF API"""
    prompt = prompt[:100]  # Limit prompt length
    for token in GLIF_TOKENS:
        try:
            response = requests.post(
                f"https://simple-api.glif.app/{GLIF_ID}",
                headers={"Authorization": f"Bearer {token}"},
                json={"prompt": prompt, "style": "youtube_trending"},
                timeout=30
            )
            data = response.json()
            
            # Check all possible response formats
            for key in ["output", "image_url", "url"]:
                if key in data and isinstance(data[key], str) and data[key].startswith('http'):
                    logger.info(f"Generated thumbnail using token {token[-6:]}")
                    return {'status': 'success', 'image_url': data[key]}
        except Exception as e:
            logger.warning(f"GLIF token {token[-6:]} failed: {str(e)}")
    return {'status': 'error'}

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

def get_available_resolutions(url, platform):
    """Check available resolutions for a video"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_generic_extractor': True,
            'cookiefile': COOKIES_FILE if platform == 'youtube' else None
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or 'formats' not in info:
                return None
            
            # Get all available formats
            formats = info.get('formats', [])
            
            # Extract unique heights
            heights = sorted({f.get('height', 0) for f in formats if f.get('vcodec') != 'none'})
            
            # Map to standard resolutions
            available = set()
            for h in heights:
                if h >= 1080:
                    available.add('1080p')
                if h >= 720:
                    available.add('720p')
                if h >= 480:
                    available.add('480p')
                if h >= 360:
                    available.add('360p')
                if h >= 144:
                    available.add('144p')
            
            # Always include best and mp3 options
            available.add('best')
            available.add('mp3')
            
            # Return in standard order
            resolution_order = ['144p', '360p', '480p', '720p', '1080p', 'best', 'mp3']
            return [res for res in resolution_order if res in available]
            
    except Exception as e:
        logger.error(f"Error checking available resolutions: {str(e)}")
        return ['144p', '360p', '480p', '720p', '1080p', 'best', 'mp3']  # Fallback options

def download_media(url, resolution, platform='youtube'):
    """Download media with selected resolution"""
    if resolution not in RESOLUTION_MAP:
        return None, None
    
    format_spec = RESOLUTION_MAP[resolution]['format']
    
    try:
        temp_dir = tempfile.mkdtemp()
        ydl_opts = {
            'format': format_spec,
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
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
        
        # Add cookies for YouTube if available
        if platform == 'youtube' and os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
        
        # Special handling for audio only
        if resolution == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                if resolution == 'mp3':
                    mp3_file = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
                    if os.path.exists(mp3_file):
                        return mp3_file, info.get('title', 'audio')
                else:
                    if check_audio(filename):
                        new_filename = f"{os.path.splitext(filename)[0]}_{resolution}.mp4"
                        os.rename(filename, new_filename)
                        return new_filename, info.get('title', 'video')
                        
            except yt_dlp.utils.DownloadError as e:
                if "Requested format is not available" in str(e):
                    logger.warning(f"Format {resolution} not available, trying best quality")
                    ydl_opts['format'] = 'bestvideo[height<={}]+bestaudio/best'.format(
                        RESOLUTION_MAP[resolution]['height']
                    )
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info)
                    if check_audio(filename):
                        new_filename = f"{os.path.splitext(filename)[0]}_{resolution}.mp4"
                        os.rename(filename, new_filename)
                        return new_filename, info.get('title', 'video')
                raise
                
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

def send_resolution_options(sender, url, platform):
    """Check available resolutions and send options to user"""
    send_whatsapp_message("🔍 Checking available video qualities...")
    
    resolutions = get_available_resolutions(url, platform)
    if not resolutions:
        send_whatsapp_message("❌ Could not determine available qualities. Trying default options...")
        resolutions = ['144p', '360p', '480p', '720p', '1080p', 'best', 'mp3']
    
    # Store available resolutions in user session
    user_sessions[sender] = {
        'url': url,
        'available_resolutions': resolutions,
        'awaiting_resolution': True,
        'platform': platform
    }
    
    # Build options message
    options_text = "📺 Available download options:\n\n"
    option_number = 1
    resolution_map = {}
    
    for res in resolutions:
        if res == 'mp3':
            options_text += f"{option_number}. MP3 (Audio only)\n"
            resolution_map[str(option_number)] = 'mp3'
        elif res == 'best':
            options_text += f"{option_number}. Best available quality\n"
            resolution_map[str(option_number)] = 'best'
        else:
            options_text += f"{option_number}. {res}\n"
            resolution_map[str(option_number)] = res
        option_number += 1
    
    options_text += "\nReply with the number of your choice"
    
    # Store the mapping in user session
    user_sessions[sender]['resolution_map'] = resolution_map
    
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

        # Check if this is a resolution selection
        if sender in user_sessions and user_sessions[sender].get('awaiting_resolution'):
            try:
                choice = message.strip()
                resolution_map = user_sessions[sender].get('resolution_map', {})
                
                if choice in resolution_map:
                    resolution = resolution_map[choice]
                    url = user_sessions[sender]['url']
                    platform = user_sessions[sender].get('platform', 'youtube')
                    del user_sessions[sender]  # Clear the session
                    
                    if resolution == 'mp3':
                        send_whatsapp_message("⬇️ Downloading MP3 audio...")
                        file_path, title = download_media(url, resolution, platform)
                        if file_path:
                            send_whatsapp_file(file_path, f"🎵 {title}", is_video=False)
                            os.remove(file_path)
                            os.rmdir(os.path.dirname(file_path))
                        else:
                            send_whatsapp_message("❌ Failed to download audio. Please try again.")
                    else:
                        send_whatsapp_message(f"⬇️ Downloading {resolution} quality...")
                        file_path, title = download_media(url, resolution, platform)
                        if file_path:
                            send_whatsapp_file(file_path, f"🎥 {title}\nQuality: {resolution}", is_video=True)
                            os.remove(file_path)
                            os.rmdir(os.path.dirname(file_path))
                        else:
                            send_whatsapp_message("❌ Failed to download media. Please try again.")
                else:
                    send_whatsapp_message("❌ Invalid choice. Please select one of the available options.")
                    # Resend options
                    url = user_sessions[sender]['url']
                    platform = user_sessions[sender].get('platform', 'youtube')
                    send_resolution_options(sender, url, platform)
                return jsonify({'status': 'processed'})
            except Exception as e:
                logger.error(f"Error processing resolution choice: {str(e)}")
                send_whatsapp_message("❌ Invalid input. Please try again.")
                return jsonify({'status': 'processed'})

        # Command handling
        if message.lower() in ['hi', 'hello', 'hey']:
            help_text = """👋 Hi! Here's what I can do:
/yt [YouTube URL] - Download YouTube video/audio
/fb [Facebook URL] - Download Facebook video
/glif [prompt] - Generate custom thumbnail
/help - Show this message"""
            send_whatsapp_message(help_text)
        
        elif message.lower().startswith(('/help', 'help', 'info')):
            help_text = """ℹ️ Available Commands:
/yt [URL] - Download YouTube video/audio (choose quality)
/fb [URL] - Download Facebook video (choose quality)
/glif [prompt] - Generate thumbnail
/help - Show this message"""
            send_whatsapp_message(help_text)
        
        elif message.lower().startswith('/glif '):
            prompt = message[6:].strip()
            if prompt:
                send_whatsapp_message("🔄 Generating your thumbnail... (20-30 seconds)")
                result = generate_thumbnail(prompt)
                if result['status'] == 'success':
                    # Download the image first
                    response = requests.get(result['image_url'])
                    temp_file = os.path.join(tempfile.gettempdir(), "thumbnail.jpg")
                    with open(temp_file, 'wb') as f:
                        f.write(response.content)
                    # Send as file with caption
                    send_whatsapp_file(temp_file, f"🎨 Thumbnail for: {prompt}")
                    send_whatsapp_message(f"🔗 Direct URL: {result['image_url']}")
                    os.remove(temp_file)
                else:
                    send_whatsapp_message("❌ Failed to generate. Please try different keywords.")
        
        elif message.lower().startswith('/yt '):
            url = message[4:].strip()
            if any(domain in url for domain in SUPPORTED_DOMAINS['youtube']):
                # Check available resolutions and send options
                send_resolution_options(sender, url, 'youtube')
            else:
                send_whatsapp_message("⚠️ Please provide a valid YouTube URL")
        
        elif message.lower().startswith('/fb '):
            url = message[4:].strip()
            if any(domain in url for domain in SUPPORTED_DOMAINS['facebook']):
                # Check available resolutions and send options
                send_resolution_options(sender, url, 'facebook')
            else:
                send_whatsapp_message("⚠️ Please provide a valid Facebook URL")

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
