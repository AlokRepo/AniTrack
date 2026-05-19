import os
import time
import re
import json
import urllib.request
import urllib.parse
import datetime

# ==============================================================================
# 1. USER CONFIGURATION
# ==============================================================================
# Credentials and Endpoints
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
ANILIST_API_URL = "https://graphql.anilist.co"

# Streaming Platform Settings
WATCH_BASE_URL = "https://aniverse.sbs"
PROVIDER_NAME = "Aniverse"

# Query Windows
# Looks back 16 minutes (960 seconds) to ensure execution delays don't miss episodes
LOOKBACK_WINDOW_SECONDS = 960

# Discord Embed Customization
EMBED_TITLE = "🚨 New Episode Alert!"
EMBED_COLOR = 3447003  # Deep Blue Hexadecimal Integer (0x3498db)

# ==============================================================================
# 2. ANILIST GRAPHQL QUERY
# ==============================================================================
ANILIST_QUERY = """
query ($startTime: Int, $endTime: Int) {
  Page(page: 1, perPage: 25) {
    airingSchedules(airingAt_greater: $startTime, airingAt_lesser: $endTime) {
      id
      episode
      media {
        id
        title {
          romaji
        }
        coverImage {
          large
        }
      }
    }
  }
}
"""

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def slugify(text):
    """Converts a title to a clean, lowercase URL slug.
    
    Example: 'Jujutsu Kaisen 2nd Season' -> 'jujutsu-kaisen-2nd-season'
    """
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text).strip('-')
    return text

# --- Sent Alerts Cache Helper ---
SENT_ALERTS_FILE = "sent_alerts.json"

def load_sent_alerts():
    """Loads already sent alerts from the cache file."""
    if os.path.exists(SENT_ALERTS_FILE):
        try:
            with open(SENT_ALERTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            print(f"Warning: Failed to load sent alerts cache: {e}")
    return []

def save_sent_alerts(alerts):
    """Saves sent alerts back to the cache file, keeping only the last 100 entries."""
    try:
        # Keep list size bounded
        alerts = alerts[-100:]
        with open(SENT_ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(alerts, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save sent alerts cache: {e}")

def post_to_webhook(payload, label="Alert"):
    """Posts a JSON payload to the Discord Webhook URL."""
    if not WEBHOOK_URL:
        print(f"Error: Missing DISCORD_WEBHOOK_URL environment variable for {label}.")
        return False
        
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        }
    )
    try:
        with urllib.request.urlopen(req) as res:
            print(f"Successfully posted {label} (Status: {res.status})")
            return True
    except Exception as err:
        print(f"Failed to post webhook for {label}: {err}")
        return False

# --- MyAnimeList / Jikan API Fallback Helpers ---

DAY_MAP = {
    "mondays": 0,
    "tuesdays": 1,
    "wednesdays": 2,
    "thursdays": 3,
    "fridays": 4,
    "saturdays": 5,
    "sundays": 6
}

def parse_iso(iso_str):
    if not iso_str:
        return None
    iso_str = iso_str.replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(iso_str)
    except Exception:
        return None

def calculate_airing(item, current_time):
    """Calculates the most recent broadcast timestamp and episode number for an anime."""
    broadcast = item.get("broadcast", {})
    day = broadcast.get("day")
    time_str = broadcast.get("time")
    
    if not day or not time_str:
        return None
        
    day_lower = day.lower()
    if day_lower not in DAY_MAP:
        return None
        
    broadcast_wd = DAY_MAP[day_lower]
    try:
        hour, minute = map(int, time_str.split(":"))
    except ValueError:
        return None
        
    # Convert current time to JST (UTC+9)
    current_dt_jst = datetime.datetime.fromtimestamp(current_time, datetime.timezone.utc).astimezone(
        datetime.timezone(datetime.timedelta(hours=9))
    )
    
    # Calculate broadcast for this week (starting Monday of current_dt_jst's week)
    monday_jst = current_dt_jst - datetime.timedelta(days=current_dt_jst.weekday())
    broadcast_dt_jst = datetime.datetime(
        year=monday_jst.year,
        month=monday_jst.month,
        day=monday_jst.day,
        hour=hour,
        minute=minute,
        second=0,
        tzinfo=datetime.timezone(datetime.timedelta(hours=9))
    )
    broadcast_dt_jst += datetime.timedelta(days=broadcast_wd)
    
    # If the broadcast is in the future, the most recent one was last week
    if broadcast_dt_jst > current_dt_jst:
        broadcast_dt_jst -= datetime.timedelta(days=7)
        
    broadcast_timestamp = int(broadcast_dt_jst.timestamp())
    
    # Calculate episode number based on start date
    aired_from_str = item.get("aired", {}).get("from")
    episode_num = 1
    if aired_from_str:
        start_dt = parse_iso(aired_from_str)
        if start_dt:
            start_dt_jst = start_dt.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
            first_broadcast_dt = datetime.datetime(
                year=start_dt_jst.year,
                month=start_dt_jst.month,
                day=start_dt_jst.day,
                hour=hour,
                minute=minute,
                second=0,
                tzinfo=datetime.timezone(datetime.timedelta(hours=9))
            )
            # Find the actual first broadcast weekday on/after first_broadcast_dt
            wd_diff = (broadcast_wd - first_broadcast_dt.weekday() + 7) % 7
            first_broadcast_dt += datetime.timedelta(days=wd_diff)
            
            # Compute weeks elapsed
            time_diff = broadcast_dt_jst - first_broadcast_dt
            weeks = round(time_diff.total_seconds() / (7 * 24 * 3600))
            if weeks >= 0:
                episode_num = weeks + 1
                
    return {
        "timestamp": broadcast_timestamp,
        "episode": episode_num
    }

def get_jst_day_names(start_time, end_time):
    """Returns Jikan day filter names matching JST days for the start/end window."""
    tz_jst = datetime.timezone(datetime.timedelta(hours=9))
    dt_start = datetime.datetime.fromtimestamp(start_time, datetime.timezone.utc).astimezone(tz_jst)
    dt_end = datetime.datetime.fromtimestamp(end_time, datetime.timezone.utc).astimezone(tz_jst)
    
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    
    days = set()
    days.add(day_names[dt_start.weekday()])
    days.add(day_names[dt_end.weekday()])
    return list(days)

def make_jikan_request(url):
    """Sends a request to Jikan API, retrying on rate limits."""
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return json.loads(res.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            raise e
    raise Exception("Rate limit exceeded or request failed after retries")

def get_schedules_from_mal(start_time, current_time):
    """Fetches schedules from Jikan API and returns normalized items that aired in the window."""
    day_names = get_jst_day_names(start_time, current_time)
    all_raw_items = []
    
    for day_name in day_names:
        page = 1
        while True:
            url = f"https://api.jikan.moe/v4/schedules?filter={day_name}&page={page}"
            try:
                print(f"Fetching Jikan schedule for {day_name} (Page {page})...")
                data = make_jikan_request(url)
                all_raw_items.extend(data.get("data", []))
                
                pagination = data.get("pagination", {})
                if not pagination.get("has_next_page"):
                    break
                page += 1
                time.sleep(0.5)  # respect rate limit
            except Exception as e:
                print(f"Error fetching Jikan schedule for {day_name}: {e}")
                break
                
    matching_schedules = []
    for item in all_raw_items:
        if item.get("status") != "Currently Airing":
            continue
            
        airing_info = calculate_airing(item, current_time)
        if airing_info:
            broadcast_timestamp = airing_info["timestamp"]
            # Check if this broadcast timestamp is within our window
            if start_time < broadcast_timestamp <= current_time:
                cover_image = item.get("images", {}).get("jpg", {}).get("large_image_url") or item.get("images", {}).get("jpg", {}).get("image_url")
                matching_schedules.append({
                    "media_id": item.get("mal_id"),
                    "title": item.get("title"),
                    "episode": airing_info["episode"],
                    "cover_image": cover_image
                })
                
    return matching_schedules

# ==============================================================================
# 4. MAIN DISCORD NOTIFIER LOGIC
# ==============================================================================
def check_and_post():
    """Queries AniList API for recently aired episodes and sends Discord alerts."""
    if not WEBHOOK_URL:
        print("Error: Missing DISCORD_WEBHOOK_URL environment variable.")
        return

    # Dynamically compute query window at execution time
    current_time = int(time.time())
    start_time = current_time - LOOKBACK_WINDOW_SECONDS

    # Load previously sent alerts to prevent duplicates
    sent_alerts = load_sent_alerts()
    new_alerts_sent = False

    # 4.1 Prepare & Send AniList Request
    variables = {"startTime": start_time, "endTime": current_time}
    req_payload = json.dumps({"query": ANILIST_QUERY, "variables": variables}).encode('utf-8')
    
    anilist_req = urllib.request.Request(
        ANILIST_API_URL, 
        data=req_payload, 
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        }
    )

    use_fallback = False
    schedules = []

    try:
        with urllib.request.urlopen(anilist_req) as response:
            data = json.loads(response.read().decode('utf-8'))
            if "errors" in data and not data.get("data"):
                print(f"AniList returned GraphQL errors: {data['errors']}")
                use_fallback = True
            else:
                schedules = data.get("data", {}).get("Page", {}).get("airingSchedules", [])
    except Exception as e:
        print(f"AniList request failed: {e}")
        use_fallback = True

    if use_fallback:
        print("AniList is down or unreachable. Switching to MyAnimeList (Jikan API) fallback...")
        schedules = get_schedules_from_mal(start_time, current_time)
        if not schedules:
            print("No new episodes found via MyAnimeList fallback in this time window.")
            return
            
        print(f"Found {len(schedules)} airing schedule(s) from MyAnimeList. Checking alerts...")
        for item in schedules:
            media_id = item["media_id"]
            title = item["title"]
            episode = item["episode"]
            cover_image = item["cover_image"]

            # Generate target URL
            title_slug = slugify(title)
            
            # Deduplicate checks
            alert_key = f"{title_slug}_ep{episode}"
            if alert_key in sent_alerts:
                print(f"Alert already sent for {title} Ep {episode}. Skipping.")
                continue

            watch_url = f"{WATCH_BASE_URL.rstrip('/')}/watch/{title_slug}-{media_id}?ep={episode}"

            # Construct Discord Rich Embed
            discord_payload = {
                "embeds": [
                    {
                        "title": EMBED_TITLE,
                        "description": f"**{title}** Episode **{episode}** is now available!",
                        "url": watch_url,
                        "color": EMBED_COLOR,
                        "fields": [
                            {
                                "name": "📺 Streaming Now",
                                "value": f"[Click here to watch on {PROVIDER_NAME}]({watch_url})",
                                "inline": False
                            }
                        ],
                        "image": {
                            "url": cover_image
                        }
                    }
                ]
            }

            # Post webhook to Discord
            if post_to_webhook(discord_payload, f"MAL Alert for {title} Ep {episode}"):
                sent_alerts.append(alert_key)
                new_alerts_sent = True
                
    else:
        if not schedules:
            print("No new episodes found in this time window.")
            return

        print(f"Found {len(schedules)} airing schedule(s). Checking alerts...")

        # 4.2 Process each new episode and post to Discord
        for item in schedules:
            media = item["media"]
            media_id = media["id"]
            romaji_title = media["title"]["romaji"]
            episode = item["episode"]
            cover_image = media["coverImage"]["large"]

            # Generate target URL
            title_slug = slugify(romaji_title)
            
            # Deduplicate checks
            alert_key = f"{title_slug}_ep{episode}"
            if alert_key in sent_alerts:
                print(f"Alert already sent for {romaji_title} Ep {episode}. Skipping.")
                continue

            watch_url = f"{WATCH_BASE_URL.rstrip('/')}/watch/{title_slug}-{media_id}?ep={episode}"

            # Construct Discord Rich Embed
            discord_payload = {
                "embeds": [
                    {
                        "title": EMBED_TITLE,
                        "description": f"**{romaji_title}** Episode **{episode}** is now available!",
                        "url": watch_url,
                        "color": EMBED_COLOR,
                        "fields": [
                            {
                                "name": "📺 Streaming Now",
                                "value": f"[Click here to watch on {PROVIDER_NAME}]({watch_url})",
                                "inline": False
                            }
                        ],
                        "image": {
                            "url": cover_image
                        }
                    }
                ]
            }

            # Post webhook to Discord
            if post_to_webhook(discord_payload, f"Alert for {romaji_title} Ep {episode}"):
                sent_alerts.append(alert_key)
                new_alerts_sent = True

    # Save state if any notifications were successfully sent
    if new_alerts_sent:
        save_sent_alerts(sent_alerts)

def send_test_notification():
    """Sends a mock/test notification to Discord to verify the webhook setup."""
    print("Sending test notification to Discord...")
    discord_payload = {
        "embeds": [
            {
                "title": "🧪 Aniverse Tracker Test Alert",
                "description": "This is a test notification from your **Aniverse Airing Tracker** setup. Webhook connectivity is verified!",
                "url": WATCH_BASE_URL,
                "color": EMBED_COLOR,
                "fields": [
                    {
                        "name": "📡 Connection Status",
                        "value": "Successful! Your Discord webhook configuration is working.",
                        "inline": False
                    }
                ]
            }
        ]
    }
    post_to_webhook(discord_payload, "Test Notification")

# ==============================================================================
# 5. ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        send_test_notification()
    else:
        check_and_post()

