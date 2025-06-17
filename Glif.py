from flask import Flask, request, jsonify
from waitress import serve
import re

app = Flask(__name__)

# Configuration
GREEN_API = {
    "idInstance": "7105261536",
    "apiToken": "13a4bbfd70394a1c862c5d709671333fb1717111737a4f7998",
    "apiUrl": "https://7105.api.greenapi.com"
}
AUTHORIZED_GROUP = "120363421227499361@g.us"

def send_whatsapp_message(text, chat_id):
    """Send text message to specified chat"""
    url = f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/sendMessage/{GREEN_API['apiToken']}"
    payload = {
        "chatId": chat_id,
        "message": text
    }
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send message: {str(e)}")
        return False

def extract_url(text):
    """Extract URL from text (including messages with previews)"""
    # This pattern matches URLs even when they're embedded in other text
    url_pattern = r'(https?://\S+)'
    match = re.search(url_pattern, text)
    return match.group(1) if match else None

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.json
        
        # Verify message is from our authorized group
        sender_data = data.get('senderData', {})
        chat_id = sender_data.get('chatId', '')
        
        if chat_id != AUTHORIZED_GROUP:
            return jsonify({'status': 'ignored'}), 200

        # Extract message text from different message types
        message_data = data.get('messageData', {})
        if message_data.get('typeMessage') == 'textMessage':
            message = message_data.get('textMessageData', {}).get('textMessage', '')
        elif message_data.get('typeMessage') == 'extendedTextMessage':
            message = message_data.get('extendedTextMessageData', {}).get('text', '')
        else:
            return jsonify({'status': 'unsupported_type'}), 200

        # Check if message contains a URL
        url = extract_url(message)
        if url:
            # Send the URL back to the group
            send_whatsapp_message(f"I detected this URL: {url}", chat_id)
        else:
            # For non-URL messages, just echo them
            send_whatsapp_message(f"You said: {message}", chat_id)

        return jsonify({'status': 'processed'})

    except Exception as e:
        print(f"WEBHOOK ERROR: {str(e)}")
        return jsonify({'status': 'error'}), 500

if __name__ == '__main__':
    print(f"Simple WhatsApp Bot running - listening for messages in group {AUTHORIZED_GROUP}")
    serve(app, host='0.0.0.0', port=8000)
