# IGPSportSync

A Python automation tool to synchronize `.fit` and `.gpx` activity files from a folder (e.g., your copied bike computer activities) to your Garmin Connect account.

## Features

1. **Automatic Upload:** Scans your target folder for `.fit` and `.gpx` files and uploads them using the Garmin Connect API.
2. **Smart Activity Naming:** Parses the activity file, extracts start and end coordinates, performs reverse geocoding via OpenStreetMap's Nominatim API, and names the Garmin activity accordingly (e.g. `"Ride from Munich to Freising"`).
3. **Local Archiving & Renaming:** Moves uploaded files to an archive folder, and optionally renames files locally to match the tour name (e.g. `20260524_132343_Ride_from_Munich_to_Freising.fit`).
4. **Deduplication:** Uses MD5 hashing and a local `sync_history.json` database to ensure each file is processed only once, and handles Garmin-side duplicate upload exceptions gracefully.
5. **Concurrence Lock:** Prevents multiple instances from running at the same time.

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
  "watch_folder": "/Users/yourname/Dev/IGPSportSync/Input",
  "archive_folder": "/Users/yourname/Dev/IGPSportSync/Archive",
  "rename_local_files": true
}
```

* **`watch_folder`**: The path where you copy activity files from your bike computer.
* **`archive_folder`**: The directory where processed files (successes and duplicates) will be moved to keep your watch folder clean.
* **`rename_local_files`**: Set to `true` to rename files in the archive to match the tour name.

---

## How to Run

Simply run the script via terminal:

```bash
python3 sync.py
```

### Script Execution Flow
1. **Acquires Lock:** Ensures only one instance runs.
2. **Loads Config & History:** Validates settings and retrieves previous sync history.
3. **Scans Folder:** Finds all `.fit` and `.gpx` files in the `watch_folder`.
4. **Authenticates:** Connects to Garmin Connect.
   * *Note:* On first login, you may be prompted in the terminal to enter a Multi-Factor Authentication (MFA) code if it is enabled on your Garmin account. Once authenticated, tokens are cached in `~/.garminconnect/` to avoid prompts on future runs.
5. **Processes Files:**
   * Checks file hash against history database.
   * Extracts coordinates and timestamps.
   * Reverse-geocodes locations with rate limiting.
   * Uploads file, extracts activity ID, and sets the title on Garmin Connect.
   * Renames and archives the file locally.
6. **Releases Lock & Summarizes:** Prints execution stats.
