from flask import Flask, request, jsonify
from waitress import serve
import requests
import logging
from datetime import datetime
import yt_dlp
import os
import tempfile
import subprocess
import re
import threading
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from concurrent.futures import ThreadPoolExecutor
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
ADMIN_NUMBER = "923247220362@c.us"  # Admin can use bot in personal chat

# GLIF Configuration (Admin-only thumbnail generation)
GLIF_ID = "cm0zceq2a00023f114o6hti7w"
GLIF_TOKENS = [
    "glif_a4ef6d3aa5d8575ea8448b29e293919a42a6869143fcbfc32f2e4a7dbe53199a",
    "glif_51d216db54438b777c4170cd8913d628ff0af09789ed5dbcbd718fa6c6968bb1",
    "glif_c9dc66b31537b5a423446bbdead5dc2dbd73dc1f4a5c47a9b77328abcbc7b755",
    "glif_f5a55ee6d767b79f2f3af01c276ec53d14475eace7cabf34b22f8e5968f3fef5",
    "glif_c3a7fd4779b59f59c08d17d4a7db46beefa3e9e49a9ebc4921ecaca35c556ab7",
    "glif_b31fdc2c9a7aaac0ec69d5f59bf05ccea0c5786990ef06b79a1d7db8e37ba317"
]

# Wikipedia Configuration
WIKIPEDIA_BASE_URL = "https://en.wikipedia.org/"
WIKIPEDIA_API_PDF = "api/rest_v1/page/pdf/"
WIKIPEDIA_API_SEARCH = "w/api.php?action=opensearch&search="

# Cookie configuration
IG_COOKIES_FILE = "igcookies.txt"
IG_COOKIES_DRIVE_URL = "https://drive.google.com/uc?export=download&id=13kNOfYmC8kZEE9Le786ndnZbdPpGBtEX"
YT_COOKIES_FILE = "cookies.txt"
YT_COOKIES_DRIVE_URL = "https://drive.google.com/uc?export=download&id=13iX8xpx47W3PAedGyhGpF5CxZRFz4uaF"

# Google Drive Configuration
DRIVE_FOLDER_ID = "12Wunh_25s3VkXAl08jVlXNQCr2ilzVt4"
TOKEN_FILE = "token.json"
TOKEN_DRIVE_URL = "https://drive.google.com/uc?export=download&id=14p_O13T1GFyZncJw3pPRYTi2jF2bh9bO"
SCOPES = ['https://www.googleapis.com/auth/drive']

# Thread pool for concurrent processing
executor = ThreadPoolExecutor(max_workers=10)

# Thread-safe session management
user_sessions = {}
session_lock = threading.Lock()

# ======================
# LOGGING SETUP
# ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def download_file(url, filename):
    """Download file from Google Drive"""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"Failed to download {filename}: {str(e)}")
        return False

def ensure_files():
    """Ensure all required files exist"""
    if not os.path.exists(IG_COOKIES_FILE):
        download_file(IG_COOKIES_DRIVE_URL, IG_COOKIES_FILE)
    if not os.path.exists(YT_COOKIES_FILE):
        download_file(YT_COOKIES_DRIVE_URL, YT_COOKIES_FILE)
    if not os.path.exists(TOKEN_FILE):
        download_file(TOKEN_DRIVE_URL, TOKEN_FILE)

def get_drive_service():
    """Authenticate and return Google Drive service"""
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Drive auth error: {str(e)}")
        return None

def is_youtube_url(url):
    """Check if URL is from YouTube"""
    return 'youtube.com' in url or 'youtu.be' in url

def is_instagram_url(url):
    """Check if URL is from Instagram"""
    return 'instagram.com' in url or 'instagr.am' in url

def get_cookies_for_url(url):
    """Get appropriate cookies file for URL"""
    if is_youtube_url(url):
        return YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None
    elif is_instagram_url(url):
        return IG_COOKIES_FILE if os.path.exists(IG_COOKIES_FILE) else None
    return None

def check_audio(filename):
    """Check if file has audio stream"""
    try:
        result = subprocess.run(
            ['ffprobe', '-i', filename, '-show_streams', '-select_streams', 'a', '-loglevel', 'error'],
            capture_output=True,
            text=True
        )
        return "codec_type=audio" in result.stdout
    except Exception as e:
        logger.error(f"Audio check error: {str(e)}")
        return False

def get_estimated_size(url, quality):
    """Estimate file size before downloading"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': get_cookies_for_url(url),
            'format': 'best' if quality == 'best' else f'best[filesize<100M]'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
                
            if 'filesize' in info and info['filesize']:
                return info['filesize']
                
            if 'duration' in info and 'format' in info:
                duration = info['duration']
                bitrate = 0
                
                if quality == 'mp3':
                    bitrate = 192  # kbps
                elif quality == '144p':
                    bitrate = 200  # kbps
                elif quality == '360p':
                    bitrate = 500  # kbps
                elif quality == '480p':
                    bitrate = 1000 # kbps
                elif quality == '720p':
                    bitrate = 2500 # kbps
                elif quality == '1080p':
                    bitrate = 5000 # kbps
                else:  # best or unknown
                    bitrate = 8000 # kbps
                
                estimated_size = (bitrate * 1000 * duration) / 8
                return estimated_size
                
        return None
    except Exception as e:
        logger.error(f"Size estimation error: {str(e)}")
        return None

def get_available_qualities(url):
    """Get available qualities for URL"""
    try:
        if is_youtube_url(url):
            return get_youtube_qualities(url)
        elif is_instagram_url(url):
            return get_instagram_qualities(url)
        return get_other_platform_qualities(url)
    except Exception as e:
        logger.error(f"Quality check error: {str(e)}")
        return None

def get_youtube_qualities(url):
    """Get YouTube quality options"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or 'formats' not in info:
                return None
            
            quality_map = {}
            for fmt in info.get('formats', []):
                if fmt.get('vcodec') != 'none':
                    height = fmt.get('height', 0)
                    if height >= 1080: quality_map['1080p'] = fmt['format_id']
                    if height >= 720: quality_map['720p'] = fmt['format_id']
                    if height >= 480: quality_map['480p'] = fmt['format_id']
                    if height >= 360: quality_map['360p'] = fmt['format_id']
                    if height >= 144: quality_map['144p'] = fmt['format_id']
            
            quality_map['best'] = 'bestvideo+bestaudio/best'
            quality_map['mp3'] = 'bestaudio/best'
            return {q: quality_map[q] for q in ['144p', '360p', '480p', '720p', '1080p', 'best', 'mp3'] if q in quality_map}
    except Exception as e:
        logger.error(f"YouTube quality error: {str(e)}")
        return None

def get_instagram_qualities(url):
    """Get Instagram quality options with rate limit handling"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': IG_COOKIES_FILE if os.path.exists(IG_COOKIES_FILE) else None
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and info.get('is_live'):
                raise Exception("Instagram rate limit reached")
            
            if not info or 'formats' not in info:
                return None
                
            quality_map = {}
            for fmt in info.get('formats', []):
                if fmt.get('vcodec') != 'none':
                    height = fmt.get('height', 0)
                    if height >= 1080: quality_map['1080p'] = fmt['format_id']
                    elif height >= 720: quality_map['720p'] = fmt['format_id']
                    elif height >= 480: quality_map['480p'] = fmt['format_id']
                    else: quality_map['SD'] = fmt['format_id']
            
            if quality_map:
                quality_map['best'] = 'bestvideo+bestaudio/best'
                quality_map['mp3'] = 'bestaudio/best'
                return quality_map
            return None
    except yt_dlp.utils.DownloadError as e:
        if 'rate limit' in str(e).lower() or '429' in str(e):
            raise Exception("Instagram servers are busy. Please try again later.")
        logger.error(f"Instagram error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Instagram quality error: {str(e)}")
        return None

def get_other_platform_qualities(url):
    """Get quality options for other platforms"""
    try:
        ydl_opts = {
            'quiet': True,
            'cookiefile': get_cookies_for_url(url)
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            if not formats:
                return None

            video_formats = []
            audio_formats = []
            
            for f in formats:
                if f.get('acodec') != 'none' and f.get('vcodec') != 'none':
                    video_formats.append({
                        'id': f['format_id'],
                        'quality': f"{f.get('height', 0)}p",
                        'type': 'video'
                    })
                elif f.get('acodec') != 'none':
                    audio_formats.append({
                        'id': f['format_id'],
                        'quality': f"{f.get('abr', 0)}kbps",
                        'type': 'audio'
                    })

            quality_map = {}
            for fmt in sorted(video_formats, key=lambda x: float(x['quality'].replace('p', '')), reverse=True):
                if fmt['quality'] not in quality_map:
                    quality_map[fmt['quality']] = fmt['id']
            
            for fmt in sorted(audio_formats, key=lambda x: float(x['quality'].replace('kbps', '')), reverse=True):
                quality_map[f"{fmt['quality']} (Audio)"] = fmt['id']
            
            quality_map['best'] = 'bestvideo+bestaudio/best'
            quality_map['mp3'] = 'bestaudio/best'
            return quality_map
    except Exception as e:
        logger.error(f"Other platform error: {str(e)}")
        return None

def download_media(url, quality, format_id=None):
    """Download media with selected quality"""
    try:
        estimated_size = get_estimated_size(url, quality)
        if estimated_size and estimated_size > 100 * 1024 * 1024:
            return None, "📛 *File size exceeds 100MB limit*"
        
        temp_dir = tempfile.mkdtemp()
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'postprocessors': [
                {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
                {'key': 'FFmpegMetadata'},
                {'key': 'EmbedThumbnail'}
            ],
            'quiet': True,
            'retries': 3
        }
        
        if cookies := get_cookies_for_url(url):
            ydl_opts['cookiefile'] = cookies
        
        if quality == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            if is_youtube_url(url):
                ydl_opts['format'] = {
                    '144p': 'bestvideo[height<=144]+bestaudio/best',
                    '360p': 'bestvideo[height<=360]+bestaudio/best',
                    '480p': 'bestvideo[height<=480]+bestaudio/best',
                    '720p': 'bestvideo[height<=720]+bestaudio/best',
                    '1080p': 'bestvideo[height<=1080]+bestaudio/best',
                    'best': 'bestvideo+bestaudio/best'
                }.get(quality, 'bestvideo+bestaudio/best')
            else:
                ydl_opts['format'] = format_id or 'bestvideo+bestaudio/best'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if os.path.exists(filename) and os.path.getsize(filename) > 100 * 1024 * 1024:
                os.remove(filename)
                return None, "📛 *File size exceeds 100MB limit*"
            
            if quality == 'mp3':
                mp3_file = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
                if os.path.exists(mp3_file):
                    if os.path.getsize(mp3_file) > 100 * 1024 * 1024:
                        os.remove(mp3_file)
                        return None, "📛 *File size exceeds 100MB limit*"
                    return mp3_file, info.get('title', 'audio')
            else:
                if check_audio(filename):
                    new_filename = f"{os.path.splitext(filename)[0]}_{quality}.mp4"
                    os.rename(filename, new_filename)
                    return new_filename, info.get('title', 'video')
                
        return None, None
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return None, None
    finally:
        try:
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except Exception as e:
            logger.warning(f"Temp dir cleanup error: {str(e)}")

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

def send_quality_options(session_key, url, chat_id=None):
    """Send available quality options"""
    send_whatsapp_message("🔍 *Checking available video qualities...*", chat_id)
    
    try:
        quality_map = get_available_qualities(url)
        if not quality_map:
            raise Exception("No qualities available")
        
        with session_lock:
            user_sessions[session_key] = {
                'url': url,
                'quality_map': quality_map,
                'awaiting_quality': True,
                'option_map': {},
                'chat_id': chat_id
            }
            
            options_text = "📺 *Available download options (Max 100MB):*\n\n"
            option_number = 1
            
            for qual in quality_map:
                if qual == 'mp3' or '(Audio)' in qual:
                    options_text += f"{option_number}. *MP3* _(Audio only)_ 🎵\n"
                    user_sessions[session_key]['option_map'][str(option_number)] = ('mp3', None)
                elif qual == 'best':
                    options_text += f"{option_number}. *Best available quality* 🌟\n"
                    user_sessions[session_key]['option_map'][str(option_number)] = ('best', quality_map[qual])
                else:
                    options_text += f"{option_number}. *{qual}* 📹\n"
                    user_sessions[session_key]['option_map'][str(option_number)] = (qual, quality_map[qual])
                option_number += 1
            
            options_text += "\n_Reply with the number of your choice_"
            send_whatsapp_message(options_text, chat_id)
    except Exception as e:
        error_msg = "⚠️ *Instagram servers are busy. Please try again later.*" if is_instagram_url(url) else "⚠️ *Error checking video qualities. Please try again later.*"
        send_whatsapp_message(error_msg, chat_id)
        logger.error(f"Quality options error: {str(e)}")

def send_course_options(session_key, query=None, chat_id=None):
    """Send course options to user"""
    send_whatsapp_message("🔍 *Searching for courses...*", chat_id)
    
    try:
        folders = list_course_folders(query)
        if not folders:
            send_whatsapp_message("❌ *No matching courses found.*", chat_id)
            return
        
        with session_lock:
            user_sessions[session_key] = {
                'folders': folders,
                'awaiting_course_selection': True,
                'option_map': {},
                'chat_id': chat_id
            }
            
            options_text = "📚 *Available Courses (A-Z):*\n\n"
            option_number = 1
            
            for folder in sorted(folders, key=lambda x: x['name'].lower()):
                options_text += f"{option_number}. *{folder['name']}* 📂\n"
                user_sessions[session_key]['option_map'][str(option_number)] = folder['id']
                option_number += 1
            
            options_text += "\n_Reply with the number of your choice_"
            send_whatsapp_message(options_text, chat_id)
    except Exception as e:
        send_whatsapp_message("❌ *Error searching courses. Please try again.*", chat_id)
        logger.error(f"Course options error: {str(e)}")

def list_course_folders(query=None):
    """List course folders from Google Drive"""
    try:
        service = get_drive_service()
        if not service:
            return None
            
        folders = []
        page_token = None
        q = f"'{DRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder'"
        if query and query.lower() != 'all':
            q += f" and name contains '{query}'"
        
        while True:
            response = service.files().list(
                q=q,
                spaces='drive',
                fields='nextPageToken, files(id, name)',
                pageToken=page_token,
                orderBy='name'
            ).execute()
            
            folders.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            if not page_token:
                break
                
        return folders
    except HttpError as e:
        logger.error(f"Drive API error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Course list error: {str(e)}")
        return None

def search_youtube(query):
    """Search YouTube videos"""
    try:
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'force_generic_extractor': True,
            'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if not info or 'entries' not in info or not info['entries']:
                return None
            
            entry = info['entries'][0]
            return {
                'url': f"https://youtube.com/watch?v={entry['id']}",
                'title': entry.get('title', 'No title'),
                'thumbnail': entry.get('thumbnail', '')
            }
    except Exception as e:
        logger.error(f"YouTube search error: {str(e)}")
        return None

def get_youtube_thumbnail(url):
    """Get YouTube thumbnail"""
    try:
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'force_generic_extractor': True,
            'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            
            thumbnails = info.get('thumbnails', [])
            if thumbnails:
                thumbnails.sort(key=lambda x: x.get('width', 0), reverse=True)
                return thumbnails[0]['url']
            
            return info.get('thumbnail')
    except Exception as e:
        logger.error(f"Thumbnail error: {str(e)}")
        return None

def generate_thumbnail(prompt):
    """Generate thumbnail using GLIF API (Admin only)"""
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
            
            for key in ["output", "image_url", "url"]:
                if key in data and isinstance(data[key], str) and data[key].startswith('http'):
                    logger.info(f"Generated thumbnail using token {token[-6:]}")
                    return {'status': 'success', 'image_url': data[key]}
        except Exception as e:
            logger.warning(f"GLIF token {token[-6:]} failed: {str(e)}")
    return {'status': 'error'}

def get_live_cricket_scores():
    """Fetch live cricket scores from Cricbuzz"""
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
        match_items = soup.find_all('div', class_='cb-mtch-lst')
        
        for item in match_items:
            try:
                # Teams
                teams = item.find('h3').get_text(strip=True)
                
                # Score
                score_div = item.find('div', class_='cb-scr-wll-chvrn')
                score = score_div.get_text(' | ', strip=True) if score_div else "Score not available"
                
                # Status
                status_div = item.find('div', class_='cb-text-live') or item.find('div', class_='cb-text-complete')
                status = status_div.get_text(strip=True) if status_div else "In Progress"
                
                matches.append({
                    'teams': teams,
                    'score': score,
                    'status': status
                })
            except Exception:
                continue
                
        return matches
    except Exception as e:
        logger.error(f"Cricket scores error: {str(e)}")
        return None

def get_weather_data(city):
    """Fetch weather data from OpenWeatherMap"""
    try:
        API_KEY = "81b37bb82aeaf67bc328dc8e1815dbcd"
        base_url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            'q': city,
            'appid': API_KEY,
            'units': 'metric'
        }
        
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Weather data error: {str(e)}")
        return None

def fix_wikipedia_title(title):
    """Formats the title for Wikipedia API"""
    return title.strip().replace(" ", "_")

def search_wikipedia(query):
    """Search Wikipedia for similar titles"""
    url = WIKIPEDIA_BASE_URL + WIKIPEDIA_API_SEARCH + query.replace(" ", "%20")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data[1]  # Returns list of suggested titles
    except requests.exceptions.RequestException as e:
        logger.error(f"Wikipedia search error: {str(e)}")
        return []

def download_wikipedia_pdf(title, chat_id=None):
    """Downloads a Wikipedia page as PDF and sends to user"""
    formatted_title = fix_wikipedia_title(title)
    url = WIKIPEDIA_BASE_URL + WIKIPEDIA_API_PDF + formatted_title
    temp_dir = tempfile.mkdtemp()
    filename = os.path.join(temp_dir, f"{formatted_title}.pdf")
    
    try:
        response = requests.get(url, stream=True, timeout=20)
        response.raise_for_status()
        
        with open(filename, 'wb') as pdf_file:
            for chunk in response.iter_content(chunk_size=4096):
                if chunk:
                    pdf_file.write(chunk)
        
        # Check if file was downloaded successfully
        if os.path.exists(filename) and os.path.getsize(filename) > 0:
            return filename, None
        else:
            os.remove(filename)
            return None, "Failed to download PDF"
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Wikipedia PDF download error: {str(e)}")
        suggestions = search_wikipedia(title)
        
        if suggestions:
            with session_lock:
                user_sessions[f"wiki_{chat_id}"] = {
                    'suggestions': suggestions[:5],
                    'awaiting_wiki_selection': True,
                    'chat_id': chat_id
                }
            
            suggestions_text = "🔍 *Wikipedia suggestions:*\n\n"
            for i, suggestion in enumerate(suggestions[:5], 1):
                suggestions_text += f"{i}. {suggestion}\n"
            suggestions_text += "\nReply with the number to download"
            
            return None, suggestions_text
        else:
            return None, "❌ Article not found and no suggestions available"

def process_user_message(session_key, message, chat_id, sender):
    """Process user message in thread"""
    try:
        with session_lock:
            session_data = user_sessions.get(session_key, {})
        
        # Get the target chat ID (group or personal)
        target_chat = chat_id
        
        # Handle Wikipedia suggestion selection
        if session_data.get('awaiting_wiki_selection'):
            choice = message.strip()
            suggestions = session_data.get('suggestions', [])
            
            if choice.isdigit() and 0 < int(choice) <= len(suggestions):
                selected_title = suggestions[int(choice)-1]
                with session_lock:
                    if session_key in user_sessions:
                        del user_sessions[session_key]
                
                send_whatsapp_message(f"⬇️ Downloading: {selected_title}", target_chat)
                pdf_path, error_msg = download_wikipedia_pdf(selected_title, target_chat)
                
                if pdf_path:
                    send_whatsapp_file(pdf_path, f"📚 *Wikipedia Article*\n{selected_title}", chat_id=target_chat)
                    os.remove(pdf_path)
                    os.rmdir(os.path.dirname(pdf_path))
                else:
                    send_whatsapp_message(f"❌ {error_msg}", target_chat)
            else:
                send_whatsapp_message("❌ Invalid selection. Please try again with /wikipdf", target_chat)
                with session_lock:
                    if session_key in user_sessions:
                        del user_sessions[session_key]
            return

        # Handle quality selection
        if session_data.get('awaiting_quality'):
            choice = message.strip()
            option_map = session_data.get('option_map', {})
            
            if choice in option_map:
                quality, format_id = option_map[choice]
                url = session_data['url']
                
                with session_lock:
                    if session_key in user_sessions:
                        del user_sessions[session_key]
                
                if quality == 'mp3' or '(Audio)' in quality:
                    send_whatsapp_message("⬇️ *Downloading MP3 audio...* 🎵", target_chat)
                    file_path, title_or_error = download_media(url, 'mp3')
                    if file_path:
                        send_whatsapp_file(file_path, f"🎵 *{title_or_error}*", is_video=False, chat_id=target_chat)
                        os.remove(file_path)
                        os.rmdir(os.path.dirname(file_path))
                    else:
                        error_msg = title_or_error if isinstance(title_or_error, str) else "❌ *Failed to download audio. Please try again.*"
                        send_whatsapp_message(error_msg, target_chat)
                else:
                    send_whatsapp_message(f"⬇️ *Downloading {quality} quality...* 🎬", target_chat)
                    file_path, title_or_error = download_media(url, quality, format_id)
                    if file_path:
                        send_whatsapp_file(file_path, f"🎥 *{title_or_error}*\n*Quality:* {quality}", is_video=True, chat_id=target_chat)
                        os.remove(file_path)
                        os.rmdir(os.path.dirname(file_path))
                    else:
                        error_msg = title_or_error if isinstance(title_or_error, str) else "❌ *Failed to download media. Please try again.*"
                        send_whatsapp_message(error_msg, target_chat)
            else:
                send_whatsapp_message("❌ *Invalid choice. Please select one of the available options.*", target_chat)
                with session_lock:
                    if session_key in user_sessions:
                        url = user_sessions[session_key]['url']
                send_quality_options(session_key, url, target_chat)
            return

        # Handle course selection
        if session_data.get('awaiting_course_selection'):
            choice = message.strip()
            option_map = session_data.get('option_map', {})
            
            if choice in option_map:
                folder_id = option_map[choice]
                folders = session_data['folders']
                folder_name = next((f['name'] for f in folders if f['id'] == folder_id), "Selected Course")
                
                with session_lock:
                    if session_key in user_sessions:
                        del user_sessions[session_key]
                
                folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
                send_whatsapp_message(f"📂 *{folder_name}*\n\n{folder_url}", target_chat)
            else:
                send_whatsapp_message("❌ *Invalid choice. Please select one of the available options.*", target_chat)
                with session_lock:
                    if session_key in user_sessions:
                        query = user_sessions[session_key].get('query', None)
                send_course_options(session_key, query, target_chat)
            return

        # Command handling
        if message.lower() in ['hi', 'hello', 'hey']:
            help_text = """👋 *Hello! Here's what I can do:*

📥 *Media Download:*
Simply paste any video URL (YouTube, Instagram, TikTok, etc.) to download
_(Max file size: 100MB)_

🔍 *Search:*
`/search [query]` - Search YouTube for videos

📚 *Courses:*
`/course [query]` - Search for courses
`/course all` - List all available courses

🎨 *Thumbnails:*
`/thumb [YouTube URL]` - Get YouTube video thumbnail

🏏 *Cricket Scores:*
`/cricket` - Get live cricket scores

⛅ *Weather:*
`/weather [city]` - Get current weather

📚 *Wikipedia:*
`/wikipdf [article]` - Get Wikipedia article as PDF"""

            # Add GLIF command only for admin in private chat
            if sender == ADMIN_NUMBER and not chat_id.endswith('@g.us'):
                help_text += "\n\n🔧 *Admin Commands:*\n`/glif [prompt]` - Generate custom thumbnail"

            help_text += "\n\nℹ️ *Help:*\n`/help` - Show this message"
            send_whatsapp_message(help_text, target_chat)
        
        elif message.lower().startswith(('/help', 'help', 'info')):
            help_text = """ℹ️ *Bot Help Menu* ℹ️

📥 *Media Download:*
Just send me a video URL from:
- YouTube
- Instagram
- TikTok
- Facebook
- And many more!
_(Maximum file size: 100MB)_

🔍 *Search Commands:*
`/search [query]` - Find YouTube videos

📚 *Course Access:*
`/course [name]` - Search courses
`/course all` - List all courses

🎨 *Thumbnail Tools:*
`/thumb [URL]` - Get YouTube thumbnail

🏏 *Cricket Scores:*
`/cricket` - Live cricket matches

⛅ *Weather Updates:*
`/weather [city]` - Current weather

📚 *Wikipedia Articles:*
`/wikipdf [article]` - Download as PDF"""

            # Add GLIF command only for admin in private chat
            if sender == ADMIN_NUMBER and not chat_id.endswith('@g.us'):
                help_text += "\n\n🔧 *Admin Commands:*\n`/glif [prompt]` - Generate custom thumbnail"

            help_text += "\n\nNeed more help? Contact admin!"
            send_whatsapp_message(help_text, target_chat)
        
        elif message.lower().startswith('/search '):
            query = message[8:].strip()
            if query:
                send_whatsapp_message(f"🔍 *Searching YouTube for:* _{query}_", target_chat)
                result = search_youtube(query)
                if result:
                    send_whatsapp_message(f"🎥 *{result['title']}*\n\n{result['url']}", target_chat)
                else:
                    send_whatsapp_message("❌ *No results found. Please try a different query.*", target_chat)
        
        elif message.lower().startswith('/thumb '):
            url = message[7:].strip()
            if is_youtube_url(url):
                send_whatsapp_message("🖼️ *Getting YouTube thumbnail...*", target_chat)
                thumbnail_url = get_youtube_thumbnail(url)
                if thumbnail_url:
                    response = requests.get(thumbnail_url)
                    temp_file = os.path.join(tempfile.gettempdir(), "yt_thumbnail.jpg")
                    with open(temp_file, 'wb') as f:
                        f.write(response.content)
                    send_whatsapp_file(temp_file, "🖼️ *YouTube Thumbnail*", chat_id=target_chat)
                    os.remove(temp_file)
                else:
                    send_whatsapp_message("❌ *Couldn't get thumbnail. Please check the URL.*", target_chat)
            else:
                send_whatsapp_message("❌ *Please provide a valid YouTube URL*", target_chat)
        
        elif message.lower().startswith('/course'):
            query = message[7:].strip()
            if not query:
                send_whatsapp_message("ℹ️ *Please specify a search query or* `all` *to list all courses*", target_chat)
            else:
                send_course_options(session_key, query if query.lower() != 'all' else None, target_chat)
        
        elif message.lower().startswith('/cricket'):
            send_whatsapp_message("🏏 Fetching live cricket scores...", target_chat)
            matches = get_live_cricket_scores()
            if matches:
                response_text = "🏏 *LIVE CRICKET SCORES*\n\n"
                for match in matches:
                    response_text += f"*{match['teams']}*\n"
                    response_text += f"📊 {match['score']}\n"
                    if 'won' in match['status'].lower():
                        response_text += f"🏆 {match['status']}\n"
                    elif 'live' in match['status'].lower():
                        response_text += f"🔴 {match['status']}\n"
                    else:
                        response_text += f"🟢 {match['status']}\n"
                    response_text += "-------------------------\n"
                response_text += "\n_Data from Cricbuzz_"
                send_whatsapp_message(response_text, target_chat)
            else:
                send_whatsapp_message("❌ No live matches found or unable to fetch scores", target_chat)
        
        elif message.lower().startswith('/weather '):
            city = message[9:].strip()
            if city:
                send_whatsapp_message(f"⛅ Fetching weather for {city}...", target_chat)
                weather_data = get_weather_data(city)
                if weather_data and weather_data.get('cod') == 200:
                    main = weather_data['main']
                    weather = weather_data['weather'][0]
                    sys = weather_data['sys']
                    
                    response_text = f"🌦️ *Weather for {weather_data['name']}, {sys['country']}*\n\n"
                    response_text += f"⏰ {datetime.fromtimestamp(weather_data['dt']).strftime('%A, %I:%M %p')}\n"
                    response_text += f"🌡️ Temp: {main['temp']}°C (Feels like {main['feels_like']}°C)\n"
                    response_text += f"☁️ {weather['description'].capitalize()}\n"
                    response_text += f"💧 Humidity: {main['humidity']}%\n"
                    response_text += f"🌬️ Wind: {weather_data['wind']['speed']} m/s\n"
                    response_text += "\n_Data from OpenWeatherMap_"
                    send_whatsapp_message(response_text, target_chat)
                else:
                    send_whatsapp_message(f"❌ Couldn't fetch weather for {city}. Check city name.", target_chat)
            else:
                send_whatsapp_message("ℹ️ Please specify a city (e.g. /weather London)", target_chat)
        
        elif message.lower().startswith('/wikipdf '):
            article = message[9:].strip()
            if article:
                send_whatsapp_message(f"📚 Downloading Wikipedia article: {article}", target_chat)
                pdf_path, error_msg = download_wikipedia_pdf(article, target_chat)
                
                if pdf_path:
                    send_whatsapp_file(pdf_path, f"📚 *Wikipedia Article*\n{article}", chat_id=target_chat)
                    os.remove(pdf_path)
                    os.rmdir(os.path.dirname(pdf_path))
                else:
                    send_whatsapp_message(f"❌ {error_msg}", target_chat)
            else:
                send_whatsapp_message("ℹ️ Please specify an article title (e.g. /wikipdf Python)", target_chat)
        
        # GLIF command (Admin only in private chat)
        elif message.lower().startswith('/glif ') and sender == ADMIN_NUMBER and not chat_id.endswith('@g.us'):
            prompt = message[6:].strip()
            if prompt:
                send_whatsapp_message("🔄 *Generating your thumbnail...* _(20-30 seconds)_", target_chat)
                result = generate_thumbnail(prompt)
                if result['status'] == 'success':
                    response = requests.get(result['image_url'])
                    temp_file = os.path.join(tempfile.gettempdir(), "thumbnail.jpg")
                    with open(temp_file, 'wb') as f:
                        f.write(response.content)
                    send_whatsapp_file(temp_file, f"🎨 *Thumbnail for:* _{prompt}_", chat_id=target_chat)
                    send_whatsapp_message(f"🔗 *Direct URL:*\n{result['image_url']}", target_chat)
                    os.remove(temp_file)
                else:
                    send_whatsapp_message("❌ *Failed to generate. Please try different keywords.*", target_chat)
        
        # Handle URLs
        elif any(proto in message.lower() for proto in ['http://', 'https://']):
            ensure_files()
            send_quality_options(session_key, message, target_chat)

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

        # Create unique session key and process in thread
        session_key = f"{chat_id}_{sender}"
        
        # Allow processing if:
        # 1. Message is in authorized group, or
        # 2. Message is from admin in personal chat
        if chat_id == AUTHORIZED_GROUP or (sender == ADMIN_NUMBER and not chat_id.endswith('@g.us')):
            executor.submit(process_user_message, session_key, message, chat_id, sender)
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
    ensure_files()
    
    logger.info(f"""
    ============================================
    WhatsApp Media Bot READY
    Responding to group: {AUTHORIZED_GROUP}
    And admin ({ADMIN_NUMBER}) in personal chat
    Ignoring messages from: {BOT_NUMBER}
    GreenAPI Instance: {GREEN_API['idInstance']}
    GLIF Thumbnails: Enabled (Admin only)
    Max file size: 100MB
    ============================================
    """)
    serve(app, host='0.0.0.0', port=8000)
