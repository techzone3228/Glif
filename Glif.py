from flask import Flask, request, jsonify
import requests
import logging

app = Flask(__name__)

# GreenAPI Configuration
INSTANCE_ID = "7105261536"
API_TOKEN = "13a4bbfd70394a1c862c5d709671333fb1717111737a4f7998"
AUTHORIZED_GROUP = "120363421227499361@g.us"
GREEN_API_URL = f"https://7105.api.greenapi.com/waInstance{INSTANCE_ID}"

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def remove_participant(chat_id, participant_id):
    """Remove participant from group using GreenAPI"""
    url = f"{GREEN_API_URL}/removeGroupParticipant/{API_TOKEN}"
    payload = {
        "groupId": chat_id,
        "participantId": participant_id
    }
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"Removed participant {participant_id} from group {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to remove participant: {str(e)}")
        return False

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"Incoming webhook data: {data}")

        # Check if message is from our authorized group
        sender_data = data.get('senderData', {})
        chat_id = sender_data.get('chatId', '')
        
        if chat_id != AUTHORIZED_GROUP:
            logger.info(f"Ignoring message from non-authorized chat: {chat_id}")
            return jsonify({'status': 'ignored'}), 200

        # Get sender and message details
        participant_id = sender_data.get('sender', '')  # The participant to remove
        message_data = data.get('messageData', {})
        
        # Check for URL in message
        message_text = ""
        if message_data.get('typeMessage') == 'textMessage':
            message_text = message_data.get('textMessageData', {}).get('textMessage', '').lower()
        elif message_data.get('typeMessage') == 'extendedTextMessage':
            message_text = message_data.get('extendedTextMessageData', {}).get('text', '').lower()

        # Check if message contains a URL
        if any(proto in message_text for proto in ['http://', 'https://', 'www.']):
            logger.info(f"Detected URL in message from {participant_id}")
            
            # Remove the participant who sent the URL
            if remove_participant(chat_id, participant_id):
                # Notify group (optional)
                requests.post(
                    f"{GREEN_API_URL}/sendMessage/{API_TOKEN}",
                    json={
                        "chatId": chat_id,
                        "message": f"⚠️ {participant_id.split('@')[0]} was removed for sharing a link."
                    },
                    headers={'Content-Type': 'application/json'}
                )
                return jsonify({'status': 'removed'}), 200
            else:
                return jsonify({'status': 'removal_failed'}), 200

        return jsonify({'status': 'no_action'}), 200

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({'status': 'error'}), 500

if __name__ == '__main__':
    logger.info("Starting URL moderator bot...")
    app.run(host='0.0.0.0', port=8000)
