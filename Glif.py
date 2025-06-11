from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
from datetime import datetime
import yt_dlp
import os
import tempfile

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
USER_STATES = {}  # To track user selection state

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
            
            for key in ["output", "image_url", "url"]:
                if key in data and isinstance(data[key], str) and data[key].startswith('http'):
                    logger.info(f"Generated thumbnail using token {token[-6:]}")
                    return {'status': 'success', 'image_url': data[key]}
        except Exception as e:
            logger.warning(f"GLIF token {token[-6:]} failed: {str(e)}")
    return {'status': 'error'}

def get_video_formats(url):
    """Get available video formats"""
    ydl_opts = {
        'quiet': True,
        'cookiefile': COOKIES_FILE,
        'extract_flat': False,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = []
        
        for f in info.get('formats', []):
            if f.get('vcodec') != 'none' and f.get('acodec') != 'none':  # Video+audio
                resolution = f.get('height', 0)
                fps = f.get('fps', 0)
                ext = f.get('ext', 'mp4')
                filesize = f.get('filesize_approx', f.get('filesize', 0))
                
                if filesize:
                    size_mb = round(filesize / (1024 * 1024), 1)
                    size_str = f"{size_mb}MB"
                else:
                    size_str = "Unknown size"
                
                format_id = f.get('format_id')
                format_note = f.get('format_note', '')
                
                if resolution:
                    if fps and fps > 30:
                        quality = f"{resolution}p{fps}"
                    else:
                        quality = f"{resolution}p"
                    
                    if format_note:
                        quality = f"{quality} ({format_note})"
                    
                    formats.append({
                        'id': format_id,
                        'quality': quality,
                        'ext': ext,
                        'size': size_str,
                        'fps': fps
                    })
        
        # Sort by resolution then fps
        formats.sort(key=lambda x: (-x.get('height', 0), -x.get('fps', 0)))
        return formats[:10]  # Return top 10 formats

def download_video(url, format_id):
    """Download video in selected format"""
    try:
        temp_dir = tempfile.mkdtemp()
        
        ydl_opts = {
            'format': format_id,
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'quiet': True,
            'cookiefile': COOKIES_FILE,
            'retries': 10,
            'fragment_retries': 10,
            'socket_timeout': 30,
            'noplaylist': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if not os.path.exists(filename):
                raise FileNotFoundError("Downloaded file not found")
                
            return filename
            
    except Exception as e:
        logger.error(f"Video download failed: {str(e)}")
        return None
    finally:
        # Clean up temp directory if empty
        try:
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except:
            pass

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

        # Check if user is responding to quality selection
        if sender in USER_STATES and USER_STATES[sender].get('awaiting_quality'):
            if message.isdigit():
                choice = int(message)
                state = USER_STATES[sender]
                if 1 <= choice <= len(state['formats']):
                    selected_format = state['formats'][choice-1]
                    send_whatsapp_message(f"⬇️ Downloading {selected_format['quality']} quality...")
                    
                    file_path = download_video(state['url'], selected_format['id'])
                    if file_path:
                        send_whatsapp_file(file_path, f"🎥 YouTube Video ({selected_format['quality']})", is_video=True)
                        os.remove(file_path)
                    else:
                        send_whatsapp_message("❌ Failed to download video. Please try again.")
                else:
                    send_whatsapp_message("⚠️ Invalid selection. Please try again.")
                
                # Clear user state
                del USER_STATES[sender]
                return jsonify({'status': 'processed'})
            else:
                send_whatsapp_message("⚠️ Please enter a number from the list.")
                return jsonify({'status': 'processed'})

        # Command handling
        if message.lower() in ['hi', 'hello', 'hey']:
            help_text = """👋 Hi! Here's what I can do:
/yt [YouTube URL] - Download YouTube video
/thumbnail [prompt] - Generate custom thumbnail
/help - Show this message"""
            send_whatsapp_message(help_text)
        
        elif message.lower().startswith(('/help', 'help', 'info')):
            help_text = """ℹ️ Available Commands:
/yt [URL] - Download YouTube video (with quality selection)
/thumbnail [prompt] - Generate thumbnail
/help - Show this message"""
            send_whatsapp_message(help_text)
        
        elif message.lower().startswith('/thumbnail '):
            prompt = message[11:].strip()
            if prompt:
                send_whatsapp_message("🔄 Generating your thumbnail... (20-30 seconds)")
                result = generate_thumbnail(prompt)
                if result['status'] == 'success':
                    response = requests.get(result['image_url'])
                    temp_file = os.path.join(tempfile.gettempdir(), "thumbnail.jpg")
                    with open(temp_file, 'wb') as f:
                        f.write(response.content)
                    send_whatsapp_file(temp_file, f"🎨 Thumbnail for: {prompt}")
                    send_whatsapp_message(f"🔗 Direct URL: {result['image_url']}")
                    os.remove(temp_file)
                else:
                    send_whatsapp_message("❌ Failed to generate. Please try different keywords.")
        
        elif message.lower().startswith('/yt '):
            url = message[4:].strip()
            if 'youtube.com' in url or 'youtu.be' in url:
                send_whatsapp_message("🔍 Checking available video qualities...")
                formats = get_video_formats(url)
                
                if formats:
                    # Store user state
                    USER_STATES[sender] = {
                        'awaiting_quality': True,
                        'url': url,
                        'formats': formats
                    }
                    
                    # Send quality options
                    quality_list = "\n".join(
                        f"{i+1}. {f['quality']} ({f['ext'].upper()}, {f['size']})"
                        for i, f in enumerate(formats)
                    )
                    send_whatsapp_message(
                        f"📹 Available Qualities:\n{quality_list}\n\n"
                        "Reply with the number of your preferred quality:"
                    )
                else:
                    send_whatsapp_message("❌ Could not retrieve video formats. The video may be restricted.")
            else:
                send_whatsapp_message("⚠️ Please provide a valid YouTube URL")
        
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
    WhatsApp YouTube Downloader READY
    ONLY responding to: {AUTHORIZED_NUMBER}
    GreenAPI Instance: {GREEN_API['idInstance']}
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
