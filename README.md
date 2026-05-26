# IGPSportSync

A Python automation tool to synchronize `.fit` and `.gpx` activity files from a folder (e.g., your copied bike computer activities) to your Garmin Connect account.

## Features

1. **Automatic Upload:** Scans your target folder for `.fit` and `.gpx` files and uploads them using the Garmin Connect API.
2. **iGPSPORT Cloud Downloading:** (Optional) Connects to your iGPSPORT account to automatically download new FIT activity files and place them in the watch folder.
3. **Interactive Cloud Cleanup:** (Optional) Prompts you to delete successfully synced activities from your iGPSPORT cloud account at the end of the sync run.
4. **Smart Activity Naming:** Parses the activity file, extracts start and end coordinates, performs reverse geocoding via OpenStreetMap's Nominatim API, and names the Garmin activity accordingly (e.g. `"Ride from Munich to Freising"`).
5. **Local Archiving & Renaming:** Moves uploaded files to an archive folder, and optionally renames files locally to match the tour name (e.g. `20260524_132343_Ride_from_Munich_to_Freising.fit`).
6. **Deduplication:** Uses MD5 hashing and a local `sync_history.json` database to ensure each file is processed only once, and handles Garmin-side duplicate upload exceptions gracefully.
7. **Concurrence Lock:** Prevents multiple instances from running at the same time.

---

## Setup Instructions

### 1. Install Requirements
Ensure you have Python 3.9+ installed, then install the required libraries:

```bash
pip install -r requirements.txt
```

### 2. Configure Settings
Copy `config.template.json` to `config.json`:

```bash
cp config.template.json config.json
```

Open `config.json` and fill in your credentials and directories:

```json
{
  "garmin_email": "your_email@example.com",
  "garmin_password": "your_password",
  "igpsport_username": "your_igpsport_username_or_phone",
  "igpsport_password": "your_igpsport_password",
  "watch_folder": "/Users/yourname/Dev/IGPSportSync/Input",
  "archive_folder": "/Users/yourname/Dev/IGPSportSync/Archive",
  "rename_local_files": true,
  "delete_from_igpsport_after_sync": true
}
```

* **`garmin_email` / `garmin_password`**: Your Garmin Connect login credentials.
* **`igpsport_username` / `igpsport_password`**: (Optional) Your iGPSPORT login credentials (e.g. your mobile number/email and password). Leave these empty or omit them if you only want to sync local files.
* **`watch_folder`**: The path where you copy activity files from your bike computer or where iGPSPORT files will be downloaded.
* **`archive_folder`**: The directory where processed files (successes and duplicates) will be moved to keep your watch folder clean.
* **`rename_local_files`**: Set to `true` to rename files in the archive to match the tour name.
* **`delete_from_igpsport_after_sync`**: If `true` and iGPSPORT credentials are provided, the script will prompt you at the end of the sync to delete successfully transferred activities from iGPSPORT.

### Alternative / Manual iGPSport Download Instructions
If you prefer to manually fetch your `.fit` files directly from the iGPSPORT browser dashboard:
1. Open your web browser and go to the iGPSPORT Passport portal: **`https://login.passport.igpsport.com/login`** (or `https://passport.igpsport.com/`).
2. Log in using the same credentials configured for iGPSport.
3. Once logged in, navigate to your **Activity Records** / **History** list page.
4. Click on the name of the activity you want to download to open its detail page.
5. Click the **"Download"** button located at the top right corner of the activity detail page to download the `.fit` file directly.
6. Save or move the downloaded `.fit` file into your local **`watch`** folder.
7. Run `python3 sync.py` to automatically geocode, name, upload to Garmin Connect, and archive the files!
8. If local deletion is set to `true`, you can then manually click the **"Delete"** button at the top right of the activity detail page on iGPSport's portal and confirm deletion.

---

## How to Run

Simply run the script via terminal:

```bash
python3 sync.py
```

### Script Execution Flow
1. **Acquires Lock:** Ensures only one instance runs.
2. **Loads Config & History:** Validates settings and retrieves previous sync history.
3. **iGPSPORT Sync (Optional):** Logs in to iGPSPORT, queries for the last 20 cloud activities, downloads any new ones as `.fit` files directly into the `watch_folder`, and tracks them.
4. **Scans Folder:** Finds all `.fit` and `.gpx` files in the `watch_folder`.
5. **Authenticates:** Connects to Garmin Connect.
   * *Note:* On first login, you may be prompted in the terminal to enter a Multi-Factor Authentication (MFA) code if it is enabled on your Garmin account. Once authenticated, tokens are cached in `~/.garminconnect/` to avoid prompts on future runs.
6. **Processes Files:**
   * Checks file hash against history database.
   * Extracts coordinates and timestamps.
   * Reverse-geocodes locations with rate limiting.
   * Uploads file, extracts activity ID, and sets the title on Garmin Connect.
   * Renames and archives the file locally.
7. **Cloud Cleanup Prompt (Optional):** If `delete_from_igpsport_after_sync` is enabled and activities were successfully uploaded, prompts you to delete them from iGPSPORT.
8. **Releases Lock & Summarizes:** Prints execution stats.
