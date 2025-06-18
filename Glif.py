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
AUTHORIZED_NUMBER = "923190779215"
COOKIES_FILE = "igcookies.txt"
COOKIES_DRIVE_URL = "https://drive.google.com/uc?export=download&id=13kNOfYmC8kZEE9Le786ndnZbdPpGBtEX"
USE_COOKIES = True  # Default setting

# ======================
# LOGGING SETUP
# ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def download_cookies_file():
    """Download the Instagram cookies file from Google Drive"""
    try:
        logger.info("Downloading Instagram cookies file from Google Drive...")
        
        # Create a session to handle potential large file warnings
        session = requests.Session()
        response = session.get(COOKIES_DRIVE_URL, stream=True)
        response.raise_for_status()
        
        # Handle Google Drive virus scan warning
        content = response.content
        if b'Google Drive - Virus scan warning' in content:
            confirm = re.search(r'confirm=([^&]+)', response.url)
            if confirm:
                new_url = f"{COOKIES_DRIVE_URL}&confirm={confirm.group(1)}"
                response = session.get(new_url, stream=True)
                response.raise_for_status()
                content = response.content
        
        # Save the file
        with open(COOKIES_FILE, 'wb') as f:
            f.write(content)
            
        logger.info(f"Successfully downloaded cookies file: {COOKIES_FILE}")
        return True
    except Exception as e:
        logger.error(f"Failed to download cookies file: {str(e)}")
        return False

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

def send_whatsapp_file(file_path, caption):
    """Send video file with caption"""
    try:
        url = f"{GREEN_API['mediaUrl']}/waInstance{GREEN_API['idInstance']}/sendFileByUpload/{GREEN_API['apiToken']}"
        
        with open(file_path, 'rb') as file:
            files = {
                'file': (os.path.basename(file_path), file, 'video/mp4')
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

def is_instagram_url(url):
    """Check if URL is from Instagram"""
    return 'instagram.com' in url or 'instagr.am' in url

def download_instagram_video(url):
    """Download Instagram video with best quality"""
    try:
        temp_dir = tempfile.mkdtemp()
        
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'format': 'best',
            'quiet': True,
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True
        }
        
        # Add cookies if enabled and file exists
        if USE_COOKIES and os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
            logger.info("Using cookies for download")
        else:
            logger.info("Downloading without cookies")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if check_audio(filename):
                new_filename = f"{os.path.splitext(filename)[0]}_instagram.mp4"
                os.rename(filename, new_filename)
                return new_filename, info.get('title', 'Instagram Video')
                
        return None, None
        
    except Exception as e:
        logger.error(f"Error downloading Instagram video: {str(e)}")
        return None, None
    finally:
        try:
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except Exception as e:
            logger.warning(f"Error cleaning temp dir: {str(e)}")

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

        # Handle commands
        if message.lower() == '/on':
            global USE_COOKIES
            USE_COOKIES = True
            if os.path.exists(COOKIES_FILE):
                send_whatsapp_message("✅ Cookies enabled and file exists")
            else:
                if download_cookies_file():
                    send_whatsapp_message("✅ Cookies enabled and downloaded successfully")
                else:
                    send_whatsapp_message("⚠️ Cookies enabled but failed to download file. Will try without cookies when needed.")
            return jsonify({'status': 'processed'})
        
        elif message.lower() == '/off':
            USE_COOKIES = False
            send_whatsapp_message("❌ Cookies disabled")
            return jsonify({'status': 'processed'})
        
        elif message.lower() in ['/help', 'help']:
            help_text = """ℹ️ Instagram Video Downloader Help:
            
• Send any Instagram video URL to download it
• /on - Enable cookies for downloading (recommended)
• /off - Disable cookies
• /help - Show this message"""
            send_whatsapp_message(help_text)
            return jsonify({'status': 'processed'})

        # Check if message is an Instagram URL
        if is_instagram_url(message):
            if USE_COOKIES and not os.path.exists(COOKIES_FILE):
                if download_cookies_file():
                    send_whatsapp_message("⬇️ Downloaded cookies file, now downloading video...")
                else:
                    send_whatsapp_message("⚠️ Cookies enabled but file missing, trying without...")
            
            send_whatsapp_message("⬇️ Downloading Instagram video...")
            file_path, title = download_instagram_video(message)
            if file_path:
                send_whatsapp_file(file_path, f"📸 {title}")
                os.remove(file_path)
                os.rmdir(os.path.dirname(file_path))
            else:
                send_whatsapp_message("❌ Failed to download Instagram video. Please make sure:")
                send_whatsapp_message("- The URL is correct and public")
                send_whatsapp_message("- The video isn't private or age-restricted")
                if USE_COOKIES:
                    send_whatsapp_message("- Try disabling cookies with /off if this persists")
        else:
            send_whatsapp_message("This bot only downloads Instagram videos. Please send a valid Instagram video URL or use /help")

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
        "cookies_enabled": USE_COOKIES,
        "cookies_file_exists": os.path.exists(COOKIES_FILE),
        "timestamp": datetime.now().isoformat()
    })

# ======================
# START SERVER
# ======================
if __name__ == '__main__':
    # Download cookies file if enabled and doesn't exist
    if USE_COOKIES and not os.path.exists(COOKIES_FILE):
        if not download_cookies_file():
            logger.warning("Running without cookies file - Instagram downloads may fail")
    
    logger.info(f"""
    ============================================
    Instagram Video Downloader READY
    ONLY responding to: {AUTHORIZED_NUMBER}
    GreenAPI Instance: {GREEN_API['idInstance']}
    Cookies Enabled: {USE_COOKIES}
    Cookies File: {'Present' if os.path.exists(COOKIES_FILE) else 'Missing'}
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
