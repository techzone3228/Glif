from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
import os
import time

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# GreenAPI Configuration
INSTANCE_ID = "7105258364"
API_TOKEN = "9f9e1a1a2611446baed68fd648dba823d34e655958e54b28bb"
BASE_API_URL = "https://7105.api.greenapi.com"
BASE_MEDIA_URL = "https://7105.media.greenapi.com"
AUTHORIZED_NUMBER = "923401809397"  # Only respond to this number
BOT_NUMBER = "923247220362"  # Your bot's number

# Temporary directory for downloads
TEMP_DIR = "temp_downloads"
os.makedirs(TEMP_DIR, exist_ok=True)

@app.route('/')
def health_check():
    """Endpoint for Koyeb health checks"""
    return jsonify({"status": "ready", "service": "WhatsApp Media Bot"})

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    try:
        logger.info(f"\n{'='*50}\nIncoming request: {request.method}")
        
        if request.method == 'GET':
            return jsonify({"status": "active"}), 200

        data = request.json
        if not data:
            logger.error("No data received")
            return jsonify({'status': 'error', 'message': 'No data received'}), 400

        logger.info(f"Request data: {data}")

        # Process incoming messages
        if data.get('event_type') == 'message_received':
            message_data = data.get('data', {})
            sender_number = message_data.get('from', '').split('@')[0]
            message_text = message_data.get('body', '').strip()
            
            # Only respond to authorized number
            if sender_number != AUTHORIZED_NUMBER:
                logger.info(f"Ignoring message from unauthorized number: {sender_number}")
                return jsonify({'status': 'ignored'})
            
            logger.info(f"Processing message from {sender_number}: {message_text}")
            
            # Check if message looks like a URL (simplified check)
            if message_text.startswith(('http://', 'https://')):
                # Download and send back the media
                process_media_url(message_text, sender_number)
            else:
                send_message(sender_number, "Please send a direct download link to an image or video file.")
            
        return jsonify({'status': 'processed'})
    
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

def process_media_url(url, recipient_number, retries=3):
    """Download media from URL and send back to user"""
    try:
        send_message(recipient_number, "🔍 Downloading your media file...")
        
        # Download the file
        filename = os.path.join(TEMP_DIR, f"downloaded_{int(time.time())}")
        
        for attempt in range(retries):
            try:
                response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()
                
                # Determine content type from headers
                content_type = response.headers.get('content-type', '')
                
                # Set appropriate file extension
                if 'image' in content_type:
                    filename += '.jpg'  # Default to jpg for images
                elif 'video' in content_type:
                    filename += '.mp4'  # Default to mp4 for videos
                else:
                    # If content type not clear, try to guess from URL
                    if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                        filename += '.jpg'
                    elif any(url.lower().endswith(ext) for ext in ['.mp4', '.mov', '.webm']):
                        filename += '.mp4'
                    else:
                        filename += '.bin'  # Fallback extension
                
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                logger.info(f"Successfully downloaded file: {filename}")
                break
            except Exception as e:
                if attempt == retries - 1:
                    raise
                time.sleep(2)
        
        # Determine media type and MIME type
        if 'image' in content_type:
            media_type = 'image'
            mime_type = content_type or 'image/jpeg'
        elif 'video' in content_type:
            media_type = 'video'
            mime_type = content_type or 'video/mp4'
        else:
            # Fallback based on file extension
            if filename.lower().endswith(('.mp4', '.mov', '.webm')):
                media_type = 'video'
                mime_type = 'video/mp4'
            else:
                media_type = 'image'
                mime_type = 'image/jpeg'
        
        # Send the file back
        send_file(recipient_number, filename, media_type, mime_type)
        
        # Clean up
        if os.path.exists(filename):
            os.remove(filename)
        
    except Exception as e:
        logger.error(f"Error processing media URL: {str(e)}")
        send_message(recipient_number, f"❌ Error: {str(e)}")

def send_message(recipient_number, text, retries=3):
    """Send WhatsApp message"""
    chat_id = f"{recipient_number}@c.us"
    url = f"{BASE_API_URL}/waInstance{INSTANCE_ID}/sendMessage/{API_TOKEN}"
    
    for attempt in range(retries):
        try:
            response = requests.post(
                url,
                json={
                    'chatId': chat_id,
                    'message': text
                },
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"Message sent to {recipient_number}")
            return response.json()
        except Exception as e:
            logger.warning(f"Failed to send message (attempt {attempt + 1}): {str(e)}")
            if attempt == retries - 1:
                raise
            time.sleep(2)

def send_file(recipient_number, file_path, media_type, mime_type, caption="Here's your media file", retries=3):
    """Send media file through WhatsApp"""
    chat_id = f"{recipient_number}@c.us"
    filename = os.path.basename(file_path)
    url = f"{BASE_MEDIA_URL}/waInstance{INSTANCE_ID}/sendFileByUpload/{API_TOKEN}"
    
    for attempt in range(retries):
        try:
            with open(file_path, 'rb') as file:
                files = {
                    'file': (filename, file, mime_type)
                }
                payload = {
                    'chatId': chat_id,
                    'caption': caption,
                    'fileName': filename
                }
                
                response = requests.post(url, data=payload, files=files, timeout=30)
                response.raise_for_status()
                logger.info(f"{media_type.capitalize()} sent to {recipient_number}")
                return response.json()
        except Exception as e:
            logger.warning(f"Failed to send {media_type} (attempt {attempt + 1}): {str(e)}")
            if attempt == retries - 1:
                raise
            time.sleep(2)

if __name__ == '__main__':
    logger.info("Starting WhatsApp Media Bot...")
    serve(app, host='0.0.0.0', port=8000)
