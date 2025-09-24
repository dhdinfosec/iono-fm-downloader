# iono-fm-downloader

A robust Python script and accompanying Bash script to download podcast episodes from [iono.fm](https://iono.fm). This tool supports resuming interrupted downloads, handles Unicode filenames, provides detailed progress tracking, and includes configurable logging and quality/format preferences.

## Features

- **Download Entire Podcast Series**: Fetches and downloads all episodes from an iono.fm channel (e.g., `https://iono.fm/c/4` for BBC Learning English).
- **Resume Capability**: Automatically resumes interrupted downloads, such as the BBC episode `1599279` (`what_will_germanys_new_budget_mean_for_the_economy_1599279.m4a`), starting from the last byte (e.g., 401,408 bytes).
- **Unicode Support**: Properly handles non-ASCII characters (e.g., Afrikaans titles in Strandloper) using Unicode normalization.
- **Progress Tracking**: Displays progress bars with filenames (via `tqdm`) or fallback percentage-based logging every ~1MB.
- **Robust Error Handling**: Includes exponential backoff for retries, granular file operation error handling, and corrupted cache recovery.
- **Configurable Options**: Customize download directory, quality, format, and logging level via `podcast_config.json`.
- **Caching**: Stores episode metadata in a `cache.json` file with immediate saves to prevent data loss.
- **Logging**: Detailed logs in `podcast_download.log` with configurable verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`).

## Prerequisites

- **Operating System**: Linux, macOS, or Windows (with Bash support, e.g., WSL on Windows).
- **Dependencies**:
  - Python 3.6+ (`python3`, `pip3`)
  - Bash (for `setup_and_run.sh`)
- **Required Python Packages** (installed automatically by `setup_and_run.sh`):
  - `requests`
  - `beautifulsoup4`
  - `feedparser`
- **Optional Python Packages** (enhance functionality):
  - `tqdm` (for progress bars)
  - `python-dateutil` (for robust date parsing)
- **Note**: `unicodedata` is part of Python's standard library and does not require installation.

## Installation

1. **Download the Zip Archive**:
   - Download `iono-fm-downloader.zip` from the [Releases](https://github.com/dhdinfosec/iono-fm-downloader/releases) section.
   - Extract to a directory (e.g., `~/Desktop/iono-fm-downloader/`), which contains:
     - `download_podcast.py`
     - `setup_and_run.sh`
     - `podcast_config.json`
     - `README.md`

2. **Make the Bash Script Executable**:
   ```bash
   chmod +x setup_and_run.sh
   ```

3. **Install Dependencies**:
   - Run the Bash script to set up a virtual environment and install packages:
     ```bash
     ./setup_and_run.sh https://iono.fm/c/4
     ```
   - This detects the package manager (`apt`, `dnf`, `brew`) or provides manual installation instructions, creates a virtual environment (default: `~/podcast_venv`), and installs required packages.

4. **Optional: Custom Virtual Environment**:
   - Specify a custom virtual environment location:
     ```bash
     ./setup_and_run.sh https://iono.fm/c/4 --venv-dir ./venv
     ```

## Usage

### Basic Usage
Download all episodes from an iono.fm channel (e.g., BBC Learning English):
```bash
./setup_and_run.sh https://iono.fm/c/4 --force --short-names --dir bbc
```
- `--force`: Skips the confirmation prompt.
- `--short-names`: Uses shorter `og:title` for filenames.
- `--dir bbc`: Saves files to a `bbc/` directory.

### Debug Mode
For detailed logging (e.g., troubleshooting interrupted downloads like `1599279`):
```bash
./setup_and_run.sh https://iono.fm/c/4 --force --short-names --dir bbc --log-level DEBUG
```
- Example output for `1599279`:
  ```
  2025-09-24 19:20:00 - INFO - Fetching RSS feed from https://iono.fm/rss/prov/4...
  2025-09-24 19:20:00 - INFO - Podcast/Series: BBC
  2025-09-24 19:20:00 - INFO - Found 150 episodes for BBC
  2025-09-24 19:20:01 - INFO - Processing: What will Germanys new budget mean for the economy
  2025-09-24 19:20:01 - INFO - Redownloading incomplete file (size mismatch): what_will_germanys_new_budget_mean_for_the_economy_1599279.m4a (local: 401,408 bytes, expected: 3,411,456 bytes)
  2025-09-24 19:20:01 - INFO - Resuming download from byte 401,408
  [Progress bar: what_will_germanys_new_budget_mean_for_the_economy_1599279.m4a | 3.41MB/3.41MB]
  2025-09-24 19:20:05 - INFO - Downloaded: what_will_germanys_new_budget_mean_for_the_economy_1599279.m4a (3,411,456 bytes)
  2025-09-24 19:20:05 - INFO - Saved: what_will_germanys_new_budget_mean_for_the_economy_1599279.m4a
  ```
- Without `tqdm`:
  ```
  2025-09-24 19:20:01 - INFO - Progress for what_will_germanys_new_budget_mean_for_the_economy_1599279.m4a: 50.0% (1,705,728/3,411,456 bytes)
  2025-09-24 19:20:05 - INFO - Downloaded: what_will_germanys_new_budget_mean_for_the_economy_1599279.m4a (3,411,456 bytes)
  ```

### Force Recheck
To re-verify all files:
```bash
./setup_and_run.sh https://iono.fm/c/4 --force --recheck --dir bbc
```

### Supported Channels
- **BBC Learning English** (`https://iono.fm/c/4`): ~150 episodes, saved to `bbc/`.
- **Strandloper** (`https://iono.fm/c/8734`): ~120 episodes, saved to `rsg/` (handles Afrikaans Unicode).
- **Luister Nuus** (`https://iono.fm/c/9375`): ~150 episodes, saved to `kosmos_941/` (time-based filenames).
- **Science Weekly/Man-to-Man Talks** (`https://iono.fm/c/3744`): ~7 episodes, saved to `guardian/`.

## Configuration

Edit `podcast_config.json` to customize settings:
```json
{
    "download_dir": null,
    "max_retries": 3,
    "timeout": 30,
    "preferred_quality": "medium",
    "preferred_format": "auto",
    "log_level": "INFO",
    "filename_max_length": 80
}
```
- `download_dir`: Custom download directory (default: uses podcast name or `--dir`).
- `max_retries`: Retry attempts for failed downloads (default: 3).
- `timeout`: HTTP request timeout in seconds (default: 30).
- `preferred_quality`: Audio quality (`high`, `medium`, `low`; default: `medium`).
- `preferred_format`: File format (`mp3`, `m4a`, `auto`; default: `auto`).
- `log_level`: Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`; default: `INFO`).
- `filename_max_length`: Maximum filename length (default: 80).

## Handling Interrupted Downloads

The script resumes interrupted downloads (e.g., BBC episode `1599279` at 401,408 bytes):
1. **Detection**: Checks file size against expected size (e.g., 3,411,456 bytes) or server headers.
2. **Resume**: Uses HTTP range requests (e.g., `Range: bytes=401408-`).
3. **Progress**: Shows progress bar or logs starting from the resume point.
4. **Verification**: Confirms completion via size or hash checks.

## Troubleshooting

- **Log File**: Check `podcast_download.log` for detailed errors.
- **Missing Dependencies**: If `tqdm` or `python-dateutil` are missing, the script falls back gracefully but logs warnings.
- **Corrupted Cache**: If `cache.json` is corrupted, the script starts fresh and logs: `Corrupted or inaccessible cache file. Starting fresh.`
- **Network Issues**: Exponential backoff (1s, 2s, 4s) retries failed requests up to `max_retries` times.
- **Exit Codes**:
  - `0`: Success
  - `1`: Dependency installation failure
  - `2`: RSS feed retrieval failure
  - `3`: User cancellation
  - `4`: Keyboard interruption

## Future Improvements

- **Concurrent Downloads**: Planned support for `asyncio` and `aiohttp` to enable parallel downloads, configurable via `max_concurrent_downloads` in `podcast_config.json`.
- **Metadata Embedding**: Add option to embed metadata (e.g., title, author) into audio files using `mutagen`.

## Contributing

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/your-feature`).
3. Commit changes (`git commit -m "Add your feature"`).
4. Push to the branch (`git push origin feature/your-feature`).
5. Open a pull request.

## License

This project is licensed under the MIT License. See the LICENSE.txt file for details.

## Contact

For issues or suggestions, open an issue on the [GitHub repository](https://github.com/dhdinfosec/iono-fm-downloader).

© 2025 dhdinfosec
