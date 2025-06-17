from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
from datetime import datetime
import yt_dlp
import os
import tempfile
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
COOKIES_FILE = "igcookies.txt"  # Changed to match the downloaded file
COOKIES_URL = "https://cdn.indexer.eu.org/-1002243289687/125/1750191676/f7ea84a9b1c8dc029c99a473d69bd234ea5103b2158d09a48ad2d160cecbb02d"

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
    """Download the Instagram cookies file if it doesn't exist"""
    if not os.path.exists(COOKIES_FILE):
        try:
            logger.info("Downloading Instagram cookies file...")
            response = requests.get(COOKIES_URL)
            response.raise_for_status()
            
            with open(COOKIES_FILE, 'wb') as f:
                f.write(response.content)
                
            logger.info("Successfully downloaded Instagram cookies")
            return True
        except Exception as e:
            logger.error(f"Failed to download cookies: {str(e)}")
            return False
    return True

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
    """Send file with caption"""
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

def download_instagram_video(url):
    """Download Instagram video in best quality with cookie authentication"""
    try:
        # Ensure cookies file exists
        if not download_cookies_file():
            return None, None
            
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, 'video.mp4')
        
        ydl_opts = {
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'format': 'best',
            'cookiefile': COOKIES_FILE,
            'extractor_args': {
                'instagram': {
                    'requestor': 'firefox',
                    'wait': 5,
                }
            },
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True,
            'throttledratelimit': 50,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Instagram video')
            
            # Verify file was downloaded
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path, title
            else:
                return None, None
                
    except yt_dlp.utils.DownloadError as e:
        if 'login required' in str(e).lower():
            logger.error("Instagram requires login - cookies may be invalid")
        else:
            logger.error(f"Download error: {str(e)}")
        return None, None
    except Exception as e:
        logger.error(f"Error downloading Instagram video: {str(e)}")
        return None, None
    finally:
        # Clean up temp directory if empty
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

        # Check if message is an Instagram URL
        if 'instagram.com' in message.lower():
            send_whatsapp_message("⬇️ Downloading Instagram video (this may take a moment)...")
            
            # Download the video
            file_path, title = download_instagram_video(message)
            
            if file_path:
                # Send the video
                if send_whatsapp_file(file_path, f"🎥 {title}"):
                    # Clean up
                    os.remove(file_path)
                    os.rmdir(os.path.dirname(file_path))
                    send_whatsapp_message("✅ Video downloaded successfully!")
                else:
                    send_whatsapp_message("❌ Failed to send video. Please try again.")
            else:
                send_whatsapp_message("❌ Failed to download video. Instagram may be blocking requests or cookies are invalid.")
        else:
            send_whatsapp_message("ℹ️ Please send me an Instagram video URL to download it")

        return jsonify({'status': 'processed'})

    except Exception as e:
        logger.error(f"WEBHOOK ERROR: {str(e)}", exc_info=True)
        return jsonify({'status': 'error'}), 500

# ======================
# START SERVER
# ======================
if __name__ == '__main__':
    # Download cookies file if needed
    if download_cookies_file():
        logger.info("✅ Instagram cookies file ready")
    else:
        logger.warning("❌ Instagram cookies file not available - downloads may fail")
    
    logger.info(f"""
    ============================================
    Instagram Video Downloader READY
    ONLY responding to: {AUTHORIZED_NUMBER}
    GreenAPI Instance: {GREEN_API['idInstance']}
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
