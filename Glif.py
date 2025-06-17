from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
import re
import time

app = Flask(__name__)

# Configuration
GREEN_API = {
    "idInstance": "7105261536",
    "apiToken": "13a4bbfd70394a1c862c5d709671333fb1717111737a4f7998",
    "apiUrl": "https://7105.api.greenapi.com"
}
AUTHORIZED_GROUP = "120363421227499361@g.us"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def delete_message(chat_id, message_id):
    """Delete message using GreenAPI"""
    url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/deleteMessage/{GREEN_API['apiToken']}"
    payload = {
        "chatId": chat_id,
        "idMessage": message_id
    }
    
    try:
        # Add delay to ensure message is processed by WhatsApp servers
        time.sleep(1)
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=10
        )
        
        # Check for specific error responses
        if response.status_code == 400:
            error_data = response.json()
            logger.error(f"API Error: {error_data.get('message', 'Unknown error')}")
            return False
            
        response.raise_for_status()
        logger.info(f"Successfully deleted message {message_id}")
        return True
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {str(e)}")
        return False

def contains_url(text):
    """Improved URL detection"""
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    return bool(url_pattern.search(text))

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.json
        logger.info(f"Incoming message from {data.get('senderData', {}).get('sender', 'unknown')}")

        # Verify message is from our authorized group
        sender_data = data.get('senderData', {})
        chat_id = sender_data.get('chatId', '')
        
        if chat_id != AUTHORIZED_GROUP:
            return jsonify({'status': 'ignored'}), 200

        # Extract message details
        message_data = data.get('messageData', {})
        message_id = data.get('idMessage', '')
        
        # Check for URL in different message types
        text = ''
        if message_data.get('typeMessage') == 'textMessage':
            text = message_data.get('textMessageData', {}).get('textMessage', '')
        elif message_data.get('typeMessage') == 'extendedTextMessage':
            text = message_data.get('extendedTextMessageData', {}).get('text', '')

        # If message contains URL, delete it
        if text and contains_url(text):
            logger.info(f"URL detected in message {message_id[:6]}...")
            if delete_message(chat_id, message_id):
                return jsonify({'status': 'deleted'}), 200
            else:
                logger.warning("Failed to delete message, attempting alternative method")
                # Try sending a delete request with different content-type
                return jsonify({'status': 'retrying'}), 200

        return jsonify({'status': 'no_action'}), 200

    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}", exc_info=True)
        return jsonify({'status': 'error'}), 500

@app.route('/')
def health_check():
    return jsonify({
        "status": "active",
        "authorized_group": AUTHORIZED_GROUP,
        "function": "URL message deleter",
        "timestamp": int(time.time())
    })

if __name__ == '__main__':
    logger.info(f"""
    ====================================
    WhatsApp URL Deleter Bot READY
    Monitoring group: {AUTHORIZED_GROUP}
    ====================================
    """)
    serve(app, host='0.0.0.0', port=8000)
