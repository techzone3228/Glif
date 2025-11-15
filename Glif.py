from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
from datetime import datetime
import tempfile
import os
from bs4 import BeautifulSoup

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
BOT_NUMBER = "923400315734@c.us"
ADMIN_NUMBER = "923247220362@c.us"

# Wikipedia Configuration
WIKIPEDIA_BASE_URL = "https://en.wikipedia.org/"
WIKIPEDIA_API_PDF = "api/rest_v1/page/pdf/"
WIKIPEDIA_API_SEARCH = "w/api.php?action=opensearch&search="

# ======================
# LOGGING SETUP
# ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def send_whatsapp_message(text, chat_id=None):
    """Send text message to authorized group or specified chat"""
    try:
        target_chat = chat_id if chat_id else AUTHORIZED_GROUP
        response = requests.post(
            f"{GREEN_API['apiUrl']}/waInstance{GREEN_API['idInstance']}/sendMessage/{GREEN_API['apiToken']}",
            json={"chatId": target_chat, "message": text},
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        logger.info(f"Message sent to {target_chat}: {text[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Message send error: {str(e)}")
        return False

def send_whatsapp_file(file_path, caption, is_video=False, chat_id=None):
    """Send file with caption to group or specified chat"""
    try:
        target_chat = chat_id if chat_id else AUTHORIZED_GROUP
        with open(file_path, 'rb') as file:
            response = requests.post(
                f"{GREEN_API['mediaUrl']}/waInstance{GREEN_API['idInstance']}/sendFileByUpload/{GREEN_API['apiToken']}",
                files={'file': (os.path.basename(file_path), file, 
                      'video/mp4' if is_video else 'audio/mpeg' if file_path.endswith('.mp3') else 'application/pdf' if file_path.endswith('.pdf') else 'image/jpeg')},
                data={'chatId': target_chat, 'caption': caption}
            )
            response.raise_for_status()
            logger.info(f"File sent to {target_chat}: {caption[:50]}...")
            return True
    except Exception as e:
        logger.error(f"File send error: {str(e)}")
        return False

def get_live_cricket_scores():
    """Fetch live cricket scores from Cricbuzz with updated parsing"""
    try:
        url = "https://www.cricbuzz.com/cricket-match/live-scores"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        matches = []
        
        # Try different selectors for match elements
        selectors = [
            'a.text-hvr-underline',
            'div.cb-mtch-lst',
            'div.cb-col-100',
            '[class*="match"]'
        ]
        
        for selector in selectors:
            match_elements = soup.select(selector)
            if match_elements:
                logger.info(f"Found {len(match_elements)} matches using selector: {selector}")
                break
        else:
            # Fallback: find any elements containing match info
            match_elements = soup.find_all(text=lambda text: text and 'vs' in text and any(word in text.lower() for word in ['cricket', 'match', 'score']))
        
        for element in match_elements[:8]:  # Limit to 8 matches
            try:
                if hasattr(element, 'get_text'):
                    text = element.get_text(strip=True)
                else:
                    text = str(element).strip()
                
                if len(text) > 30 and 'vs' in text:
                    matches.append({
                        'teams': text[:150],  # Limit length
                        'score': 'Check website for details',
                        'status': 'Live' if 'live' in text.lower() else 'Completed'
                    })
            except Exception:
                continue
        
        if matches:
            return matches
        else:
            return [{
                'teams': 'No live matches found',
                'score': 'Please check cricbuzz.com',
                'status': 'No current matches'
            }]
                
    except Exception as e:
        logger.error(f"Cricket scores error: {str(e)}")
        return [{
            'teams': 'Error fetching scores',
            'score': 'Please try again later',
            'status': 'Service unavailable'
        }]

def search_wikipedia(query):
    """Search Wikipedia for similar titles"""
    url = WIKIPEDIA_BASE_URL + WIKIPEDIA_API_SEARCH + query.replace(" ", "%20")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data[1]  # Returns list of suggested titles
    except Exception as e:
        logger.error(f"Wikipedia search error: {str(e)}")
        return []

def download_wikipedia_pdf(title, chat_id=None):
    """Download Wikipedia page as PDF"""
    formatted_title = title.strip().replace(" ", "_")
    url = WIKIPEDIA_BASE_URL + WIKIPEDIA_API_PDF + formatted_title
    temp_dir = tempfile.mkdtemp()
    filename = os.path.join(temp_dir, f"{formatted_title}.pdf")
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf"
        }
        
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        
        if response.status_code == 403:
            return None, "❌ Wikipedia is blocking requests. Try again later."
        elif response.status_code == 404:
            return None, "❌ Article not found. Check spelling."
        
        response.raise_for_status()
        
        # Check if it's actually a PDF
        content_type = response.headers.get('content-type', '')
        if 'pdf' not in content_type.lower():
            return None, "❌ No PDF available for this article."
        
        with open(filename, 'wb') as pdf_file:
            for chunk in response.iter_content(chunk_size=4096):
                if chunk:
                    pdf_file.write(chunk)
        
        # Verify file was downloaded properly
        if os.path.exists(filename) and os.path.getsize(filename) > 1000:
            return filename, None
        else:
            if os.path.exists(filename):
                os.remove(filename)
            return None, "❌ Failed to download PDF"
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Wikipedia PDF download error: {str(e)}")
        
        # Get suggestions for better error handling
        suggestions = search_wikipedia(title)
        if suggestions:
            suggestions_text = "🔍 *Did you mean:*\n\n"
            for i, suggestion in enumerate(suggestions[:5], 1):
                suggestions_text += f"{i}. {suggestion}\n"
            suggestions_text += "\n_Reply with the number to download_"
            return None, suggestions_text
        else:
            return None, f"❌ Download failed: {str(e)}"
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return None, "❌ An unexpected error occurred."

def process_user_message(message, chat_id, sender):
    """Process user message for cricket and wikipedia commands"""
    try:
        # Get the target chat ID (group or personal)
        target_chat = chat_id
        
        # Command handling
        if message.lower().startswith('/cricket'):
            send_whatsapp_message("🏏 Fetching live cricket scores...", target_chat)
            matches = get_live_cricket_scores()
            if matches:
                response_text = "🏏 *LIVE CRICKET SCORES*\n\n"
                for match in matches:
                    response_text += f"*{match['teams']}*\n"
                    response_text += f"📊 {match['score']}\n"
                    response_text += f"🟢 {match['status']}\n"
                    response_text += "-------------------------\n"
                response_text += "\n_Data from Cricbuzz_"
                send_whatsapp_message(response_text, target_chat)
            else:
                send_whatsapp_message("❌ No live matches found or unable to fetch scores", target_chat)
        
        elif message.lower().startswith('/wikipdf '):
            article = message[9:].strip()
            if article:
                send_whatsapp_message(f"📚 Searching Wikipedia for: {article}", target_chat)
                pdf_path, error_msg = download_wikipedia_pdf(article, target_chat)
                
                if pdf_path:
                    send_whatsapp_file(pdf_path, f"📚 *Wikipedia Article*\n{article}", chat_id=target_chat)
                    os.remove(pdf_path)
                    os.rmdir(os.path.dirname(pdf_path))
                else:
                    send_whatsapp_message(f"❌ {error_msg}", target_chat)
            else:
                send_whatsapp_message("ℹ️ Please specify an article title (e.g. /wikipdf Python)", target_chat)
        
        elif message.lower() in ['hi', 'hello', 'hey', '/help', 'help']:
            help_text = """👋 *Hello! Here's what I can do:*

🏏 *Cricket Scores:*
`/cricket` - Get live cricket scores

📚 *Wikipedia:*
`/wikipdf [article]` - Get Wikipedia article as PDF

Need more help? Contact admin!"""
            send_whatsapp_message(help_text, target_chat)

    except Exception as e:
        logger.error(f"Message processing error: {str(e)}")
        send_whatsapp_message("❌ *An error occurred. Please try again.*", target_chat)

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        data = request.json
        logger.info(f"RAW WEBHOOK DATA:\n{data}")

        sender_data = data.get('senderData', {})
        sender = sender_data.get('sender', '')
        chat_id = sender_data.get('chatId', '')
        
        # Ignore messages from the bot itself
        if BOT_NUMBER in sender:
            logger.info("Ignoring message from bot itself")
            return jsonify({'status': 'ignored'}), 200
        
        # Get message content
        message_data = data.get('messageData', {})
        if message_data.get('typeMessage') == 'textMessage':
            message = message_data.get('textMessageData', {}).get('textMessage', '').strip()
        elif message_data.get('typeMessage') == 'extendedTextMessage':
            message = message_data.get('extendedTextMessageData', {}).get('text', '').strip()
        else:
            logger.warning(f"Unsupported message type: {message_data.get('typeMessage')}")
            return jsonify({'status': 'unsupported_type'}), 200

        if not message:
            logger.warning("Received empty message")
            return jsonify({'status': 'empty_message'}), 200

        logger.info(f"PROCESSING MESSAGE FROM {sender} IN CHAT {chat_id}: {message}")

        # Allow processing if:
        # 1. Message is in authorized group, or
        # 2. Message is from admin in personal chat
        if chat_id == AUTHORIZED_GROUP or (sender == ADMIN_NUMBER and not chat_id.endswith('@g.us')):
            process_user_message(message, chat_id, sender)
            return jsonify({'status': 'processing'}), 200
        else:
            logger.warning(f"Ignoring message from unauthorized chat: {chat_id}")
            return jsonify({'status': 'ignored'}), 200

    except Exception as e:
        logger.error(f"WEBHOOK ERROR: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/')
def health_check():
    return jsonify({
        "status": "active",
        "authorized_group": AUTHORIZED_GROUP,
        "instance_id": GREEN_API['idInstance'],
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    logger.info(f"""
    ============================================
    WhatsApp Cricket & Wikipedia Bot READY
    Responding to group: {AUTHORIZED_GROUP}
    And admin ({ADMIN_NUMBER}) in personal chat
    Ignoring messages from: {BOT_NUMBER}
    GreenAPI Instance: {GREEN_API['idInstance']}
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
