from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
import yt_dlp
import os
import tempfile
import urllib.request

app = Flask(__name__)

# Configuration
GREEN_API = {
    "idInstance": "7105261536",
    "apiToken": "13a4bbfd70394a1c862c5d709671333fb1717111737a4f7998",
    "apiUrl": "https://7105.api.greenapi.com",
    "mediaUrl": "https://7105.media.greenapi.com"
}
AUTHORIZED_NUMBER = "923190779215"
COOKIES_URL = "https://cdn.indexer.eu.org/-1002243289687/125/1750191676/f7ea84a9b1c8dc029c99a473d69bd234ea5103b2158d09a48ad2d160cecbb02d"
COOKIES_FILE = "igcookies.txt"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def download_cookies():
    """Download Instagram cookies file"""
    try:
        urllib.request.urlretrieve(COOKIES_URL, COOKIES_FILE)
        logger.info("Successfully downloaded Instagram cookies")
        return True
    except Exception as e:
        logger.error(f"Failed to download cookies: {str(e)}")
        return False

def send_whatsapp_message(text):
    """Send text message via WhatsApp"""
    url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/sendMessage/{GREEN_API['apiToken']}"
    payload = {"chatId": f"{AUTHORIZED_NUMBER}@c.us", "message": text}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logger.info(f"Message sent: {text[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {str(e)}")
        return False

def send_whatsapp_video(file_path, caption):
    """Send video file via WhatsApp"""
    try:
        url = f"{GREEN_API['mediaUrl']}/waInstance{GREEN_API['idInstance']}/sendFileByUpload/{GREEN_API['apiToken']}"
        with open(file_path, 'rb') as file:
            files = {'file': (os.path.basename(file_path), file, 'video/mp4')}
            data = {'chatId': f"{AUTHORIZED_NUMBER}@c.us", 'caption': caption}
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            logger.info(f"Video sent: {caption[:50]}...")
            return True
    except Exception as e:
        logger.error(f"Failed to send video: {str(e)}")
        return False

def download_instagram_video(url):
    """Download Instagram video using yt-dlp with cookies"""
    temp_dir = tempfile.mkdtemp()
    try:
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'cookiefile': COOKIES_FILE,
            'format': 'best',
            'quiet': True,
            'retries': 3,
            'extractor_args': {
                'instagram': {
                    'requestor': 'firefox',
                    'wait': 5
                }
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename, info.get('title', 'Instagram Video')
            
    except Exception as e:
        logger.error(f"Error downloading video: {str(e)}")
        return None, None

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.json
        sender = data.get('senderData', {}).get('sender', '')
        
        # Verify sender
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
            return jsonify({'status': 'unsupported_type'}), 200

        if not message:
            return jsonify({'status': 'empty_message'}), 200

        logger.info(f"Processing message: {message}")

        # Check if message is an Instagram URL
        if 'instagram.com' in message:
            send_whatsapp_message("⬇️ Downloading Instagram video...")
            
            # Download video
            video_path, title = download_instagram_video(message)
            
            if video_path and os.path.exists(video_path):
                # Send video
                if send_whatsapp_video(video_path, f"🎥 {title}"):
                    # Cleanup
                    os.remove(video_path)
                    os.rmdir(os.path.dirname(video_path))
                else:
                    send_whatsapp_message("❌ Failed to send video. Please try again.")
            else:
                send_whatsapp_message("❌ Failed to download video. Instagram may be blocking requests.")
        
        return jsonify({'status': 'processed'})

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/')
def health_check():
    return jsonify({
        "status": "active",
        "authorized_number": AUTHORIZED_NUMBER,
        "instance_id": GREEN_API['idInstance']
    })

if __name__ == '__main__':
    # Download cookies file if it doesn't exist
    if not os.path.exists(COOKIES_FILE):
        if not download_cookies():
            logger.error("Failed to download cookies - Instagram downloads may fail")
    
    logger.info(f"""
    ============================================
    Instagram Video Downloader READY
    ONLY responding to: {AUTHORIZED_NUMBER}
    GreenAPI Instance: {GREEN_API['idInstance']}
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
