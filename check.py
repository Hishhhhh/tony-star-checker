import os
import re
import requests

APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
APIFY_TASK_ID = os.environ.get("APIFY_TASK_ID")

# Put his public profile link here
PROFILE_URL = "https://www.facebook.com/profile.php?id=61593822099768"
STATE_FILE = "latest_post.txt"

def get_last_seen():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return ""

def save_last_seen(post_id):
    with open(STATE_FILE, "w") as f:
        f.write(post_id)

def trigger_apify():
    print("New post detected! Firing Apify task...")
    endpoint = f"https://api.apify.com/v2/actor-tasks/{APIFY_TASK_ID}/runs?token={APIFY_TOKEN}"
    response = requests.post(endpoint)
    if response.status_code in [200, 201]:
        print("Apify successfully triggered.")
    else:
        print(f"Failed to trigger Apify: {response.status_code} - {response.text}")

def main():
    last_seen = get_last_seen()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        res = requests.get(PROFILE_URL, headers=headers, timeout=15)
        # Match post, reel, or video ID numbers in public markup
        matches = re.findall(r'/(?:posts|reel|videos)/([0-9]+)', res.text)
        
        if not matches:
            print("No post IDs found on this pass (page structure unchanged or login gate). Skipping.")
            return

        latest_id = matches[0]
        print(f"Latest post ID seen: {latest_id}")

        if latest_id != last_seen:
            print(f"Change detected! (Old: {last_seen} -> New: {latest_id})")
            save_last_seen(latest_id)
            trigger_apify()
        else:
            print("No new post detected. Exiting.")

    except Exception as e:
        print(f"Error checking profile: {e}")

if __name__ == "__main__":
    main()
