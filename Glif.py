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
import shutil

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
    """Get YouTube quality options with EXACT quality mapping"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': YT_COOKIES_FILE if os.path.exists(YT_COOKIES_FILE) else None,
            "extractor_args": {
                "youtube": {
                    "player_skip": ["configs"],
                    "player_client": ["ios", "android", "web_safari", "web"]
                }
            },
            "nocheckcertificate": True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or 'formats' not in info:
                return None
            
            # EXACT QUALITY MAPPING - Find best format for each quality
            quality_map = {}
            formats = info.get('formats', [])
            
            # Sort formats by quality (height) and bitrate
            video_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            video_formats.sort(key=lambda x: (x.get('height', 0), x.get('tbr', 0)), reverse=True)
            
            # Map qualities to specific format IDs
            quality_targets = {
                '144p': (140, 144),
                '360p': (230, 360),
                '480p': (370, 480),
                '720p': (550, 720),
                '1080p': (870, 1080)
            }
            
            for quality, (min_h, max_h) in quality_targets.items():
                for fmt in video_formats:
                    height = fmt.get('height', 0)
                    format_id = fmt.get('format_id', '')
                    # Find the best format in this quality range
                    if min_h <= height <= max_h:
                        if quality not in quality_map:
                            quality_map[quality] = format_id
                            break
            
            # Add best quality options
            quality_map['best'] = 'best'
            quality_map['mp3'] = 'bestaudio/best'
            
            logger.info(f"Available qualities mapped: {quality_map}")
            return quality_map
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

def download_media_with_quality(url, quality, format_id=None):
    """Download media with EXACT quality selection - FIXED VERSION"""
    temp_dir = tempfile.mkdtemp()
    downloaded_file_path = None
    
    try:
        # yt-dlp options with modern settings
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title).100s.%(ext)s'),
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'retries': 3,
            "extractor_args": {
                "youtube": {
                    "player_skip": ["configs"],
                    "player_client": ["ios", "android", "web_safari", "web"]
                }
            },
            "nocheckcertificate": True,
        }
        
        if cookies := get_cookies_for_url(url):
            ydl_opts['cookiefile'] = cookies
        
        # EXACT QUALITY SELECTION - FIXED LOGIC
        if quality == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        elif quality == 'best':
            # Use best available quality
            ydl_opts['format'] = 'best[height<=1080]'
        else:
            # USE SPECIFIC FORMAT ID FOR EXACT QUALITY
            if format_id and format_id != 'best':
                ydl_opts['format'] = format_id
            else:
                # Fallback to height-based selection
                height_map = {
                    '144p': 'best[height<=144]',
                    '360p': 'best[height<=360]',
                    '480p': 'best[height<=480]',
                    '720p': 'best[height<=720]',
                    '1080p': 'best[height<=1080]'
                }
                ydl_opts['format'] = height_map.get(quality, 'best')
        
        logger.info(f"Downloading with quality: {quality}, format: {ydl_opts['format']}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Find the downloaded file
            for file in os.listdir(temp_dir):
                if any(file.endswith(ext) for ext in ['.mp4', '.mp3', '.webm', '.m4a']):
                    downloaded_file_path = os.path.join(temp_dir, file)
                    break
            
            if not downloaded_file_path or not os.path.exists(downloaded_file_path):
                return None, "No file downloaded", None
            
            file_size = os.path.getsize(downloaded_file_path)
            
            # Check file size limit
            if file_size > 100 * 1024 * 1024:
                return None, "📛 *File size exceeds 100MB limit*", None
            
            title = info.get('title', 'Unknown Title')
            
            # For MP3, ensure proper extension
            if quality == 'mp3' and not downloaded_file_path.endswith('.mp3'):
                mp3_file = downloaded_file_path.rsplit('.', 1)[0] + '.mp3'
                if os.path.exists(mp3_file):
                    downloaded_file_path = mp3_file
                else:
                    # Convert to MP3 if needed
                    try:
                        subprocess.run([
                            'ffmpeg', '-i', downloaded_file_path, '-codec:a', 'libmp3lame', 
                            '-q:a', '2', mp3_file, '-y'
                        ], capture_output=True, timeout=30)
                        if os.path.exists(mp3_file):
                            downloaded_file_path = mp3_file
                    except Exception as e:
                        logger.error(f"MP3 conversion error: {str(e)}")
            
            return downloaded_file_path, title, temp_dir
            
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        # Cleanup on error
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return None, f"Download failed: {str(e)}", None

def cleanup_temp_files(file_path, temp_dir):
    """Clean up temporary files after sending"""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Removed file: {file_path}")
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info(f"Removed temp directory: {temp_dir}")
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")

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
        # Check if file exists before sending
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return False
            
        target_chat = chat_id if chat_id else AUTHORIZED_GROUP
        
        # Determine content type
        if is_video:
            content_type = 'video/mp4'
        elif file_path.endswith('.mp3'):
            content_type = 'audio/mpeg'
        elif file_path.endswith('.pdf'):
            content_type = 'application/pdf'
        else:
            content_type = 'video/mp4'  # Default for videos
            
        with open(file_path, 'rb') as file:
            files = {'file': (os.path.basename(file_path), file, content_type)}
            data = {'chatId': target_chat, 'caption': caption}
            
            response = requests.post(
                f"{GREEN_API['mediaUrl']}/waInstance{GREEN_API['idInstance']}/sendFileByUpload/{GREEN_API['apiToken']}",
                files=files,
                data=data,
                timeout=60  # Increased timeout for file upload
            )
            response.raise_for_status()
            logger.info(f"File sent to {target_chat}: {caption[:50]}...")
            return True
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Network connection error: {str(e)}")
        return False
    except requests.exceptions.Timeout as e:
        logger.error(f"Request timeout: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"File send error: {str(e)}")
        return False

def send_quality_options(session_key, url, chat_id=None):
    """Send available quality options"""
    send_whatsapp_message("🔍 *Checking available video qualities...*", chat_id)
    
    try:
        quality_map = get_available_qualities(url)
        if not quality_map:
            send_whatsapp_message("❌ *No qualities available for this video*", chat_id)
            return
        
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
            
            # Show available qualities in order
            quality_order = ['144p', '360p', '480p', '720p', '1080p', 'best', 'mp3']
            
            for qual in quality_order:
                if qual in quality_map:
                    if qual == 'mp3':
                        options_text += f"{option_number}. *MP3* _(Audio only)_ 🎵\n"
                        user_sessions[session_key]['option_map'][str(option_number)] = ('mp3', quality_map[qual])
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

def process_user_message(session_key, message, chat_id, sender):
    """Process user message in thread"""
    try:
        with session_lock:
            session_data = user_sessions.get(session_key, {})
        
        # Get the target chat ID (group or personal)
        target_chat = chat_id
        
        # Handle Wikipedia suggestion selection
        wiki_session_key = f"wiki_{chat_id}"
        with session_lock:
            wiki_session_data = user_sessions.get(wiki_session_key, {})
        
        if wiki_session_data.get('awaiting_wiki_selection'):
            choice = message.strip()
            suggestions = wiki_session_data.get('suggestions', [])
            
            if choice.isdigit() and 0 < int(choice) <= len(suggestions):
                selected_title = suggestions[int(choice)-1]
                with session_lock:
                    if wiki_session_key in user_sessions:
                        del user_sessions[wiki_session_key]
                
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
                    if wiki_session_key in user_sessions:
                        del user_sessions[wiki_session_key]
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
                
                # Submit download task to thread pool
                def download_task():
                    file_path = None
                    temp_dir = None
                    try:
                        if quality == 'mp3':
                            send_whatsapp_message("⬇️ *Downloading MP3 audio...* 🎵", target_chat)
                        else:
                            send_whatsapp_message(f"⬇️ *Downloading {quality} quality...* 🎬", target_chat)
                        
                        # Download the file
                        file_path, title_or_error, temp_dir = download_media_with_quality(url, quality, format_id)
                        
                        if file_path and os.path.exists(file_path):
                            logger.info(f"File downloaded successfully: {file_path}")
                            logger.info(f"File exists: {os.path.exists(file_path)}")
                            logger.info(f"File size: {os.path.getsize(file_path)} bytes")
                            
                            is_video = not file_path.endswith('.mp3')
                            quality_display = 'MP3' if not is_video else quality
                            caption = f"🎵 *{title_or_error}*" if not is_video else f"🎥 *{title_or_error}*\n*Quality:* {quality}"
                            
                            # Send the file
                            if send_whatsapp_file(file_path, caption, is_video=is_video, chat_id=target_chat):
                                logger.info(f"File sent successfully: {title_or_error}")
                            else:
                                send_whatsapp_message("❌ *Failed to send file - Network issue*", target_chat)
                        else:
                            error_msg = title_or_error if isinstance(title_or_error, str) else "❌ *Failed to download media*"
                            send_whatsapp_message(error_msg, target_chat)
                        
                    except Exception as e:
                        logger.error(f"Download task error: {str(e)}")
                        send_whatsapp_message("❌ *Download error occurred*", target_chat)
                    finally:
                        # Cleanup temporary files after sending
                        if file_path or temp_dir:
                            logger.info(f"Cleaning up files: {file_path}, {temp_dir}")
                            cleanup_temp_files(file_path, temp_dir)
                
                # Execute in thread pool
                executor.submit(download_task)
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
