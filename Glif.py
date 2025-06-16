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

# YouTube Resolution options with guaranteed audio
YT_RESOLUTIONS = {
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

def download_youtube_media(url, choice):
    """Download YouTube media with selected option (original logic)"""
    resolution = YT_RESOLUTIONS.get(choice, YT_RESOLUTIONS['6'])
    
    # Handle MP3 download
    if choice == '7':
        try:
            temp_dir = tempfile.mkdtemp()
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'cookiefile': COOKIES_FILE,
                'quiet': True
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                mp3_file = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
                
                if os.path.exists(mp3_file):
                    return mp3_file, info.get('title', 'audio')
            return None, None
            
        except Exception as e:
            logger.error(f"Error downloading MP3: {str(e)}")
            return None, None
        finally:
            # Clean up temp directory if empty
            try:
                if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                    os.rmdir(temp_dir)
            except Exception as e:
                logger.warning(f"Error cleaning temp dir: {str(e)}")
    
    # Handle video downloads
    try:
        temp_dir = tempfile.mkdtemp()
        
        # First try normal download
        ydl_opts = {
            'format': resolution['format'],
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'cookiefile': COOKIES_FILE,
            'merge_output_format': 'mp4',
            'postprocessors': [
                {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
                {'key': 'FFmpegMetadata'},
                {'key': 'EmbedThumbnail'}
            ],
            'quiet': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if check_audio(filename):
                new_filename = f"{os.path.splitext(filename)[0]}_{resolution['name']}.mp4"
                os.rename(filename, new_filename)
                return new_filename, info.get('title', 'video')
        
        # If no audio, force separate download and merge
        logger.warning("Audio missing - forcing separate audio/video download...")
        
        # Download video only
        video_format = "bestvideo[ext=mp4]"
        if resolution['name'][-1] == 'p' and resolution['name'][:-1].isdigit():
            video_format += f"[height<={resolution['name'][:-1]}]"
            
        video_path = os.path.join(temp_dir, "video.mp4")
        subprocess.run([
            "yt-dlp",
            "-f", video_format,
            "-o", video_path,
            url,
            "--cookies", COOKIES_FILE,
            "--quiet"
        ], check=True)
        
        # Download audio only
        audio_path = os.path.join(temp_dir, "audio.m4a")
        subprocess.run([
            "yt-dlp",
            "-f", "bestaudio[ext=m4a]",
            "-o", audio_path,
            url,
            "--cookies", COOKIES_FILE,
            "--quiet"
        ], check=True)
        
        # Merge them
        final_path = os.path.join(temp_dir, "final.mp4")
        subprocess.run([
            "ffmpeg",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-strict", "experimental",
            final_path,
            "-y",
            "-loglevel", "error"
        ], check=True)
        
        # Clean up
        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(audio_path):
            os.remove(audio_path)
            
        return final_path, info.get('title', 'video')
            
    except Exception as e:
        logger.error(f"Error downloading video: {str(e)}")
        return None, None
    finally:
        # Clean up temp directory if empty
        try:
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except Exception as e:
            logger.warning(f"Error cleaning temp dir: {str(e)}")

def download_social_media(url, format_id):
    """Download media from other social platforms with audio merging"""
    try:
        temp_dir = tempfile.mkdtemp()
        
        # First try normal download
        ydl_opts = {
            'format': format_id,
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'postprocessors': [
                {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
                {'key': 'FFmpegMetadata'}
            ],
            'quiet': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if check_audio(filename):
                new_filename = f"{os.path.splitext(filename)[0]}.mp4"
                os.rename(filename, new_filename)
                return new_filename, info.get('title', 'video')
        
        # If no audio, try separate download and merge
        logger.warning("Audio missing - forcing separate audio/video download...")
        
        # Download video only
        video_path = os.path.join(temp_dir, "video.mp4")
        subprocess.run([
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]",
            "-o", video_path,
            url,
            "--quiet"
        ], check=True)
        
        # Download audio only
        audio_path = os.path.join(temp_dir, "audio.m4a")
        subprocess.run([
            "yt-dlp",
            "-f", "bestaudio[ext=m4a]",
            "-o", audio_path,
            url,
            "--quiet"
        ], check=True)
        
        # Merge them
        final_path = os.path.join(temp_dir, "final.mp4")
        subprocess.run([
            "ffmpeg",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-strict", "experimental",
            final_path,
            "-y",
            "-loglevel", "error"
        ], check=True)
        
        # Clean up
        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(audio_path):
            os.remove(audio_path)
            
        return final_path, info.get('title', 'video')
            
    except Exception as e:
        logger.error(f"Error downloading media: {str(e)}")
        return None, None
    finally:
        # Clean up temp directory if empty
        try:
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except Exception as e:
            logger.warning(f"Error cleaning temp dir: {str(e)}")

def get_social_media_formats(url):
    """Get available formats for social media URLs"""
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            
            formats = []
            if 'formats' in info:
                for f in info['formats']:
                    if f.get('vcodec') != 'none' and f.get('height'):
                        formats.append({
                            'height': f['height'],
                            'ext': f['ext'],
                            'format_id': f['format_id'],
                            'acodec': f.get('acodec', 'none')
                        })
                    elif f.get('acodec') != 'none':
                        formats.append({
                            'height': 0,
                            'ext': f['ext'],
                            'format_id': f['format_id'],
                            'acodec': f.get('acodec', 'none')
                        })
            
            # Remove duplicates and sort
            unique_formats = []
            seen = set()
            for f in sorted(formats, key=lambda x: x['height'], reverse=True):
                key = (f['height'], f['ext'])
                if key not in seen:
                    seen.add(key)
                    unique_formats.append(f)
            
            return {
                'title': info.get('title', 'video'),
                'formats': unique_formats
            }
    except Exception as e:
        logger.error(f"Error getting formats: {str(e)}")
        return None

def send_youtube_options(sender, url):
    """Send YouTube resolution options to user"""
    options_text = "📺 Please select YouTube download option:\n\n"
    options_text += "1. 144p (Lowest video quality)\n"
    options_text += "2. 360p (Low video quality)\n"
    options_text += "3. 480p (Medium video quality)\n"
    options_text += "4. 720p (HD video quality)\n"
    options_text += "5. 1080p (Full HD video quality)\n"
    options_text += "6. Best video quality\n"
    options_text += "7. MP3 (Audio only)\n\n"
    options_text += "Reply with the number (1-7) of your choice"
    
    # Store the URL in user session
    user_sessions[sender] = {
        'url': url,
        'awaiting_yt_resolution': True
    }
    
    send_whatsapp_message(options_text)

def send_social_media_options(sender, url, formats):
    """Send social media format options to user"""
    options_text = "📺 Available Download Options:\n\n"
    
    # Add video options
    video_options = [f for f in formats if f['height'] > 0]
    if video_options:
        options_text += "🎥 Video Qualities:\n"
        for i, fmt in enumerate(video_options, 1):
            options_text += f"{i}. {fmt['height']}p ({fmt['ext']})\n"
    
    # Add audio option
    audio_options = [f for f in formats if f['height'] == 0]
    if audio_options:
        options_text += "\n🔊 Audio Only:\n"
        options_text += f"{len(video_options)+1}. MP3 Audio\n"
    
    options_text += f"\n{len(formats)+1}. Best Quality Available\n"
    options_text += "\nReply with the number of your choice"
    
    # Store the formats in user session
    user_sessions[sender] = {
        'url': url,
        'formats': formats,
        'awaiting_sm_format': True
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

        # Check if this is a YouTube resolution selection
        if sender in user_sessions and user_sessions[sender].get('awaiting_yt_resolution'):
            try:
                choice = message.strip()
                if choice in YT_RESOLUTIONS:
                    # Get the stored URL
                    url = user_sessions[sender]['url']
                    del user_sessions[sender]  # Clear the session
                    
                    if choice == '7':
                        send_whatsapp_message("⬇️ Downloading MP3 audio...")
                        file_path, title = download_youtube_media(url, choice)
                        if file_path:
                            send_whatsapp_file(file_path, f"🎵 {title}", is_video=False)
                            os.remove(file_path)
                            os.rmdir(os.path.dirname(file_path))
                        else:
                            send_whatsapp_message("❌ Failed to download audio. Please try again.")
                    else:
                        send_whatsapp_message(f"⬇️ Downloading {YT_RESOLUTIONS[choice]['name']} quality...")
                        file_path, title = download_youtube_media(url, choice)
                        if file_path:
                            send_whatsapp_file(file_path, f"🎥 {title}\nQuality: {YT_RESOLUTIONS[choice]['name']}", is_video=True)
                            os.remove(file_path)
                            os.rmdir(os.path.dirname(file_path))
                        else:
                            send_whatsapp_message("❌ Failed to download media. Please try again.")
                else:
                    send_whatsapp_message("❌ Invalid choice. Please select a number between 1-7.")
                    send_youtube_options(sender, url)
                return jsonify({'status': 'processed'})
            except Exception as e:
                logger.error(f"Error processing YouTube resolution choice: {str(e)}")
                send_whatsapp_message("❌ Invalid input. Please try again.")
                return jsonify({'status': 'processed'})

        # Check if this is a social media format selection
        elif sender in user_sessions and user_sessions[sender].get('awaiting_sm_format'):
            try:
                choice = message.strip()
                formats = user_sessions[sender]['formats']
                url = user_sessions[sender]['url']
                
                # Clear the session
                del user_sessions[sender]
                
                # Handle best quality selection
                if choice == str(len(formats)+1):
                    format_id = 'bestvideo+bestaudio/best'
                    quality = "Best Quality"
                # Handle audio selection
                elif choice == str(len([f for f in formats if f['height'] > 0])+1):
                    format_id = 'bestaudio/best'
                    quality = "MP3 Audio"
                # Handle video quality selection
                elif choice.isdigit() and 1 <= int(choice) <= len(formats):
                    selected = formats[int(choice)-1]
                    if selected['height'] > 0:
                        format_id = selected['format_id']
                        quality = f"{selected['height']}p"
                    else:
                        format_id = 'bestaudio/best'
                        quality = "MP3 Audio"
                else:
                    send_whatsapp_message("❌ Invalid choice. Please try again with a valid number.")
                    return jsonify({'status': 'processed'})
                
                send_whatsapp_message(f"⬇️ Downloading {quality}...")
                file_path, title = download_social_media(url, format_id)
                
                if file_path:
                    if quality == "MP3 Audio":
                        send_whatsapp_file(file_path, f"🎵 {title}", is_video=False)
                    else:
                        send_whatsapp_file(file_path, f"🎥 {title}\nQuality: {quality}", is_video=True)
                    # Clean up
                    os.remove(file_path)
                    os.rmdir(os.path.dirname(file_path))
                else:
                    send_whatsapp_message("❌ Failed to download media. Please try again.")
                
                return jsonify({'status': 'processed'})
            except Exception as e:
                logger.error(f"Error processing format choice: {str(e)}")
                send_whatsapp_message("❌ Invalid input. Please try again.")
                return jsonify({'status': 'processed'})

        # Command handling
        if message.lower() in ['hi', 'hello', 'hey']:
            help_text = """👋 Hi! Here's what I can do:
- Send any YouTube URL to download with quality options
- Send other video URLs (Instagram, Twitter, etc.) to download
/glif [prompt] - Generate custom thumbnail
/help - Show this message"""
            send_whatsapp_message(help_text)
        
        elif message.lower().startswith(('/help', 'help', 'info')):
            help_text = """ℹ️ Available Commands:
- Send YouTube URL for quality options
- Send other video URLs to download
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
        
        # URL detection and processing
        elif re.match(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', message):
            url = message.strip()
            
            # Check if it's a YouTube URL
            if 'youtube.com' in url or 'youtu.be' in url:
                send_whatsapp_message("🔍 Detected YouTube link")
                send_youtube_options(sender, url)
            else:
                send_whatsapp_message("🔍 Analyzing URL...")
                
                # Get available formats for other social media
                format_info = get_social_media_formats(url)
                if not format_info:
                    send_whatsapp_message("❌ Unsupported URL or private content. Please try another link.")
                    return jsonify({'status': 'processed'})
                
                # Send format options to user
                send_social_media_options(
                    sender,
                    url,
                    format_info['formats']
                )
        
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
