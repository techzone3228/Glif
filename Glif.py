from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
from datetime import datetime
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
AUTHORIZED_GROUP = "120363421227499361@g.us"
BOT_NUMBER = "13656174559@c.us"

# ======================
# LOGGING SETUP
# ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def send_whatsapp_message(text):
    """Send text message to authorized group"""
    url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/sendMessage/{GREEN_API['apiToken']}"
    payload = {
        "chatId": AUTHORIZED_GROUP,
        "message": text
    }
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"Message sent to group: {text[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {str(e)}")
        return False

def extract_message_text_and_links(message_data):
    """Extract text and detect links from different message types including previews"""
    message_text = ""
    links = []
    
    if message_data.get('typeMessage') == 'textMessage':
        message_text = message_data.get('textMessageData', {}).get('textMessage', '').strip()
    elif message_data.get('typeMessage') == 'extendedTextMessage':
        extended_data = message_data.get('extendedTextMessageData', {})
        message_text = extended_data.get('text', '').strip()
        
        # Check for link in preview data
        if 'previewType' in extended_data and extended_data['previewType'] != 'None':
            if 'matchText' in extended_data:
                message_text = extended_data['matchText']
            elif 'title' in extended_data:
                message_text = extended_data['title']
    
    # URL detection with improved regex
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    links = url_pattern.findall(message_text)
    
    return message_text, links

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.json
        logger.info(f"RAW WEBHOOK DATA:\n{data}")

        # Verify sender is from our authorized group and not the bot itself
        sender_data = data.get('senderData', {})
        chat_id = sender_data.get('chatId', '')
        sender = sender_data.get('sender', '')
        
        if chat_id != AUTHORIZED_GROUP:
            logger.warning(f"Ignoring message from: {chat_id}")
            return jsonify({'status': 'ignored'}), 200
            
        if sender == BOT_NUMBER:
            logger.info("Ignoring bot's own message")
            return jsonify({'status': 'ignored'}), 200

        # Extract message text and links
        message_data = data.get('messageData', {})
        message_text, links = extract_message_text_and_links(message_data)

        if not message_text:
            logger.warning("Received empty message")
            return jsonify({'status': 'empty_message'}), 200

        logger.info(f"PROCESSING MESSAGE FROM {sender}: {message_text}")
        if links:
            logger.info(f"Detected links: {links}")

        # Check if message contains a URL
        if links:
            for link in links:
                send_whatsapp_message(f"🔗 URL detected: {link}")
        else:
            send_whatsapp_message(f"📝 You said: {message_text}")

        return jsonify({'status': 'processed'})

    except Exception as e:
        logger.error(f"WEBHOOK ERROR: {str(e)}", exc_info=True)
        return jsonify({'status': 'error'}), 500

@app.route('/')
def health_check():
    return jsonify({
        "status": "active",
        "authorized_group": AUTHORIZED_GROUP,
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    logger.info(f"""
    ============================================
    WhatsApp Link Detection Bot READY
    ONLY responding to group: {AUTHORIZED_GROUP}
    Ignoring messages from: {BOT_NUMBER}
    GreenAPI Instance: {GREEN_API['idInstance']}
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
