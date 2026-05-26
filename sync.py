#!/usr/bin/env python3
import os
import sys
import re
import json
import hashlib
import urllib.request
import urllib.parse
import time
from datetime import datetime
import shutil

# Check if required modules are installed
try:
    import requests
except ImportError:
    print("[-] Error: 'requests' package is not installed.")
    print("    Please run: pip install -r requirements.txt")
    sys.exit(1)

try:
    from garminconnect import Garmin, GarminConnectConnectionError
except ImportError:
    print("[-] Error: 'garminconnect' package is not installed.")
    print("    Please run: pip install -r requirements.txt")
    sys.exit(1)

try:
    import fitparse
except ImportError:
    print("[-] Error: 'fitparse' package is not installed.")
    print("    Please run: pip install -r requirements.txt")
    sys.exit(1)

try:
    import gpxpy
except ImportError:
    print("[-] Error: 'gpxpy' package is not installed.")
    print("    Please run: pip install -r requirements.txt")
    sys.exit(1)


# Constants
CONFIG_FILE = "config.json"
HISTORY_FILE = "sync_history.json"
LOCK_FILE = "sync.lock"
GEOCODE_CACHE_FILE = "geocode_cache.json"

# In-memory geocoding cache to minimize Nominatim API hits
GEOCODE_CACHE = {}


class IGPSPORTClient:
    """Client for fetching and managing activities on app.igpsport.com."""
    
    BASE_URL = "https://prod.zh.igpsport.com/service/"
    LOGIN_URL = BASE_URL + "auth/account/login"
    ACTIVITY_URL = BASE_URL + "web-gateway/web-analyze/activity/"
    QUERY_URL = ACTIVITY_URL + "queryMyActivity"
    DOWNLOAD_URL = ACTIVITY_URL + "getDownloadUrl/"

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.token = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://app.igpsport.com",
            "Referer": "https://app.igpsport.com/"
        })

    def update_base_url(self, base):
        """Updates all endpoints dynamically when switching backends."""
        self.BASE_URL = base
        self.LOGIN_URL = base + "auth/account/login"
        self.ACTIVITY_URL = base + "web-gateway/web-analyze/activity/"
        self.QUERY_URL = self.ACTIVITY_URL + "queryMyActivity"
        self.DOWNLOAD_URL = self.ACTIVITY_URL + "getDownloadUrl/"

    def login(self):
        """Authenticates with iGPSPORT and retrieves access token. Fallbacks to international backend if 403 Forbidden is received."""
        if not self.username or not self.password:
            raise ValueError("iGPSPORT username or password not provided in config.")
            
        req = {
            "appId": "igpsport-web",
            "username": self.username,
            "password": self.password,
        }
        
        # Candidate backends (Chinese domestic vs Global/International)
        backends = [
            "https://prod.zh.igpsport.com/service/",
            "https://prod.igpsport.com/service/"
        ]
        
        last_err = None
        for base in backends:
            login_url = base + "auth/account/login"
            try:
                rsp = self.session.post(login_url, json=req)
                if rsp.status_code == 403:
                    raise Exception("HTTP 403 Forbidden (WAF restriction)")
                if not rsp.ok:
                    raise Exception(f"HTTP error {rsp.status_code}: {rsp.reason}")
                ret = rsp.json()
                if ret.get("code") != 0 and ret.get("Code") != 0:
                    msg = ret.get("message") or ret.get("Message") or "Unknown error"
                    raise Exception(f"Login failed: {msg}")
                    
                access_token = ret.get("data", {}).get("access_token", "")
                if not access_token:
                    raise Exception("Access token missing in login response.")
                    
                self.token = access_token
                self.update_base_url(base)
                self.session.headers.update({"Authorization": "Bearer " + access_token})
                return True
            except Exception as e:
                print(f"[i] Failed login attempt via {base}: {e}")
                last_err = e
                
        raise Exception(f"iGPSPORT login failed on all backends. Last error: {last_err}")

    def get_activities(self, page_no=1, page_size=20):
        """Retrieves user activity list from iGPSPORT."""
        if not self.token:
            self.login()
            
        params = {
            "pageNo": str(page_no),
            "pageSize": str(page_size),
            "sort": "1",
            "reqType": "0"  # 0 for FIT, 1 for GPX
        }
        try:
            rsp = self.session.get(self.QUERY_URL, params=params)
            if not rsp.ok:
                raise Exception(f"HTTP error {rsp.status_code}: {rsp.reason}")
            ret = rsp.json()
            if ret.get("code") != 0 and ret.get("Code") != 0:
                msg = ret.get("message") or ret.get("Message") or "Unknown error"
                raise Exception(f"Query failed: {msg}")
            return ret
        except Exception as e:
            print(f"[-] Failed to fetch iGPSPORT activities: {e}")
            raise

    def get_download_url(self, ride_id):
        """Gets the FIT file download URL for a specific ride ID."""
        if not self.token:
            self.login()
            
        try:
            rsp = self.session.get(f"{self.DOWNLOAD_URL}{ride_id}")
            if not rsp.ok:
                raise Exception(f"HTTP error {rsp.status_code}: {rsp.reason}")
            ret = rsp.json()
            if ret.get("code") != 0 and ret.get("Code") != 0:
                msg = ret.get("message") or ret.get("Message") or "Unknown error"
                raise Exception(f"Get download URL failed: {msg}")
            return ret.get("data", "")
        except Exception as e:
            print(f"[-] Failed to retrieve download URL for ride {ride_id}: {e}")
            raise

    def download_activity(self, ride_id, dest_folder):
        """Downloads the activity file and saves it in the destination folder."""
        file_path = os.path.join(dest_folder, f"igpsport_{ride_id}.fit")
        try:
            download_url = self.get_download_url(ride_id)
            if not download_url:
                raise Exception("No download URL returned by iGPSPORT.")
                
            rsp = self.session.get(download_url)
            if not rsp.ok:
                raise Exception(f"HTTP error {rsp.status_code} downloading file: {rsp.reason}")
                
            with open(file_path, "wb") as f:
                f.write(rsp.content)
            return file_path
        except Exception as e:
            print(f"[-] Failed to download activity {ride_id}: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)
            raise

    def delete_activity(self, ride_id):
        """Attempts to delete the activity using multiple candidate endpoints (reverse-engineered)."""
        if not self.token:
            self.login()
            
        # Candidate URLs
        candidates = [
            (f"{self.ACTIVITY_URL}delete", {"rideId": ride_id}),
            (f"{self.ACTIVITY_URL}delete", {"rideId": str(ride_id)}),
            (f"{self.ACTIVITY_URL}deleteActivity", {"rideId": ride_id}),
            (f"{self.ACTIVITY_URL}deleteMyActivity", {"rideId": ride_id}),
            (f"{self.ACTIVITY_URL}delete", {"id": ride_id}),
        ]
        
        errors = []
        for url, payload in candidates:
            try:
                rsp = self.session.post(url, json=payload)
                if rsp.status_code == 200:
                    ret = rsp.json()
                    if ret.get("code") == 0 or ret.get("Code") == 0:
                        print(f"[✓] Activity {ride_id} successfully deleted from iGPSPORT.")
                        return True
                    else:
                        errors.append(f"Endpoint {url} returned API error code: {ret}")
                else:
                    errors.append(f"Endpoint {url} returned HTTP status {rsp.status_code}")
            except Exception as e:
                errors.append(f"Endpoint {url} raised exception: {e}")
                
        print(f"[-] Failed to delete activity {ride_id} from iGPSPORT cloud. Tried all candidates.")
        for err in errors:
            print(f"    - {err}")
        return False


def load_config():
    """Loads configuration from config.json."""
    if not os.path.exists(CONFIG_FILE):
        print(f"[-] Configuration file '{CONFIG_FILE}' not found.")
        print(f"    Please copy 'config.template.json' to '{CONFIG_FILE}' and fill in your details.")
        sys.exit(1)
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        # Validate required fields
        required = ["garmin_email", "garmin_password", "watch_folder"]
        missing = [field for field in required if not config.get(field)]
        if missing:
            print(f"[-] Invalid configuration. Missing fields: {', '.join(missing)}")
            sys.exit(1)
            
        return config
    except Exception as e:
        print(f"[-] Error loading configuration: {e}")
        sys.exit(1)


def load_history():
    """Loads sync history from sync_history.json."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[i] Failed to load history, starting fresh: {e}")
    return {}


def save_history(history):
    """Saves sync history to sync_history.json."""
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"[-] Error saving history: {e}")


def load_geocode_cache():
    """Loads geocode cache from geocode_cache.json."""
    global GEOCODE_CACHE
    if os.path.exists(GEOCODE_CACHE_FILE):
        try:
            with open(GEOCODE_CACHE_FILE, 'r') as f:
                GEOCODE_CACHE = json.load(f)
        except Exception as e:
            print(f"[i] Failed to load geocode cache: {e}")


def save_geocode_cache():
    """Saves geocode cache to geocode_cache.json."""
    try:
        with open(GEOCODE_CACHE_FILE, 'w') as f:
            json.dump(GEOCODE_CACHE, f, indent=2)
    except Exception as e:
        print(f"[-] Error saving geocode cache: {e}")


def acquire_lock():
    """Ensures only one instance of the script runs at a time."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            # Check if process is still running on macOS
            os.kill(pid, 0)
            print(f"[-] Another instance (PID {pid}) is already running.")
            sys.exit(0)
        except (OSError, ValueError):
            # Process not running, stale lock file
            pass
            
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))


def release_lock():
    """Releases the file lock on exit."""
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass


def compute_md5(file_path):
    """Computes the MD5 checksum of a file."""
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def semicircles_to_degrees(semicircles):
    """Converts semicircles coordinates (used in FIT files) to degrees."""
    if semicircles is None:
        return None
    return semicircles * (180.0 / 2147483648.0)


def extract_fit_data(file_path):
    """Extracts start coordinate, end coordinate, and start time from a FIT file."""
    try:
        fitfile = fitparse.FitFile(file_path)
    except Exception as e:
        print(f"[-] Failed to parse FIT file '{file_path}': {e}")
        return None, None, None

    start_coord = None
    end_coord = None
    start_time = None

    # Track coordinate sequence to find first and last valid points
    coords = []
    
    # 1. Parse records for coordinates
    for record in fitfile.get_messages('record'):
        lat = record.get_value('position_lat')
        lon = record.get_value('position_long')
        if lat is not None and lon is not None:
            lat_deg = semicircles_to_degrees(lat)
            lon_deg = semicircles_to_degrees(lon)
            coords.append((lat_deg, lon_deg))
            
    if coords:
        start_coord = coords[0]
        end_coord = coords[-1]

    # 2. Extract start time and fallback coordinates from session message
    for session in fitfile.get_messages('session'):
        if start_time is None:
            start_time = session.get_value('start_time')
            
        if start_coord is None:
            s_lat = session.get_value('start_position_lat')
            s_lon = session.get_value('start_position_long')
            if s_lat is not None and s_lon is not None:
                start_coord = (semicircles_to_degrees(s_lat), semicircles_to_degrees(s_lon))
                end_coord = start_coord  # Fallback

    # 3. Fallback start time search in other messages
    if start_time is None:
        for record in fitfile.get_messages('record'):
            timestamp = record.get_value('timestamp')
            if timestamp:
                start_time = timestamp
                break

    return start_coord, end_coord, start_time


def extract_gpx_data(file_path):
    """Extracts start coordinate, end coordinate, and start time from a GPX file."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            gpx = gpxpy.parse(f)
    except Exception as e:
        print(f"[-] Failed to parse GPX file '{file_path}': {e}")
        return None, None, None

    start_coord = None
    end_coord = None
    start_time = None

    all_points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                if point.latitude is not None and point.longitude is not None:
                    all_points.append(point)

    if all_points:
        start_pt = all_points[0]
        end_pt = all_points[-1]
        start_coord = (start_pt.latitude, start_pt.longitude)
        end_coord = (end_pt.latitude, end_pt.longitude)
        
        # Look for the first timestamp in points
        for pt in all_points:
            if pt.time:
                start_time = pt.time
                break

    # Fallback start time from file metadata
    if start_time is None and gpx.time:
        start_time = gpx.time

    return start_coord, end_coord, start_time


def reverse_geocode(lat, lon):
    """Queries Nominatim OpenStreetMap API to find the town/city name. Uses local caching."""
    if lat is None or lon is None:
        return None

    # Round coordinates to 3 decimal places to increase cache hits for nearby start/end points
    lat_key = f"{lat:.3f}"
    lon_key = f"{lon:.3f}"
    cache_key = f"{lat_key},{lon_key}"

    if cache_key in GEOCODE_CACHE:
        return GEOCODE_CACHE[cache_key]

    # Rate limiting: Sleep for 1.1s before requesting OSM Nominatim (max 1 req/sec policy)
    time.sleep(1.1)

    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=13&addressdetails=1"
    headers = {
        'User-Agent': 'IGPSportSync/1.0 (sven.koerner.dev.sync@aleph-alpha.de)'
    }
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            address = data.get('address', {})
            
            # Find the best administrative unit representation of a town/city
            keys_to_try = [
                'city', 'town', 'village', 'hamlet', 'suburb', 'borough',
                'municipality', 'city_district', 'neighbourhood', 'quarter',
                'local_administrative_area', 'county', 'state'
            ]
            
            place_name = None
            for key in keys_to_try:
                val = address.get(key)
                if val:
                    place_name = val
                    break
                    
            if not place_name:
                # Last resort fallback to first element of display_name
                display_name = data.get('display_name', '')
                if display_name:
                    place_name = display_name.split(',')[0].strip()

            if place_name:
                GEOCODE_CACHE[cache_key] = place_name
                save_geocode_cache()
                return place_name
                
    except Exception as e:
        print(f"[!] Geocoding error for ({lat}, {lon}): {e}")
        
    return None


def generate_tour_name(start_coord, end_coord):
    """Generates a human-friendly tour name based on geocoding."""
    start_town = None
    end_town = None

    if start_coord:
        start_town = reverse_geocode(start_coord[0], start_coord[1])
    if end_coord:
        end_town = reverse_geocode(end_coord[0], end_coord[1])

    if start_town and end_town:
        if start_town == end_town:
            return f"Ride in {start_town}"
        return f"Ride from {start_town} to {end_town}"
    elif start_town:
        return f"Ride from {start_town}"
    elif end_town:
        return f"Ride to {end_town}"
    else:
        return "Bike Ride"


def sanitize_filename(name):
    """Sanitizes strings for safe filenames."""
    # Strip leading/trailing spaces first
    name = name.strip()
    name = name.replace(' ', '_')
    # Keep alphanumeric, underscores, and hyphens
    name = re.sub(r'[^\w\-]', '', name)
    # Deduplicate underscores
    name = re.sub(r'_+', '_', name)
    # Strip leading/trailing underscores
    name = name.strip('_')
    return name


def extract_activity_id_from_response(response):
    """Safely extracts Garmin Connect Activity ID from upload response."""
    try:
        if isinstance(response, dict):
            import_result = response.get('detailedImportResult', {})
            successes = import_result.get('successes', [])
            if successes and isinstance(successes, list):
                return successes[0].get('internalId')
    except Exception:
        pass
    return None


def find_latest_activity_id(api, start_time_utc):
    """Fallback to search Garmin Connect for the uploaded activity based on date."""
    try:
        print("[i] Attempting to find activity ID by listing recent activities...")
        # Fetch the most recent 5 activities
        activities = api.get_activities(0, 5)
        if not activities:
            return None

        # Try to find a matching activity by start time (within a reasonable window)
        for act in activities:
            start_time_local_str = act.get('startTimeLocal') # e.g. "2026-05-24 13:23:43"
            activity_id = act.get('activityId')
            
            if start_time_local_str and activity_id:
                # Convert activity start time local string to datetime
                try:
                    act_dt = datetime.strptime(start_time_local_str, "%Y-%m-%d %H:%M:%S")
                    # Check if activity matches within a 5-minute difference
                    time_diff = abs((start_time_utc.replace(tzinfo=None) - act_dt).total_seconds())
                    if time_diff < 3600 * 3: # Allow timezone differences (up to 3 hours match window)
                        return activity_id
                except Exception:
                    continue
                    
        # If no strict match, fallback to the latest activity
        return activities[0].get('activityId')
    except Exception as e:
        print(f"[!] Failed to list activities: {e}")
    return None


def main():
    acquire_lock()
    print("=========================================")
    print("      IGPSPORT to Garmin Connect Sync    ")
    print("=========================================")
    
    config = load_config()
    history = load_history()
    load_geocode_cache()
    
    watch_folder = config['watch_folder']
    watch_folder = os.path.abspath(watch_folder)
    
    archive_folder = config.get('archive_folder')
    if archive_folder:
        archive_folder = os.path.abspath(archive_folder)
        try:
            os.makedirs(archive_folder, exist_ok=True)
        except OSError as e:
            print(f"[-] Error: Could not create archive folder '{archive_folder}': {e}")
            if config.get('archive_folder', '').startswith('/'):
                print("    Hint: Your path starts with '/'. On macOS, the root directory is read-only.")
                print("          Please use a relative path (e.g. './archive') or a path in your user directory (e.g. '/Users/username/Desktop/archive').")
            release_lock()
            sys.exit(1)
        
    rename_local = config.get('rename_local_files', True)
    
    if not os.path.exists(watch_folder):
        try:
            os.makedirs(watch_folder, exist_ok=True)
            print(f"[i] Created watch folder: {watch_folder}")
        except OSError as e:
            print(f"[-] Error: Could not create watch folder '{watch_folder}': {e}")
            if config.get('watch_folder', '').startswith('/'):
                print("    Hint: Your path starts with '/'. On macOS, the root directory is read-only.")
                print("          Please use a relative path (e.g. './watch') or a path in your user directory (e.g. '/Users/username/Desktop/watch').")
            release_lock()
            sys.exit(1)
        
    # iGPSPORT Cloud Sync Integration
    igpsport_user = config.get('igpsport_username')
    igpsport_pass = config.get('igpsport_password')
    igp_client = None
    ride_id_map = {}  # mapping file_hash -> rideId
    ride_name_map = {}  # mapping rideId -> title
    succeeded_ride_ids = []
    
    if igpsport_user and igpsport_pass:
        print("[*] iGPSPORT credentials configured. Checking cloud activities...")
        try:
            igp_client = IGPSPORTClient(igpsport_user, igpsport_pass)
            try:
                igp_client.login()
                print("[✓] iGPSPORT login successful.")
            except Exception as e:
                # Set client to None so we don't attempt other operations later
                igp_client = None
                print(f"[!] iGPSPORT login failed: {e}")
                print("[i] Continuing script execution to scan local watch folder...")
                
            if igp_client:
                print("[*] Fetching activity list from iGPSPORT cloud...")
            list_res = igp_client.get_activities(page_no=1, page_size=20)
            rows = list_res.get("data", {}).get("rows", [])
            print(f"[i] Found {len(rows)} activities on iGPSPORT cloud.")
            
            new_downloads = 0
            for row in rows:
                ride_id = row.get("rideId")
                ride_title = row.get("title") or f"Ride {ride_id}"
                
                # Check if this rideId is in history
                already_synced = False
                for h_hash, h_entry in history.items():
                    if h_entry.get('ride_id') == ride_id and h_entry.get('status') in ['SUCCESS', 'DUPLICATE']:
                        already_synced = True
                        break
                        
                if not already_synced:
                    print(f"[*] Downloading new activity from iGPSPORT: '{ride_title}' (ID: {ride_id})...")
                    try:
                        file_path = igp_client.download_activity(ride_id, watch_folder)
                        file_hash = compute_md5(file_path)
                        ride_id_map[file_hash] = ride_id
                        ride_name_map[ride_id] = ride_title
                        new_downloads += 1
                        print(f"[✓] Downloaded to: {os.path.basename(file_path)}")
                    except Exception as e:
                        print(f"[!] Failed to download ride {ride_id}: {e}")
                        
            if new_downloads > 0:
                print(f"[i] Downloaded {new_downloads} new activity file(s) from iGPSPORT.")
            else:
                print("[i] No new activities to download from iGPSPORT.")
                
        except Exception as e:
            print(f"[!] iGPSPORT cloud sync skipped due to error: {e}")
            
    # Get all .fit and .gpx files
    files = []
    for f in os.listdir(watch_folder):
        if f.lower().endswith(('.fit', '.gpx')):
            files.append(os.path.join(watch_folder, f))
            
    if not files:
        print("[i] No activity files (.fit or .gpx) found to sync.")
        release_lock()
        sys.exit(0)
        
    print(f"[i] Found {len(files)} activity file(s) in watch folder.")
    
    # Initialize Garmin API
    print("[*] Logging in to Garmin Connect...")
    try:
        # Note: garminconnect manages session token files automatically in ~/.garminconnect
        api = Garmin(config['garmin_email'], config['garmin_password'])
        api.login()
        print("[✓] Login successful.")
    except Exception as e:
        print(f"[-] Garmin Connect login failed: {e}")
        release_lock()
        sys.exit(1)
        
    success_count = 0
    duplicate_count = 0
    fail_count = 0
    
    for file_path in files:
        filename = os.path.basename(file_path)
        print(f"\n[*] Processing: {filename}")
        
        # 1. Compute file hash to prevent double syncs
        file_hash = compute_md5(file_path)
        
        # Try to extract ride_id from filename or ride_id_map
        ride_id = ride_id_map.get(file_hash)
        if not ride_id:
            match = re.match(r'igpsport_(\d+)\.fit', filename.lower())
            if match:
                ride_id = int(match.group(1))
                
        if file_hash in history:
            entry = history[file_hash]
            status = entry.get('status')
            print(f"[i] File already processed. History Status: {status}")
            
            # If it was already completed or marked duplicate, we just move it to archive if it's still here
            if status in ['SUCCESS', 'DUPLICATE']:
                # Update ride_id in history if it was missing
                if ride_id and not entry.get('ride_id'):
                    entry['ride_id'] = ride_id
                    save_history(history)
                    
                if archive_folder:
                    try:
                        dest_name = entry.get('archived_filename', filename)
                        dest_path = os.path.join(archive_folder, dest_name)
                        shutil.move(file_path, dest_path)
                        print(f"[✓] Moved already synced file to archive: {dest_name}")
                    except Exception as e:
                        print(f"[!] Failed to move already synced file to archive: {e}")
                continue
                
        # 2. Extract metadata
        print("[*] Parsing file metadata...")
        start_coord, end_coord, start_time = None, None, None
        if filename.lower().endswith('.fit'):
            start_coord, end_coord, start_time = extract_fit_data(file_path)
        else:
            start_coord, end_coord, start_time = extract_gpx_data(file_path)
            
        # 3. Geocode and generate name
        print("[*] Resolving ride locations...")
        tour_name = generate_tour_name(start_coord, end_coord)
        print(f"[i] Generated name: '{tour_name}'")
        
        # 4. Upload file
        print("[*] Uploading file to Garmin Connect...")
        upload_success = False
        duplicate_upload = False
        activity_id = None
        
        try:
            response = api.upload_activity(file_path)
            activity_id = extract_activity_id_from_response(response)
            upload_success = True
            print("[✓] Upload completed successfully.")
        except Exception as e:
            err_str = str(e).lower()
            if "duplicate" in err_str or "already exists" in err_str or "409" in err_str:
                print("[i] Activity already exists in Garmin Connect (duplicate).")
                upload_success = True  # We count it as processed
                duplicate_upload = True
                duplicate_count += 1
            else:
                print(f"[-] Upload failed: {e}")
                fail_count += 1
                history[file_hash] = {
                    "filename": filename,
                    "timestamp": datetime.now().isoformat(),
                    "status": "FAILED",
                    "error": str(e),
                    "ride_id": ride_id
                }
                save_history(history)
                continue
                
        # 5. Rename activity on Garmin Connect if upload was new
        if upload_success and not duplicate_upload:
            if not activity_id and start_time:
                # Use fallback search
                activity_id = find_latest_activity_id(api, start_time)
                
            if activity_id:
                print(f"[*] Renaming activity ID {activity_id} to '{tour_name}' on Garmin Connect...")
                try:
                    # Garmin's set_activity_name
                    api.set_activity_name(activity_id, tour_name)
                    print("[✓] Garmin activity renamed.")
                except Exception as e:
                    print(f"[!] Failed to rename activity on Garmin: {e}")
            else:
                print("[!] Could not determine activity ID to rename activity on Garmin Connect.")
            success_count += 1
            
        if upload_success and ride_id:
            succeeded_ride_ids.append((ride_id, tour_name))
            
        # 6. File archiving and local renaming
        final_filename = filename
        if upload_success:
            status_val = "DUPLICATE" if duplicate_upload else "SUCCESS"
            
            # Determine archived filename
            if rename_local:
                sanitized_name = sanitize_filename(tour_name)
                # Formulate date string
                date_prefix = ""
                if start_time:
                    if isinstance(start_time, str):
                        # Attempt to parse or clean string
                        date_prefix = start_time[:19].replace(':', '').replace(' ', '_').replace('-', '') + "_"
                    elif isinstance(start_time, datetime):
                        date_prefix = start_time.strftime("%Y%m%d_%H%M%S_")
                
                ext = os.path.splitext(filename)[1]
                final_filename = f"{date_prefix}{sanitized_name}{ext}"
                
            if archive_folder:
                dest_path = os.path.join(archive_folder, final_filename)
                # Make sure we don't overwrite an existing file with the same name, append counter if needed
                counter = 1
                orig_dest = dest_path
                while os.path.exists(dest_path):
                    name_part, ext_part = os.path.splitext(final_filename)
                    dest_path = os.path.join(archive_folder, f"{name_part}_{counter}{ext_part}")
                    counter += 1
                
                try:
                    shutil.move(file_path, dest_path)
                    print(f"[✓] File moved to archive as: {os.path.basename(dest_path)}")
                    final_filename = os.path.basename(dest_path)
                except Exception as e:
                    print(f"[!] Failed to move file to archive: {e}")
            else:
                # If no archive folder, we rename in-place if requested
                if rename_local and final_filename != filename:
                    try:
                        dest_path = os.path.join(watch_folder, final_filename)
                        os.rename(file_path, dest_path)
                        print(f"[✓] File renamed locally to: {final_filename}")
                    except Exception as e:
                        print(f"[!] Failed to rename file locally: {e}")
                        final_filename = filename
                        
            # Save progress in history
            history[file_hash] = {
                "filename": filename,
                "archived_filename": final_filename,
                "timestamp": datetime.now().isoformat(),
                "status": status_val,
                "activity_id": activity_id,
                "tour_name": tour_name,
                "ride_id": ride_id
            }
            save_history(history)
            
    print("\n=========================================")
    print("              Sync Summary               ")
    print("=========================================")
    print(f"Successfully processed (new): {success_count}")
    print(f"Skipped (duplicates):        {duplicate_count}")
    print(f"Failed uploads:              {fail_count}")
    print("=========================================")
    
    # iGPSPORT Deletion Prompt
    delete_enabled = config.get('delete_from_igpsport_after_sync', False)
    if delete_enabled and succeeded_ride_ids:
        print("\n=========================================")
        print("          iGPSPORT Deletion Prompt       ")
        print("=========================================")
        print(f"The following {len(succeeded_ride_ids)} activities were successfully synced to Garmin Connect:")
        for r_id, r_name in succeeded_ride_ids:
            print(f"  - {r_name} (ID: {r_id})")
            
        print("\n[?] Would you like to delete these activities from your iGPSPORT account?")
        ans = input("Confirm deletion? (y/N): ").strip().lower()
        if ans in ['y', 'yes']:
            print("[*] Deleting activities from iGPSPORT...")
            try:
                if not igp_client:
                    igp_client = IGPSPORTClient(igpsport_user, igpsport_pass)
                    igp_client.login()
                
                deleted_count = 0
                for r_id, r_name in succeeded_ride_ids:
                    print(f"[*] Deleting ride {r_id} ({r_name})...")
                    if igp_client.delete_activity(r_id):
                        deleted_count += 1
                        # Update history status to deleted
                        for h_hash, h_entry in history.items():
                            if h_entry.get('ride_id') == r_id:
                                h_entry['deleted_from_igpsport'] = True
                                h_entry['deleted_timestamp'] = datetime.now().isoformat()
                        save_history(history)
                print(f"[✓] Deleted {deleted_count} of {len(succeeded_ride_ids)} activities from iGPSPORT.")
            except Exception as e:
                print(f"[-] Deletion process failed: {e}")
        else:
            print("[i] Deletion cancelled. Activities will remain on iGPSPORT.")
            
    release_lock()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Execution interrupted by user.")
        release_lock()
        sys.exit(0)
