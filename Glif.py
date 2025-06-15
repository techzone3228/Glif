from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
from datetime import datetime
import yt_dlp
import os
import tempfile
import re
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
COOKIES_FILE = "cookies.txt"  # Path to your cookies file

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
SUPPORTED_DOMAINS = [
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "twitter.com",
    "x.com"
]

# Resolution options with WhatsApp-compatible formats
RESOLUTIONS = {
    '144p': {'format': '160', 'height': 144, 'vcodec': 'mp4v'},
    '360p': {'format': '18', 'height': 360, 'vcodec': 'mp4v'},
    '480p': {'format': '135', 'height': 480, 'vcodec': 'mp4v'},
    '720p': {'format': '22', 'height': 720, 'vcodec': 'mp4v'},
    '1080p': {'format': '137+140', 'height': 1080, 'vcodec': 'mp4v'},
    'best': {'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', 'vcodec': 'mp4v'}
}

# User session data to track resolution selection
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
                'file': (os.path.basename(file_path), file, 'video/mp4' if is_video else 'image/jpeg')
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

def convert_to_whatsapp_compatible(input_path, output_path):
    """Convert video to WhatsApp compatible format using ffmpeg"""
    try:
        command = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', 'libx264',
            '-profile:v', 'baseline',
            '-level', '3.0',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', 'faststart',
            '-y',
            output_path
        ]
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg conversion failed: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error in video conversion: {str(e)}")
        return False

def download_media(url, resolution='best'):
    """Download media with specified resolution and ensure WhatsApp compatibility"""
    try:
        temp_dir = tempfile.mkdtemp()
        resolution_config = RESOLUTIONS.get(resolution, RESOLUTIONS['best'])
        
        ydl_opts = {
            'format': resolution_config['format'],
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'quiet': True,
            'cookiefile': COOKIES_FILE,
            'extract_flat': False,
            'retries': 10,
            'fragment_retries': 10,
            'ignoreerrors': True,
            'no_warnings': False,
            'socket_timeout': 30,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4'
            }],
            'extractor_args': {
                'youtube': {
                    'skip': ['dash', 'hls']
                }
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise ValueError("Failed to extract video info")
                
            original_filename = ydl.prepare_filename(info)
            if not os.path.exists(original_filename):
                raise FileNotFoundError("Downloaded file not found")
            
            # Convert to WhatsApp compatible format
            final_filename = os.path.join(temp_dir, f"whatsapp_{os.path.basename(original_filename)}")
            if not convert_to_whatsapp_compatible(original_filename, final_filename):
                logger.warning("Using original file as fallback")
                final_filename = original_filename
                
            return final_filename, info.get('title', 'video')
            
    except Exception as e:
        logger.error(f"Media download failed: {str(e)}")
        return None, None
    finally:
        # Clean up temp directory if empty
        try:
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except:
            pass

def send_resolution_options(sender):
    """Send resolution options to user"""
    options_text = "📺 Please select video resolution:\n\n"
    options_text += "1. 144p (Lowest quality)\n"
    options_text += "2. 360p (Low quality)\n"
    options_text += "3. 480p (Medium quality)\n"
    options_text += "4. 720p (HD quality)\n"
    options_text += "5. 1080p (Full HD)\n"
    options_text += "6. Best available quality\n\n"
    options_text += "Reply with the number (1-6) of your choice"
    
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
                choice = int(message)
                if 1 <= choice <= 6:
                    resolutions = ['144p', '360p', '480p', '720p', '1080p', 'best']
                    selected_resolution = resolutions[choice - 1]
                    
                    # Get the stored URL
                    url = user_sessions[sender]['url']
                    del user_sessions[sender]  # Clear the session
                    
                    send_whatsapp_message(f"⬇️ Downloading {selected_resolution} quality... (may take a few minutes)")
                    file_path, title = download_media(url, selected_resolution)
                    
                    if file_path and title:
                        send_whatsapp_file(file_path, f"🎥 {title}\nQuality: {selected_resolution}", is_video=True)
                        os.remove(file_path)
                        os.rmdir(os.path.dirname(file_path))
                    else:
                        send_whatsapp_message("❌ Failed to download media. Please try again later.")
                else:
                    send_whatsapp_message("❌ Invalid choice. Please select a number between 1-6.")
                    send_resolution_options(sender)
                return jsonify({'status': 'processed'})
            except ValueError:
                send_whatsapp_message("❌ Please enter a number between 1-6 to select resolution.")
                send_resolution_options(sender)
                return jsonify({'status': 'processed'})

        # Command handling
        if message.lower() in ['hi', 'hello', 'hey']:
            help_text = """👋 Hi! Here's what I can do:
/yt [YouTube URL] - Download YouTube video (choose quality)
/tt [TikTok URL] - Download TikTok video
/tw [Twitter URL] - Download Twitter video
/thumbnail [prompt] - Generate custom thumbnail
/help - Show this message"""
            send_whatsapp_message(help_text)
        
        elif message.lower().startswith(('/help', 'help', 'info')):
            help_text = """ℹ️ Available Commands:
/yt [URL] - Download YouTube video with quality options
/tt [URL] - Download TikTok video
/tw [URL] - Download Twitter video
/thumbnail [prompt] - Generate thumbnail
/help - Show this message"""
            send_whatsapp_message(help_text)
        
        elif message.lower().startswith('/thumbnail '):
            prompt = message[11:].strip()
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
            if any(domain in url for domain in ['youtube.com', 'youtu.be']):
                # Store the URL and ask for resolution
                user_sessions[sender] = {
                    'url': url,
                    'awaiting_resolution': True
                }
                send_resolution_options(sender)
            else:
                send_whatsapp_message("⚠️ Please provide a valid YouTube URL (e.g., /yt https://youtube.com/watch?v=...)")
        
        elif any(message.lower().startswith(cmd) for cmd in ['/tt ', '/tw ']):
            command, url = message.split(' ', 1)
            if any(domain in url for domain in ['tiktok.com', 'twitter.com', 'x.com']):
                send_whatsapp_message("⬇️ Downloading media... (this may take a while)")
                file_path, title = download_media(url)
                if file_path and title:
                    platform = {
                        '/tt': 'TikTok',
                        '/tw': 'Twitter'
                    }[command]
                    send_whatsapp_file(file_path, f"🎥 {platform} Video: {title}", is_video=True)
                    os.remove(file_path)
                    os.rmdir(os.path.dirname(file_path))
                else:
                    send_whatsapp_message("❌ Failed to download media. Please try again or check the URL.")
            else:
                send_whatsapp_message("⚠️ Please provide a valid TikTok or Twitter URL")
        
        elif len(message) > 3:  # Fallback to thumbnail generation
            send_whatsapp_message("🔄 Generating your thumbnail... (20-30 seconds)")
            result = generate_thumbnail(message)
            if result['status'] == 'success':
                response = requests.get(result['image_url'])
                temp_file = os.path.join(tempfile.gettempdir(), "thumbnail.jpg")
                with open(temp_file, 'wb') as f:
                    f.write(response.content)
                send_whatsapp_file(temp_file, f"🎨 Thumbnail for: {message}")
                send_whatsapp_message(f"🔗 Direct URL: {result['image_url']}")
                os.remove(temp_file)
            else:
                send_whatsapp_message("❌ Failed to generate. Please try different keywords.")

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
