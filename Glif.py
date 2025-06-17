from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
import re

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
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logger.info(f"Deleted message {message_id} in chat {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete message: {str(e)}")
        return False

def contains_url(text):
    """Check if text contains URL"""
    url_pattern = re.compile(
        r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w .-]*/?'
    )
    return bool(url_pattern.search(text))

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.json
        logger.info(f"Incoming webhook data: {data}")

        # Verify message is from our authorized group
        sender_data = data.get('senderData', {})
        chat_id = sender_data.get('chatId', '')
        
        if chat_id != AUTHORIZED_GROUP:
            logger.warning(f"Ignoring message from: {chat_id}")
            return jsonify({'status': 'ignored'}), 200

        # Extract message details
        message_data = data.get('messageData', {})
        message_id = data.get('idMessage', '')
        
        # Check for URL in different message types
        if message_data.get('typeMessage') == 'textMessage':
            text = message_data.get('textMessageData', {}).get('textMessage', '')
        elif message_data.get('typeMessage') == 'extendedTextMessage':
            text = message_data.get('extendedTextMessageData', {}).get('text', '')
        else:
            return jsonify({'status': 'unsupported_type'}), 200

        # If message contains URL, delete it
        if contains_url(text):
            logger.info(f"Detected URL in message {message_id}: {text[:50]}...")
            delete_message(chat_id, message_id)
            return jsonify({'status': 'deleted'}), 200

        return jsonify({'status': 'no_action'}), 200

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/')
def health_check():
    return jsonify({
        "status": "active",
        "authorized_group": AUTHORIZED_GROUP,
        "function": "URL message deleter"
    })

if __name__ == '__main__':
    logger.info(f"""
    ====================================
    WhatsApp URL Deleter Bot READY
    Monitoring group: {AUTHORIZED_GROUP}
    ====================================
    """)
    serve(app, host='0.0.0.0', port=8000)
