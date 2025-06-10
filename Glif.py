from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
import time
from datetime import datetime

app = Flask(__name__)

# ======================
# CONFIGURATION (YOUR CREDENTIALS)
# ======================
GREEN_API = {
    "idInstance": "7105258364",
    "apiToken": "9f9e1a1a2611446baed68fd648dba823d34e655958e54b28bb",
    "apiUrl": "https://7105.api.greenapi.com",
    "mediaUrl": "https://7105.media.greenapi.com"
}
AUTHORIZED_NUMBER = "923401809397"  # ONLY responds to this number

# ALL GLIF TOKENS (COMPLETE SET)
GLIF_TOKENS = [
    "glif_a4ef6d3aa5d8575ea8448b29e293919a42a6869143fcbfc32f2e4a7dbe53199a",
    "glif_51d216db54438b777c4170cd8913d628ff0af09789ed5dbcbd718fa6c6968bb1",
    "glif_c9dc66b31537b5a423446bbdead5dc2dbd73dc1f4a5c47a9b77328abcbc7b755",
    "glif_f5a55ee6d767b79f2f3af01c276ec53d14475eace7cabf34b22f8e5968f3fef5",
    "glif_c3a7fd4779b59f59c08d17d4a7db46beefa3e9e49a9ebc4921ecaca35c556ab7",
    "glif_b31fdc2c9a7aaac0ec69d5f59bf05ccea0c5786990ef06b79a1d7db8e37ba317"
]
GLIF_ID = "cm0zceq2a00023f114o6hti7w"

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
# CORE FUNCTIONALITY
# ======================
def send_whatsapp_message(phone, text, retries=3):
    """Send message via GreenAPI (strictly to authorized number)"""
    if phone != AUTHORIZED_NUMBER:
        logger.error(f"Blocked unauthorized send attempt to {phone}")
        return False

    url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/SendMessage/{GREEN_API['apiToken']}"
    payload = {
        "chatId": f"{phone}@c.us",
        "message": text
    }

    for attempt in range(retries):
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Sent to {phone}: {text[:50]}...")
            return True
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed: {str(e)}")
            time.sleep(2)
    logger.error(f"Failed to send to {phone} after {retries} attempts")
    return False

def send_whatsapp_image(phone, image_url, caption, retries=3):
    """Send image via GreenAPI (strictly to authorized number)"""
    if phone != AUTHORIZED_NUMBER:
        logger.error(f"Blocked unauthorized image send to {phone}")
        return False

    # Step 1: Upload file
    upload_url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/UploadFile/{GREEN_API['apiToken']}"
    try:
        upload_response = requests.post(upload_url, json={"url": image_url})
        upload_response.raise_for_status()
        file_id = upload_response.json().get("idFile")
        if not file_id:
            raise ValueError("No file ID received")
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        return False

    # Step 2: Send file
    send_url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/SendFileByUpload/{GREEN_API['apiToken']}"
    payload = {
        "chatId": f"{phone}@c.us",
        "caption": caption,
        "fileId": file_id
    }

    for attempt in range(retries):
        try:
            response = requests.post(send_url, json=payload, timeout=20)
            response.raise_for_status()
            logger.info(f"Image sent to {phone}: {caption[:50]}...")
            return True
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed: {str(e)}")
            time.sleep(2)
    logger.error(f"Failed to send image to {phone} after {retries} attempts")
    return False

def generate_thumbnail(prompt):
    """Generate image using all available GLIF tokens"""
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

# ======================
# WEBHOOK HANDLER (STRICT FILTERING)
# ======================
@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        # 1. Log raw incoming data
        webhook_data = request.json
        logger.info(f"Incoming webhook: {webhook_data}")

        # 2. Reject non-message events immediately
        if webhook_data.get('typeWebhook') != 'incomingMessageReceived':
            logger.warning(f"Ignored webhook type: {webhook_data.get('typeWebhook')}")
            return jsonify({'status': 'ignored'}), 200

        # 3. Extract sender and validate
        sender_data = webhook_data.get('senderData', {})
        sender_phone = sender_data.get('sender', '').split('@')[0]
        
        if sender_phone != AUTHORIZED_NUMBER:
            logger.warning(f"Blocked unauthorized sender: {sender_phone}")
            return jsonify({'status': 'unauthorized'}), 403

        # 4. Process only text messages
        message_data = webhook_data.get('messageData', {})
        message = message_data.get('textMessageData', {}).get('text', '').strip().lower()
        
        if not message:
            logger.warning("Received empty message")
            return jsonify({'status': 'empty_message'}), 200

        logger.info(f"Processing from {sender_phone}: {message}")

        # 5. Command handling
        if message in ['hi', 'hello', 'hey']:
            send_whatsapp_message(sender_phone, "👋 Hi! Send me a video topic to generate a thumbnail!")
        
        elif message in ['help', 'info']:
            send_whatsapp_message(sender_phone, "ℹ️ Just send me a topic (e.g. 'cooking tutorial') and I'll create a thumbnail!")
        
        elif len(message) > 3:  # Thumbnail generation
            send_whatsapp_message(sender_phone, "🔄 Generating your thumbnail... (20-30 seconds)")
            
            result = generate_thumbnail(message)
            if result['status'] == 'success':
                send_whatsapp_image(sender_phone, result['image_url'], f"🎨 Thumbnail for: {message}")
                send_whatsapp_message(sender_phone, f"🔗 Direct URL: {result['image_url']}")
            else:
                send_whatsapp_message(sender_phone, "❌ Failed to generate. Please try different keywords.")

        return jsonify({'status': 'processed'})

    except Exception as e:
        logger.critical(f"Webhook error: {str(e)}", exc_info=True)
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
    logger.info(f"""\n
    ============================================
    Starting WhatsApp Thumbnail Bot
    Authorized Number: {AUTHORIZED_NUMBER}
    GreenAPI Instance: {GREEN_API['idInstance']}
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
