import os
import re
import requests

APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
APIFY_TASK_ID = os.environ.get("APIFY_TASK_ID")

# Clean target profile URL
RAW_URL = "https://www.facebook.com/profile.php?id=61593822099768"
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

    # Route through mobile endpoint for static server-rendered HTML
    mobile_url = RAW_URL.replace("www.facebook.com", "mbasic.facebook.com").replace("web.facebook.com", "mbasic.facebook.com")
    if "facebook.com" in mobile_url and "mbasic." not in mobile_url:
        mobile_url = mobile_url.replace("facebook.com", "mbasic.facebook.com")

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }

    try:
        session = requests.Session()
        res = session.get(mobile_url, headers=headers, timeout=15)
        
        # 1. Match standard post/story/photo IDs
        matches = re.findall(r'(?:story_fbid=|fbid=|posts/|videos/|reel/)([0-9]{8,})', res.text)
        
        # 2. Fallback: match encoded story targets
        if not matches:
            matches = re.findall(r'story\.php\?story_fbid=([0-9]+)', res.text)

        if not matches:
            # Check if Meta served an explicit checkpoint/login redirect
            if "login" in res.url:
                print("Facebook redirected request to a login wall.")
            else:
                print("No post IDs found on this pass. HTML snippet length:", len(res.text))
            return

        latest_id = matches[0]
        print(f"Latest post ID seen: {latest_id}")

        if latest_id != last_seen:
            print(f"Change detected! (Old: '{last_seen}' -> New: '{latest_id}')")
            save_last_seen(latest_id)
            trigger_apify()
        else:
            print(f"No new post detected (current ID matches '{latest_id}'). Exiting.")

    except Exception as e:
        print(f"Error checking profile: {e}")

if __name__ == "__main__":
    main()
