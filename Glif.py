from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
import time
from datetime import datetime

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# GreenAPI Configuration
ID_INSTANCE = "7105242995"
API_TOKEN = "d8822c5bc02d4b00b72455cc64abd11ad672072fbe5d4bf9a2"
API_URL = "https://7105.api.greenapi.com"
AUTHORIZED_NUMBER = "923401809397"

# GLIF Configuration
GLIF_ID = "cm0zceq2a00023f114o6hti7w"
API_TOKENS = [
    "glif_a4ef6d3aa5d8575ea8448b29e293919a42a6869143fcbfc32f2e4a7dbe53199a",
    "glif_51d216db54438b777c4170cd8913d628ff0af09789ed5dbcbd718fa6c6968bb1",
    "glif_c9dc66b31537b5a423446bbdead5dc2dbd73dc1f4a5c47a9b77328abcbc7b755",
    "glif_f5a55ee6d767b79f2f3af01c276ec53d14475eace7cabf34b22f8e5968f3fef5",
    "glif_c3a7fd4779b59f59c08d17d4a7db46beefa3e9e49a9ebc4921ecaca35c556ab7",
    "glif_b31fdc2c9a7aaac0ec69d5f59bf05ccea0c5786990ef06b79a1d7db8e37ba317"
]

@app.route('/')
def health_check():
    logger.info("Health check endpoint hit")
    return jsonify({"status": "ready", "timestamp": str(datetime.now())})

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        logger.info(f"\n{'='*50}\nIncoming webhook request at {datetime.now()}")
        
        # Log raw request data
        raw_data = request.json
        logger.info(f"Raw request data: {raw_data}")
        
        if not raw_data:
            logger.error("Empty request received")
            return jsonify({'status': 'error', 'message': 'No data received', 'timestamp': str(datetime.now())}), 400

        # Extract message details with error handling
        sender_data = raw_data.get('senderData', {})
        message_data = raw_data.get('messageData', {})
        
        phone = sender_data.get('sender', '').split('@')[0]
        message = message_data.get('extendedTextMessageData', {}).get('text', '').strip().lower()
        
        logger.info(f"Extracted data - Phone: {phone}, Message: {message}")

        # Verify sender
        if phone != AUTHORIZED_NUMBER:
            logger.warning(f"Unauthorized access attempt from: {phone}")
            return jsonify({'status': 'unauthorized', 'timestamp': str(datetime.now())}), 403

        logger.info(f"Processing message from authorized number: {phone}")

        # Command handling
        if message in ['hi', 'hello', 'hey']:
            logger.info("Greeting command detected")
            send_message(phone, "👋 Hi! Send me any video topic to generate a thumbnail!")
            return jsonify({'status': 'success'})
            
        elif message in ['help', 'info']:
            logger.info("Help command detected")
            send_message(phone, "ℹ️ Just send me a video topic (e.g. 'cooking tutorial') and I'll create a thumbnail!")
            return jsonify({'status': 'success'})
            
        # Thumbnail generation
        elif len(message) > 3:
            logger.info(f"Thumbnail generation requested for: '{message}'")
            send_message(phone, "🔄 Generating your thumbnail... (20-30 seconds)")
            
            for idx, token in enumerate(API_TOKENS, 1):
                logger.info(f"Attempting GLIF API with token {idx}/{len(API_TOKENS)}")
                result = generate_thumbnail(message, token)
                
                if result.get('status') == 'success':
                    logger.info(f"Thumbnail generated successfully: {result['image_url']}")
                    send_image(phone, result['image_url'], f"🎨 Thumbnail for: {message}")
                    send_message(phone, f"🔗 Direct URL: {result['image_url']}")
                    return jsonify({'status': 'success'})
                else:
                    logger.warning(f"GLIF API attempt {idx} failed")
            
            logger.error("All GLIF API attempts failed")
            send_message(phone, "❌ Failed to generate. Please try different keywords.")

        return jsonify({'status': 'ignored', 'reason': 'No matching command', 'timestamp': str(datetime.now())})
    
    except Exception as e:
        logger.critical(f"Unhandled exception: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e),
            'timestamp': str(datetime.now())
        }), 500

def send_message(phone, text, retries=3):
    """Send WhatsApp message with detailed logging"""
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Attempt {attempt} to send message to {phone}")
            url = f"{API_URL}/waInstance{ID_INSTANCE}/SendMessage/{API_TOKEN}"
            payload = {
                "chatId": f"{phone}@c.us",
                "message": text
            }
            
            logger.debug(f"Request payload: {payload}")
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info(f"Message sent successfully to {phone}")
            logger.debug(f"API response: {response.text}")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Attempt {attempt} failed: {str(e)}")
            if attempt < retries:
                time.sleep(2)
    
    logger.error(f"All {retries} attempts failed for {phone}")
    return None

def send_image(phone, url, caption, retries=3):
    """Send WhatsApp image with detailed logging"""
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Attempt {attempt} to send image to {phone}")
            
            # Upload file
            upload_url = f"{API_URL}/waInstance{ID_INSTANCE}/UploadFile/{API_TOKEN}"
            logger.debug(f"Uploading file from URL: {url}")
            upload_response = requests.post(upload_url, json={"url": url})
            upload_response.raise_for_status()
            file_id = upload_response.json().get('idFile')
            
            if not file_id:
                raise ValueError("No file ID in upload response")
            
            logger.info(f"File uploaded successfully. ID: {file_id}")
            
            # Send file
            send_url = f"{API_URL}/waInstance{ID_INSTANCE}/SendFileByUpload/{API_TOKEN}"
            payload = {
                "chatId": f"{phone}@c.us",
                "caption": caption,
                "fileId": file_id
            }
            
            logger.debug(f"Sending file with payload: {payload}")
            response = requests.post(send_url, json=payload, timeout=20)
            response.raise_for_status()
            
            logger.info(f"Image sent successfully to {phone}")
            logger.debug(f"API response: {response.text}")
            return response.json()
            
        except Exception as e:
            logger.error(f"Attempt {attempt} failed: {str(e)}")
            if attempt < retries:
                time.sleep(2)
    
    logger.error(f"All {retries} attempts failed for image send")
    return None

def generate_thumbnail(prompt, token, max_length=100):
    """Generate thumbnail with detailed logging"""
    try:
        logger.info(f"Generating thumbnail for: {prompt[:max_length]}")
        
        response = requests.post(
            f"https://simple-api.glif.app/{GLIF_ID}",
            headers={"Authorization": f"Bearer {token}"},
            json={"prompt": prompt[:max_length], "style": "youtube_trending"},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        logger.debug(f"GLIF API raw response: {data}")
        
        # Check all possible response formats
        for key in ["output", "image_url", "url"]:
            if key in data and isinstance(data[key], str) and data[key].startswith('http'):
                logger.info(f"Successfully generated image: {data[key]}")
                return {'status': 'success', 'image_url': data[key]}
        
        logger.warning(f"No valid image URL found in response. Keys: {list(data.keys())}")
        return {'status': 'error'}
        
    except Exception as e:
        logger.error(f"GLIF API error: {str(e)}")
        return {'status': 'error'}

if __name__ == '__main__':
    logger.info("Starting WhatsApp Thumbnail Generator with enhanced logging...")
    serve(app, host='0.0.0.0', port=8000)
