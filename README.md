# Aniverse Airing Tracker 🚨

A lightweight Python script that monitors currently airing anime and posts new episode release alerts directly to a Discord channel via Webhooks.

---

## How It Works

The tracker runs on a scheduling loop (every 15 minutes) to find anime episodes that aired within a lookback window (the last 16 minutes).

### 1. Primary Flow (AniList)
- The script queries the **AniList GraphQL API** for episodes airing in the lookback window.
- If matches are found, it generates a Discord rich embed notification with the anime's romaji title, episode number, cover image, and streaming link.

### 2. Fallback Flow (MyAnimeList via Jikan API)
If AniList is down, unreachable, or returns error responses, the tracker automatically falls back to **MyAnimeList** data using the public **Jikan API**:
- Converts the current query window to Japan Standard Time (JST).
- Fetches the schedule for matching JST weekdays.
- Calculates when each currently airing show was broadcast during the week.
- Determines if the broadcast fell inside the lookback window.
- Computes the exact episode number dynamically based on the difference between the current date and the series start date (`aired.from`).
- Standardizes the notification data (mapping `mal_id` and titles) to ensure Discord webhook delivery continues seamlessly.

---

## Project Structure

- `check_schedule.py`: The core Python script containing the tracking logic, API parsing, and Discord webhook notifications.
- `anime_tracker.yml`: GitHub Actions workflow definition for automated schedule execution.

---

## Local Setup & Execution

### Prerequisites
- **Python 3.9+** (uses standard library modules only; no external package installations required).

### Steps
1. **Clone the repository** (or navigate to the directory):
   ```bash
   cd f:\AniTrack
   ```

2. **Configure your Environment Variable**:
   Set your Discord Webhook URL in your environment:
   - **Windows (PowerShell)**:
     ```powershell
     $env:DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/your-webhook-url"
     ```
   - **Linux / macOS**:
     ```bash
     export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/your-webhook-url"
     ```

3. **Run the Script**:
   - **Normal Tracking Mode**:
     ```bash
     python check_schedule.py
     ```
   - **Test Webhook Mode** (Verify Discord connectivity):
     ```bash
     python check_schedule.py --test
     ```

---

## Setup on GitHub Actions

This repository is pre-configured to run automatically on GitHub using GitHub Actions.

### Steps to Enable:

1. **Push to GitHub**:
   Ensure both `check_schedule.py` and `.github/workflows/anime_tracker.yml` are committed and pushed to your GitHub repository.

2. **Configure Repository Secret**:
   - Go to your GitHub repository page.
   - Click on **Settings** (top tabs).
   - In the left sidebar, click **Secrets and variables** > **Actions**.
   - Click the **New repository secret** button.
   - Set the Name to: `DISCORD_WEBHOOK_URL`
   - Set the Value to your actual Discord Webhook URL.
   - Click **Add secret**.

3. **Automatic & Manual Runs**:
   - **Automated**: The action is scheduled to run every 15 minutes via the cron trigger (`*/15 * * * *`).
   - **Manual**: You can trigger the tracker at any time by going to the **Actions** tab in your GitHub repository, selecting the **Aniverse Airing Tracker** workflow, and clicking **Run workflow**. You can also check the **"Send a test notification..."** box to send a simulated alert to your channel immediately.

---

## Duplicate Prevention Cache

To ensure the same episode is not posted multiple times, the script stores a history of recently sent alert keys (formatted as `title-slug_ep{episode}`) in a cache file: `sent_alerts.json`.

- **Local Run**: The `sent_alerts.json` file is read and updated on your local disk.
- **GitHub Actions Run**: The workflow has write permissions enabled (`contents: write`). When new alerts are successfully sent, the Action automatically commits the updated `sent_alerts.json` file back to the repository (using the `[skip ci]` tag to avoid triggering recursive runs). This ensures state is maintained between scheduled cron executions.
