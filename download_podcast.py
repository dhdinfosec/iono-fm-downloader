import subprocess
import sys
import importlib.util
import requests
from bs4 import BeautifulSoup
import feedparser
import re
import os
import json
import hashlib
import argparse
import logging
import time
import unicodedata
from functools import wraps
from urllib.parse import urljoin, urlparse
from datetime import datetime

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

try:
    import dateutil.parser
except ImportError:
    dateutil = None

module_map = {
    'requests': 'requests',
    'beautifulsoup4': 'bs4',
    'feedparser': 'feedparser',
    'tqdm': 'tqdm',
    'python-dateutil': 'dateutil'
}

def setup_logging(log_level='INFO'):
    """Setup logging to file and console."""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    logger = logging.getLogger(__name__)
    logger.setLevel(getattr(logging, log_level))
    
    if logger.handlers:
        return logger
    
    file_handler = logging.FileHandler('podcast_download.log')
    file_handler.setLevel(getattr(logging, log_level))
    file_handler.setFormatter(logging.Formatter(log_format))
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level))
    console_handler.setFormatter(logging.Formatter(log_format))
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

def retry_on_failure(max_retries=3, delay=1, backoff=2):
    """Retry decorator with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except requests.RequestException as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Failed after {max_retries} attempts: {e}")
                        raise
                    logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= backoff
            return None
        return wrapper
    return decorator

def load_config():
    """Load configuration from podcast_config.json if it exists."""
    config_file = 'podcast_config.json'
    default_config = {
        'download_dir': None,
        'max_retries': 3,
        'timeout': 30,
        'preferred_quality': 'medium',
        'preferred_format': 'auto',
        'log_level': 'INFO',
        'filename_max_length': 80
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                user_config = json.load(f)
                return {**default_config, **user_config}
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not load config file: {e}. Using defaults.")
    
    return default_config

def install_missing_modules():
    """Check and install required Python modules."""
    for pip_name, import_name in module_map.items():
        if importlib.util.find_spec(import_name) is None:
            if pip_name in ['tqdm', 'python-dateutil']:
                logger.warning(f"Optional module '{pip_name}' not found. Some features may be limited.")
                continue
            logger.info(f"Installing {pip_name}...")
            try:
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', pip_name])
                logger.info(f"Successfully installed {pip_name}")
            except subprocess.CalledProcessError:
                logger.error(f"Failed to install {pip_name}. Install manually with 'pip install {pip_name}'.")
                sys.exit(1)

def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Download podcast episodes from iono.fm.",
        epilog="Example: python download_podcast.py https://iono.fm/c/4 --force --short-names --dir bbc --recheck --log-level DEBUG"
    )
    parser.add_argument("channel_url", help="The iono.fm channel URL (e.g., https://iono.fm/c/4)")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--short-names", action="store_true", help="Use shorter og:title for filenames")
    parser.add_argument("--dir", help="Custom directory name for downloads (e.g., bbc)")
    parser.add_argument("--recheck", action="store_true", help="Force completeness check on all cached files")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help="Set logging level")
    args = parser.parse_args()

    if not args.channel_url.startswith('https://iono.fm/c/') or not args.channel_url.split('/')[-1].isdigit():
        parser.error("Channel URL must be in the format https://iono.fm/c/<number>")
    
    return args

def sanitize_filename(name, max_length=80):
    """Sanitize a string for use as a filename with Unicode normalization."""
    if not name:
        return "unnamed"
    
    normalized = unicodedata.normalize('NFKC', str(name))
    sanitized = re.sub(r'[^\w\s\-\.]', '', normalized)
    sanitized = re.sub(r'\s+', '_', sanitized.strip()).lower()
    return sanitized[:max_length].rstrip('_')

def extract_episode_number(text):
    """Enhanced episode number extraction."""
    if not text:
        return None
    
    patterns = [
        r'Episode\s+(\d+)', r'Ep\.?\s*(\d+)', r'#(\d+)', r'Part\s+(\d+)',
        r'(\d+):00\s+nuus', r'S\d+E(\d+)', r'Season\s+\d+\s+Episode\s+(\d+)',
        r'\b(\d{1,3})\b(?=\s*(?:-|–|:|$))', r'^(\d+)\b', r'\b(\d+)$'
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            numbers = [int(match) for match in matches if match.isdigit() and 1 <= int(match) <= 9999]
            if numbers:
                return numbers[0]
    return None

def parse_publication_date(pub_date_str):
    """Parse various date formats robustly."""
    if not pub_date_str:
        return datetime.min
    
    try:
        if dateutil:
            return dateutil.parser.parse(pub_date_str)
        return datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %z')
    except (ValueError, TypeError):
        logger.debug(f"Could not parse date: {pub_date_str}")
        return datetime.min

def extract_episode_metadata(soup, rss_ep_num, rss_title):
    """Extract episode number, description, and og:title from HTML."""
    page_title_tag = soup.find('meta', attrs={'property': 'og:title'})
    page_title = page_title_tag.get('content', '') if page_title_tag else (soup.title.string.strip() if soup.title else '')
    
    html_ep_num = extract_episode_number(page_title)
    if html_ep_num is None:
        logger.debug(f"Could not extract episode number from HTML title: '{page_title}'")
        html_ep_num = rss_ep_num
    elif html_ep_num != rss_ep_num and rss_ep_num is not None:
        logger.debug(f"HTML episode number ({html_ep_num}) differs from RSS ({rss_ep_num}). Using HTML.")

    meta_desc = soup.find('meta', attrs={'name': 'description'})
    description = meta_desc.get('content') if meta_desc else page_title

    if page_title and page_title != rss_title:
        logger.debug(f"HTML title ('{page_title}') differs from RSS title ('{rss_title}')")

    return html_ep_num, description, page_title

def extract_author(soup):
    """Extract author from <meta name="author">."""
    author_meta = soup.find('meta', attrs={'name': 'author'})
    author = author_meta.get('content') if author_meta else None
    logger.debug(f"Extracted author: {author or 'None (will use podcast name)'}")
    return author

def get_file_extension(url, content_type=None, preferred_format='auto'):
    """Determine file extension from URL, Content-Type, or user preference."""
    if preferred_format != 'auto':
        logger.debug(f"Using user-specified format: {preferred_format}")
        return f'.{preferred_format}'
    
    if content_type:
        content_type_lower = content_type.lower()
        logger.debug(f"Content-Type: {content_type_lower}")
        if 'audio/mpeg' in content_type_lower or 'audio/mp3' in content_type_lower:
            return '.mp3'
        elif 'audio/mp4' in content_type_lower or 'audio/m4a' in content_type_lower:
            return '.m4a'
    
    url_lower = url.lower()
    logger.debug(f"URL for extension check: {url_lower}")
    if '.mp3' in url_lower:
        return '.mp3'
    elif '.m4a' in url_lower:
        return '.m4a'
    
    logger.debug("Falling back to default extension: .m4a")
    return '.m4a'

def get_quality_preference_order(preferred_quality):
    """Get quality preference order."""
    quality_orders = {
        'high': ['high', 'medium', 'low'],
        'medium': ['medium', 'high', 'low'],
        'low': ['low', 'medium', 'high']
    }
    return quality_orders.get(preferred_quality, quality_orders['medium'])

@retry_on_failure(max_retries=3, delay=1, backoff=2)
def extract_audio_url(soup, rss_entry, config):
    """Extract audio URL with quality preference."""
    quality_order = get_quality_preference_order(config['preferred_quality'])
    
    if rss_entry.get('enclosures'):
        enclosure_urls = []
        for enclosure in rss_entry.enclosures:
            url = enclosure.get('url', '')
            if url and ('mp3' in url.lower() or 'm4a' in url.lower()):
                enclosure_urls.append(url)
        
        for quality in quality_order:
            for url in enclosure_urls:
                if quality in url.lower():
                    logger.debug(f"Selected enclosure URL with quality {quality}: {url}")
                    return url
        if enclosure_urls:
            logger.debug(f"No preferred quality found, using first enclosure: {enclosure_urls[0]}")
            return enclosure_urls[0]
    
    og_audio = soup.find('meta', attrs={'property': 'og:audio'})
    if og_audio:
        logger.debug(f"Using og:audio URL: {og_audio.get('content')}")
        return og_audio.get('content')
    
    audio_tag = soup.find('audio')
    if audio_tag and audio_tag.get('src'):
        logger.debug(f"Using audio tag URL: {audio_tag['src']}")
        return audio_tag['src']
    
    scripts = soup.find_all('script')
    for script in scripts:
        if not script.string:
            continue
        if 'STATE_FROM_SERVER' in script.string:
            for quality in quality_order:
                pattern = rf'"url":"https://dl\.iono\.fm/epi/prov_\d+/epi_\d+_{quality}\.m4a"'
                match = re.search(pattern, script.string)
                if match:
                    url = match.group(0).replace('\\"', '"').replace('\\/', '/')
                    url = re.search(r'https://dl\.iono\.fm/epi/prov_\d+/epi_\d+_\w+\.m4a', url).group(0)
                    logger.debug(f"Found script URL with quality {quality}: {url}")
                    return url
        
        if 'dl.iono.fm' in script.string:
            for quality in quality_order:
                pattern = rf'https://dl\.iono\.fm/epi/prov_\d+/epi_\d+_{quality}\.m4a'
                match = re.search(pattern, script.string)
                if match:
                    logger.debug(f"Found script URL with quality {quality}: {match.group(0)}")
                    return match.group(0)
    
    text = str(soup)
    match = re.search(r'https://dl\.iono\.fm/epi/prov_\d+/epi_\d+_\w+\.m4a', text)
    if match:
        logger.debug(f"Found fallback URL in page text: {match.group(0)}")
        return match.group(0)
    
    logger.debug("No audio URL found")
    return None

@retry_on_failure(max_retries=3, delay=1, backoff=2)
def get_audio_url_and_metadata(episode_page_url, rss_ep_num, rss_title, rss_entry, config):
    """Fetch episode page and extract audio URL and metadata."""
    try:
        response = requests.get(episode_page_url, timeout=config['timeout'])
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch {episode_page_url}: {e}")
        logger.info("Falling back to RSS enclosure.")
        enclosure_url = None
        if rss_entry.get('enclosures'):
            for enclosure in rss_entry.enclosures:
                url = enclosure.get('url', '')
                if url and ('mp3' in url.lower() or 'm4a' in url.lower()):
                    enclosure_url = url
                    logger.debug(f"Using RSS enclosure fallback: {enclosure_url}")
                    break
        return enclosure_url, rss_ep_num, rss_title, rss_title, None

    soup = BeautifulSoup(response.text, 'html.parser')
    audio_url = extract_audio_url(soup, rss_entry, config)
    html_ep_num, description, og_title = extract_episode_metadata(soup, rss_ep_num, rss_title)
    author = extract_author(soup)
    
    if not audio_url and rss_entry.get('enclosures'):
        for enclosure in rss_entry.enclosures:
            url = enclosure.get('url', '')
            if url and ('mp3' in url.lower() or 'm4a' in url.lower()):
                audio_url = url
                logger.info(f"Using RSS enclosure URL: {audio_url}")
                break
    
    if not audio_url:
        logger.error(f"Failed to find audio URL for {episode_page_url}")

    return audio_url, html_ep_num, description, og_title, author

def compute_file_hash(filepath):
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except IOError as e:
        logger.error(f"Could not compute hash for {filepath}: {e}")
        return None

@retry_on_failure(max_retries=3, delay=1, backoff=2)
def check_file_completeness(url, filepath, rss_enclosure_length=None):
    """Check if a file exists and is complete, trying both .mp3 and .m4a if needed."""
    possible_extensions = ['.mp3', '.m4a']
    base_filepath = filepath.rsplit('.', 1)[0]  # Remove extension
    existing_filepath = None
    local_size = None

    # Check for existing file with any extension
    for ext in possible_extensions:
        test_filepath = base_filepath + ext
        if os.path.exists(test_filepath):
            existing_filepath = test_filepath
            local_size = os.path.getsize(test_filepath)
            logger.debug(f"Found existing file: {existing_filepath} ({local_size:,} bytes)")
            break

    if not existing_filepath:
        logger.debug(f"No file found for {filepath} with extensions {possible_extensions}")
        return False, None, "Downloading new file"
    
    if local_size == 0:
        logger.debug(f"Empty file detected: {existing_filepath}")
        return False, None, "Redownloading empty file"
    
    try:
        response = requests.head(url, allow_redirects=True, timeout=10)
        response.raise_for_status()
        
        source_size = int(response.headers.get('Content-Length', 0))
        server_hash = response.headers.get('ETag', '').strip('"')

        if server_hash:
            local_hash = compute_file_hash(existing_filepath)
            if local_hash and local_hash == server_hash:
                return True, local_size, f"Skipping complete file (hash match): {os.path.basename(existing_filepath)} ({local_size:,} bytes)"
            else:
                return False, local_size, f"Redownloading incomplete file (hash mismatch): {os.path.basename(existing_filepath)} (local: {local_size:,} bytes, expected: {source_size:,} bytes)"
        
        elif source_size > 0:
            if local_size == source_size:
                return True, local_size, f"Skipping complete file: {os.path.basename(existing_filepath)} ({local_size:,} bytes)"
            else:
                return False, local_size, f"Redownloading incomplete file (size mismatch): {os.path.basename(existing_filepath)} (local: {local_size:,} bytes, expected: {source_size:,} bytes)"
        
        elif rss_enclosure_length and rss_enclosure_length > 0:
            if local_size == rss_enclosure_length:
                return True, local_size, f"Skipping complete file (RSS match): {os.path.basename(existing_filepath)} ({local_size:,} bytes)"
            else:
                return False, local_size, f"Redownloading incomplete file (RSS mismatch): {os.path.basename(existing_filepath)} (local: {local_size:,} bytes, expected: {rss_enclosure_length:,} bytes)"
        
        else:
            logger.debug(f"Cannot verify completeness for {existing_filepath}: no server size or hash available")
            return False, local_size, f"Cannot verify completeness: {os.path.basename(existing_filepath)} (local: {local_size:,} bytes)"
            
    except requests.RequestException as e:
        logger.debug(f"Could not check source for {url}: {e}")
        return False, local_size, f"Cannot verify completeness (network error): {os.path.basename(existing_filepath)} (local: {local_size:,} bytes)"

@retry_on_failure(max_retries=3, delay=1, backoff=2)
def download_file_with_resume(url, filepath, config):
    """Download with resume capability."""
    headers = {}
    initial_pos = 0
    progress_interval = 1048576  # 1MB intervals for non-tqdm progress
    
    if os.path.exists(filepath):
        initial_pos = os.path.getsize(filepath)
        if initial_pos > 0:
            headers['Range'] = f'bytes={initial_pos}-'
            logger.info(f"Resuming download from byte {initial_pos:,}")
    
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=config['timeout'])
        if response.status_code == 416:
            logger.info(f"File appears complete: {os.path.basename(filepath)}")
            return
        
        response.raise_for_status()
        
        content_length = response.headers.get('Content-Length')
        total_size = int(content_length) + initial_pos if content_length else None
        
        mode = 'ab' if initial_pos > 0 else 'wb'
        
        with open(filepath, mode) as f:
            if tqdm and total_size:
                with tqdm(
                    total=total_size, 
                    initial=initial_pos, 
                    unit='B', 
                    unit_scale=True,
                    desc=os.path.basename(filepath)
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
            else:
                bytes_downloaded = initial_pos
                last_reported = initial_pos
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        bytes_downloaded += len(chunk)
                        if total_size and (bytes_downloaded - last_reported >= progress_interval or bytes_downloaded == total_size):
                            percent = (bytes_downloaded / total_size) * 100
                            logger.info(f"Progress for {os.path.basename(filepath)}: {percent:.1f}% ({bytes_downloaded:,}/{total_size:,} bytes)")
                            last_reported = bytes_downloaded
        
        final_size = os.path.getsize(filepath)
        logger.info(f"Downloaded: {os.path.basename(filepath)} ({final_size:,} bytes)")
        
    except (requests.RequestException, IOError) as e:
        logger.error(f"Download failed for {url}: {e}")
        raise

def download_file(url, filepath, rss_enclosure_length=None, recheck=False, config=None):
    """Download a file if it doesn't exist or is incomplete."""
    is_complete, local_size, message = check_file_completeness(url, filepath, rss_enclosure_length)
    
    if is_complete and not recheck:
        logger.info(message)
        return
    
    logger.info(message)
    download_file_with_resume(url, filepath, config)

def main():
    """Main function to download podcast series from iono.fm."""
    config = load_config()
    
    args = parse_arguments()
    config['log_level'] = args.log_level
    global logger
    logger = setup_logging(config['log_level'])
    
    install_missing_modules()
    
    channel_id = args.channel_url.split('/')[-1]
    rss_urls = [
        f'https://iono.fm/rss/chan/{channel_id}',
        f'https://iono.fm/rss/prov/{channel_id}'
    ]

    feed = None
    for rss_url in rss_urls:
        logger.info(f"Fetching RSS feed from {rss_url}...")
        try:
            feed = feedparser.parse(rss_url)
            if feed.feed.get('title'):
                break
            logger.warning(f"No podcast name found in {rss_url}. Trying next feed...")
        except Exception as e:
            logger.error(f"Failed to parse {rss_url}: {e}")
    
    if not feed or not feed.feed.get('title'):
        logger.error(f"Could not retrieve podcast name from RSS feeds. Check the channel URL.")
        sys.exit(2)

    podcast_name = feed.feed.title
    logger.info(f"Podcast/Series: {podcast_name}")

    download_dir = None
    cache_file = None
    cache = {}

    episodes = []
    for entry in feed.entries:
        title = entry.title
        rss_ep_num = extract_episode_number(title)
        link = entry.link
        episode_id = link.split('/')[-1]
        pub_date = entry.get('published', '')
        enclosure_length = None
        enclosure_url = None
        if entry.get('enclosures'):
            for enclosure in entry.enclosures:
                url = enclosure.get('url', '')
                if url and ('mp3' in url.lower() or 'm4a' in url.lower()):
                    enclosure_url = url
                    enclosure_length = int(enclosure.get('length', 0)) if enclosure.get('length') else None
                    break
        episodes.append((rss_ep_num, title, link, episode_id, pub_date, enclosure_length, enclosure_url, entry))
    
    logger.info(f"Found {len(episodes)} episodes for {podcast_name}")

    try:
        processed_episodes = []
        for rss_ep_num, title, ep_url, episode_id, pub_date, enclosure_length, enclosure_url, entry in episodes:
            if download_dir is None:
                audio_url, html_ep_num, description, og_title, author = get_audio_url_and_metadata(ep_url, rss_ep_num, title, entry, config)
                download_dir = sanitize_filename(args.dir or author or podcast_name, config['filename_max_length'])
                cache_file = os.path.join(download_dir, 'cache.json')
                os.makedirs(download_dir, exist_ok=True)
                
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, 'r') as f:
                            cache = json.load(f)
                    except (json.JSONDecodeError, IOError):
                        logger.warning("Corrupted or inaccessible cache file. Starting fresh.")
                        cache = {}

            if ep_url in cache and not args.recheck:
                data = cache.get(ep_url, {})
                required_keys = ['html_ep_num', 'audio_url', 'description']
                if all(key in data for key in required_keys):
                    processed_episodes.append((
                        data['html_ep_num'], data['title'], ep_url, data['audio_url'],
                        data['description'], episode_id, data.get('pub_date', ''),
                        data.get('enclosure_length')
                    ))
                    logger.debug(f"Using cached episode data: {title}")
                    continue
            
            logger.info(f"Processing: {title}")
            if pub_date:
                logger.debug(f"Published: {pub_date}")
            if enclosure_url:
                logger.debug(f"RSS enclosure: {enclosure_url}")
            
            audio_url, html_ep_num, description, og_title, _ = get_audio_url_and_metadata(ep_url, rss_ep_num, title, entry, config)
            if not audio_url:
                logger.error(f"Skipping episode (no audio URL): {title}")
                continue
            
            cache[ep_url] = {
                'html_ep_num': html_ep_num,
                'title': title,
                'audio_url': audio_url,
                'description': description,
                'episode_id': episode_id,
                'pub_date': pub_date,
                'enclosure_length': enclosure_length
            }
            
            try:
                with open(cache_file, 'w') as f:
                    json.dump(cache, f, indent=2)
            except IOError as e:
                logger.warning(f"Could not save cache: {e}")
            
            processed_episodes.append((html_ep_num, title, ep_url, audio_url, description, episode_id, pub_date, enclosure_length))

        processed_episodes.sort(key=lambda x: (
            x[0] if x[0] is not None else float('inf'),
            parse_publication_date(x[6]),
            x[5]
        ))
        logger.info(f"Sorted {len(processed_episodes)} episodes")

        if not args.force:
            try:
                response = input(f"Download all episodes to '{download_dir}'? [y/N]: ").strip().lower()
            except KeyboardInterrupt:
                logger.info("Cancelled by user")
                sys.exit(3)
            if response != 'y':
                logger.info("Download cancelled")
                sys.exit(3)

        success_count = 0
        for html_ep_num, title, ep_url, audio_url, description, episode_id, pub_date, enclosure_length in processed_episodes:
            try:
                content_type = None
                try:
                    head_response = requests.head(audio_url, allow_redirects=True, timeout=config['timeout'])
                    content_type = head_response.headers.get('Content-Type', '')
                except requests.RequestException:
                    logger.debug(f"Could not fetch Content-Type for {audio_url}")
                
                ext = get_file_extension(audio_url, content_type, config['preferred_format'])
                name_source = og_title if args.short_names or (description and len(description) > config['filename_max_length']) else description
                filename = f"{sanitize_filename(name_source, config['filename_max_length'])}_{episode_id}{ext}"
                filepath = os.path.join(download_dir, filename)
                
                if not os.path.exists(filepath):
                    logger.info(f"Cache miss for {ep_url}; downloading new file")
                download_file(audio_url, filepath, enclosure_length, args.recheck, config)
                logger.info(f"Saved: {filename}")
                success_count += 1
                
            except Exception as e:
                logger.error(f"Failed to download {title}: {e}")
                continue

        logger.info(f"Successfully downloaded {success_count}/{len(processed_episodes)} episodes")

    except KeyboardInterrupt:
        logger.info(f"Download interrupted. Partial downloads may be in '{download_dir}'")
        sys.exit(4)

    logger.info(f"All done! Files are in '{download_dir}'")
    sys.exit(0)

if __name__ == "__main__":
    main()
