from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
import re

app = Flask(__name__)

# GreenAPI Configuration
GREEN_API = {
    "idInstance": "7105261536",
    "apiToken": "13a4bbfd70394a1c862c5d709671333fb1717111737a4f7998",
    "apiUrl": "https://7105.api.greenapi.com"
}

# Group to monitor
AUTHORIZED_GROUP = "120363421227499361@g.us"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def remove_participant(chat_id, participant):
    """Remove participant from group"""
    url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/removeGroupParticipant/{GREEN_API['apiToken']}"
    payload = {
        "groupId": chat_id,
        "participantChatId": participant
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logger.info(f"Removed {participant} from group {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to remove participant: {str(e)}")
        return False

def send_message(chat_id, text):
    """Send message to group"""
    url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/sendMessage/{GREEN_API['apiToken']}"
    payload = {
        "chatId": chat_id,
        "message": text
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logger.info(f"Message sent to {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {str(e)}")
        return False

def is_url(text):
    """Check if text contains a URL"""
    url_pattern = re.compile(
        r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w .-]*/?'
    )
    return bool(url_pattern.search(text))

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"Incoming webhook data: {data}")
        
        # Check if message is from our monitored group
        sender_data = data.get('senderData', {})
        chat_id = sender_data.get('chatId', '')
        
        if chat_id != AUTHORIZED_GROUP:
            logger.info(f"Ignoring message from {chat_id}")
            return jsonify({'status': 'ignored'}), 200
            
        # Get sender and message content
        sender = sender_data.get('sender', '')
        message_data = data.get('messageData', {})
        
        # Extract text from different message types
        if message_data.get('typeMessage') == 'textMessage':
            message = message_data.get('textMessageData', {}).get('textMessage', '')
        elif message_data.get('typeMessage') == 'extendedTextMessage':
            message = message_data.get('extendedTextMessageData', {}).get('text', '')
        else:
            return jsonify({'status': 'unsupported_type'}), 200
        
        # Check if message contains URL
        if is_url(message):
            logger.info(f"URL detected from {sender}")
            
            # Remove the participant who sent the URL
            if remove_participant(chat_id, sender):
                # Notify group
                send_message(chat_id, f"⚠️ {sender.split('@')[0]} was removed for sharing a link.")
            else:
                send_message(chat_id, "⚠️ Failed to remove participant. Admin action required.")
        
        return jsonify({'status': 'processed'}), 200
    
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/')
def health_check():
    return jsonify({
        'status': 'running',
        'monitored_group': AUTHORIZED_GROUP
    })

if __name__ == '__main__':
    logger.info(f"""
    ====================================
    Link Monitor Bot Started
    Monitoring Group: {AUTHORIZED_GROUP}
    ====================================
    """)
    serve(app, host='0.0.0.0', port=8000)
