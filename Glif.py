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

def is_youtube_url(url):
    """Check if URL is from YouTube"""
    return 'youtube.com' in url or 'youtu.be' in url

def get_available_qualities(url):
    """Check available qualities for YouTube videos"""
    if is_youtube_url(url):
        return get_youtube_qualities(url)
    else:
        return get_other_platform_qualities(url)

def get_youtube_qualities(url):
    """Get YouTube-specific quality options"""
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
        logger.error(f"Error checking YouTube qualities: {str(e)}")
        return {'best': 'bestvideo+bestaudio/best', 'mp3': 'bestaudio/best'}

def get_other_platform_qualities(url):
    """Get quality options for non-YouTube platforms"""
    try:
        ydl_opts = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            if not formats:
                return None

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
            for v in sorted(video_formats, key=lambda x: float(x['quality'].replace('p', '')), reverse=True):
                if v['quality'] not in seen_video:
                    seen_video.add(v['quality'])
                    unique_video.append(v)
            
            seen_audio = set()
            unique_audio = []
            for a in sorted(audio_formats, key=lambda x: float(x['quality'].replace('kbps', '')), reverse=True):
                if a['quality'] not in seen_audio:
                    seen_audio.add(a['quality'])
                    unique_audio.append(a)

            # Prepare quality map
            quality_map = {}
            for fmt in unique_video:
                quality_map[fmt['quality']] = fmt['id']
            
            for fmt in unique_audio:
                quality_map[f"{fmt['quality']} (Audio)"] = fmt['id']
            
            # Add best quality option
            quality_map['best'] = 'bestvideo+bestaudio/best'
            quality_map['mp3'] = 'bestaudio/best'
            
            return quality_map
            
    except Exception as e:
        logger.error(f"Error getting other platform formats: {str(e)}")
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
            # For YouTube, use our standard format selection
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
                # For other platforms, use the specific format_id
                ydl_opts['format'] = format_id if format_id else 'bestvideo+bestaudio/best'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
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
    """Check available qualities and send options to user"""
    send_whatsapp_message("🔍 Checking available video qualities...")
    
    quality_map = get_available_qualities(url)
    if not quality_map:
        send_whatsapp_message("❌ Could not determine available qualities. Trying default options...")
        quality_map = {'best': 'bestvideo+bestaudio/best', 'mp3': 'bestaudio/best'}
    
    # Store available qualities in user session with format_ids
    user_sessions[sender] = {
        'url': url,
        'quality_map': quality_map,
        'awaiting_quality': True
    }
    
    # Build options message
    options_text = "📺 Available download options:\n\n"
    option_number = 1
    option_map = {}
    
    for qual in quality_map.keys():
        if qual == 'mp3' or '(Audio)' in qual:
            options_text += f"{option_number}. MP3 (Audio only)\n"
            option_map[str(option_number)] = ('mp3', None)
        elif qual == 'best':
            options_text += f"{option_number}. Best available quality\n"
            option_map[str(option_number)] = ('best', quality_map[qual])
        else:
            options_text += f"{option_number}. {qual}\n"
            option_map[str(option_number)] = (qual, quality_map[qual])
        option_number += 1
    
    options_text += "\nReply with the number of your choice"
    
    # Store the option mapping in user session
    user_sessions[sender]['option_map'] = option_map
    
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

        # Check if this is a quality selection
        if sender in user_sessions and user_sessions[sender].get('awaiting_quality'):
            try:
                choice = message.strip()
                option_map = user_sessions[sender].get('option_map', {})
                
                if choice in option_map:
                    quality, format_id = option_map[choice]
                    url = user_sessions[sender]['url']
                    del user_sessions[sender]  # Clear the session
                    
                    if quality == 'mp3' or '(Audio)' in quality:
                        send_whatsapp_message("⬇️ Downloading MP3 audio...")
                        file_path, title = download_media(url, 'mp3')
                        if file_path:
                            send_whatsapp_file(file_path, f"🎵 {title}", is_video=False)
                            os.remove(file_path)
                            os.rmdir(os.path.dirname(file_path))
                        else:
                            send_whatsapp_message("❌ Failed to download audio. Please try again.")
                    else:
                        send_whatsapp_message(f"⬇️ Downloading {quality} quality...")
                        file_path, title = download_media(url, quality, format_id)
                        if file_path:
                            send_whatsapp_file(file_path, f"🎥 {title}\nQuality: {quality}", is_video=True)
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
        if message.lower() in ['hi', 'hello', 'hey']:
            help_text = """👋 Hi! Here's what I can do:
Paste any video URL (YouTube, Instagram, TikTok, Facebook, etc.) to download
/glif [prompt] - Generate custom thumbnail
/help - Show this message"""
            send_whatsapp_message(help_text)
        
        elif message.lower().startswith(('/help', 'help', 'info')):
            help_text = """ℹ️ Available Commands:
Paste any video URL (YouTube, Instagram, TikTok, Facebook, etc.) to download
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
