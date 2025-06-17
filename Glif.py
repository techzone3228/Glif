import os
import tempfile
import yt_dlp
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Configuration
AUTHORIZED_NUMBER = "923190779215"  # Your WhatsApp number
GREEN_API = {
    "idInstance": "7105261536",
    "apiToken": "13a4bbfd70394a1c862c5d709671333fb1717111737a4f7998",
    "apiUrl": "https://7105.api.greenapi.com",
    "mediaUrl": "https://7105.media.greenapi.com"
}

def send_whatsapp_message(text):
    """Send text message via GreenAPI"""
    url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/sendMessage/{GREEN_API['apiToken']}"
    payload = {
        "chatId": f"{AUTHORIZED_NUMBER}@c.us",
        "message": text
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send message: {e}")
        return False

def send_whatsapp_video(file_path, caption):
    """Send video via GreenAPI"""
    url = f"{GREEN_API['mediaUrl']}/waInstance{GREEN_API['idInstance']}/sendFileByUpload/{GREEN_API['apiToken']}"
    try:
        with open(file_path, 'rb') as file:
            files = {'file': (os.path.basename(file_path), file, 'video/mp4')}
            data = {'chatId': f"{AUTHORIZED_NUMBER}@c.us", 'caption': caption}
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            return True
    except Exception as e:
        print(f"Failed to send video: {e}")
        return False

def download_instagram_video(url):
    """Download Instagram video with best quality"""
    temp_dir = tempfile.mkdtemp()
    ydl_opts = {
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'format': 'best',
        'quiet': True,
        'retries': 3,
        'extractor_args': {
            'instagram': {
                'requestor': 'firefox',  # Mimic browser
                'wait': 5,  # Delay between requests
            }
        },
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename, info.get('title', 'Instagram Video')
    except Exception as e:
        print(f"Failed to download video: {e}")
        return None, None

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    data = request.json
    sender = data.get('senderData', {}).get('sender', '')
    
    # Verify sender
    if not sender.endswith(f"{AUTHORIZED_NUMBER}@c.us"):
        return jsonify({'status': 'ignored'}), 200
    
    # Extract message
    message_data = data.get('messageData', {})
    if message_data.get('typeMessage') == 'extendedTextMessage':
        url = message_data.get('extendedTextMessageData', {}).get('text', '').strip()
    else:
        return jsonify({'status': 'unsupported_type'}), 200
    
    # Check if it's an Instagram URL
    if 'instagram.com' not in url:
        return jsonify({'status': 'not_instagram'}), 200
    
    # Process Instagram URL
    send_whatsapp_message("⬇️ Downloading Instagram video...")
    
    # Try download with 3 retries
    for attempt in range(3):
        file_path, title = download_instagram_video(url)
        if file_path:
            caption = f"🎬 {title}" if title else "Instagram Video"
            if send_whatsapp_video(file_path, caption):
                # Clean up
                os.remove(file_path)
                os.rmdir(os.path.dirname(file_path))
                return jsonify({'status': 'success'}), 200
            break
        send_whatsapp_message(f"⚠️ Attempt {attempt + 1} failed. Retrying...")
    
    send_whatsapp_message("❌ Failed to download video after 3 attempts. Instagram may be blocking requests.")
    return jsonify({'status': 'failed'}), 200

if __name__ == '__main__':
    print("Instagram Downloader Ready")
    app.run(host='0.0.0.0', port=8000)
