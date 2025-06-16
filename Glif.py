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
COOKIES_FILE = "cookies.txt"  # Make sure this file exists in your root directory

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

def get_available_formats(url):
    """Get available formats for a URL"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    # Add cookies for YouTube if available
    if 'youtube.com' in url or 'youtu.be' in url:
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
            logger.info("Using cookies.txt for YouTube authentication")
        else:
            logger.warning("YouTube cookies file not found, may encounter restrictions")
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
            video_formats = [f for f in formats if f.get('vcodec') != 'none']
            
            # Sort video formats by resolution
            video_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
            
            return {
                'title': info.get('title', 'Untitled'),
                'thumbnail': info.get('thumbnail', ''),
                'audio_formats': audio_formats,
                'video_formats': video_formats,
                'extractor': info.get('extractor', 'generic')
            }
        except Exception as e:
            logger.error(f"Error getting formats: {str(e)}")
            return None

def download_media(url, format_id=None, audio_only=False):
    """Download media with selected format"""
    temp_dir = tempfile.mkdtemp()
    try:
        ydl_opts = {
            'format': f'{format_id}' if format_id else 'bestvideo+bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [
                {'key': 'FFmpegMetadata'},
                {'key': 'EmbedThumbnail'}
            ],
        }
        
        # Add cookies for YouTube if available
        if ('youtube.com' in url or 'youtu.be' in url) and os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
            logger.info("Using cookies.txt for YouTube download")
        
        if audio_only:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'].append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if audio_only:
                filename = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
            
            if os.path.exists(filename):
                return filename, info.get('title', 'media')
        return None, None
        
    except Exception as e:
        logger.error(f"Error downloading media: {str(e)}")
        return None, None
    finally:
        # Clean up temp directory if empty
        try:
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except:
            pass

def send_format_options(sender, url):
    """Send available format options to user"""
    formats_info = get_available_formats(url)
    if not formats_info:
        send_whatsapp_message("❌ Could not get available formats for this URL")
        return False
    
    user_sessions[sender] = {
        'url': url,
        'title': formats_info['title'],
        'awaiting_format': True
    }
    
    options_text = f"📺 Available formats for: {formats_info['title']}\n\n"
    
    # Video options
    if formats_info['video_formats']:
        options_text += "🎥 Video Formats:\n"
        for i, fmt in enumerate(formats_info['video_formats'][:5]):  # Show top 5 video formats
            res = fmt.get('height', '?')
            fps = fmt.get('fps', 0)
            options_text += f"{i+1}. {res}p{f' ({fps}fps)' if fps > 30 else ''}\n"
    
    # Audio options
    if formats_info['audio_formats']:
        options_text += "\n🎵 Audio Formats:\n"
        audio_start = len(formats_info['video_formats'][:5]) + 1
        for i, fmt in enumerate(formats_info['audio_formats'][:3]):  # Show top 3 audio formats
            abr = fmt.get('abr', 0)
            options_text += f"{audio_start + i}. MP3 ({abr}kbps)\n"
    
    options_text += "\nReply with the number of your choice"
    send_whatsapp_message(options_text)
    return True

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
            try:
                choice = message.strip()
                url = user_sessions[sender]['url']
                title = user_sessions[sender]['title']
                del user_sessions[sender]  # Clear the session
                
                formats_info = get_available_formats(url)
                if not formats_info:
                    send_whatsapp_message("❌ Could not get formats. Please try again.")
                    return jsonify({'status': 'processed'})
                
                # Determine if audio or video was selected
                video_count = len(formats_info['video_formats'][:5])
                audio_only = int(choice) > video_count if choice.isdigit() else False
                
                send_whatsapp_message("⬇️ Downloading your media...")
                
                if audio_only:
                    # Audio download
                    file_path, _ = download_media(url, audio_only=True)
                    if file_path:
                        send_whatsapp_file(file_path, f"🎵 {title}", is_video=False)
                        os.remove(file_path)
                    else:
                        send_whatsapp_message("❌ Failed to download audio. Please try again.")
                else:
                    # Video download
                    format_id = formats_info['video_formats'][int(choice)-1]['format_id']
                    file_path, _ = download_media(url, format_id=format_id)
                    if file_path:
                        send_whatsapp_file(file_path, f"🎥 {title}", is_video=True)
                        os.remove(file_path)
                    else:
                        send_whatsapp_message("❌ Failed to download video. Please try again.")
                
                return jsonify({'status': 'processed'})
            except Exception as e:
                logger.error(f"Error processing format choice: {str(e)}")
                send_whatsapp_message("❌ Invalid selection. Please try again.")
                return jsonify({'status': 'processed'})

        # Command handling
        if message.lower() in ['hi', 'hello', 'hey']:
            help_text = """👋 Hi! Here's what I can do:
- Send any video URL to download (YouTube, Instagram, Facebook, etc.)
/thumbnail [prompt] - Generate custom thumbnail
/help - Show this message"""
            send_whatsapp_message(help_text)
        
        elif message.lower().startswith(('/help', 'help', 'info')):
            help_text = """ℹ️ Available Commands:
- Just send any video URL to download
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
        
        # URL detection
        elif re.match(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', message):
            url = message.strip()
            send_whatsapp_message("🔍 Checking available formats...")
            if not send_format_options(sender, url):
                send_whatsapp_message("❌ Unsupported URL or private content")
        
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
