import io
import json
import os
import re
import socket
import time
from datetime import datetime
import requests
import urllib3.util.connection as urllib3_cn

# Force urllib3 to only use IPv4 (fixes GitHub Actions [Errno 101] Network is unreachable)
def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
APIFY_TASK_ID = os.environ.get("APIFY_TASK_ID")
MAKE_TEST_WEBHOOK_URL = os.environ.get("MAKE_TEST_WEBHOOK_URL")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

RAW_URL = "https://www.facebook.com/profile.php?id=61593822099768"
STATE_FILE = "latest_post_v2.txt"
SEEN_FILE = "seen_ids.txt"

def get_last_seen():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

def save_last_seen(post_id):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(post_id)

def load_seen_ids():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_seen_ids(seen_ids):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        for post_id in sorted(seen_ids):
            f.write(f"{post_id}\n")

def fetch_apify_task_results():
    print("Change detected on profile! Running Apify task synchronously...")
    endpoint = f"https://api.apify.com/v2/actor-tasks/{APIFY_TASK_ID}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    response = requests.post(endpoint, json={}, timeout=180)
    
    if response.status_code in [200, 201]:
        print("Apify run finished successfully. Processing dataset...")
        return response.json()
    else:
        print(f"Failed to run Apify: {response.status_code} - {response.text}")
        return []

def get_unix_timestamp(time_val):
    if not time_val:
        return int(time.time())
    if isinstance(time_val, (int, float)):
        return int(time_val)
    try:
        dt = datetime.fromisoformat(str(time_val).replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return int(time.time())

def send_to_discord(post_data):
    if not DISCORD_WEBHOOK_URL:
        print("Skipping direct Discord post (DISCORD_WEBHOOK_URL secret not set).")
        return

    post_time = post_data.get("time") or post_data.get("timestamp")
    unix_time = get_unix_timestamp(post_time)

    post_url = post_data.get("url") or post_data.get("postUrl") or ""
    post_text = post_data.get("text") or post_data.get("postText") or ""

    content_lines = [
        "------------------------------------",
        f"**POSTED:** <t:{unix_time}:f> (<t:{unix_time}:R>)",
        "",
        f"<{post_url}>",
        "",
        post_text,
        ""
    ]
    content = "\n".join(content_lines).strip()

    image_url = None
    media = post_data.get("media")
    if isinstance(media, list) and len(media) > 0 and isinstance(media[0], dict):
        image_url = media[0].get("thumbnail") or media[0].get("url")
    elif post_data.get("thumbnail"):
        image_url = post_data.get("thumbnail")
    elif post_data.get("imageUrl"):
        image_url = post_data.get("imageUrl")

    # Image branch: Download raw bytes & upload to Discord as a permanent native attachment
    if image_url:
        try:
            download_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
            }
            img_res = requests.get(image_url, headers=download_headers, timeout=20)
            if img_res.status_code == 200:
                payload = {
                    "content": content,
                    "embeds": [
                        {
                            "image": {
                                "url": "attachment://post_image.jpg"
                            }
                        }
                    ]
                }
                files = {
                    "payload_json": (None, json.dumps(payload), "application/json"),
                    "files[0]": ("post_image.jpg", io.BytesIO(img_res.content), "image/jpeg")
                }
                res = requests.post(DISCORD_WEBHOOK_URL, files=files, timeout=30)
                print(f"Direct Discord upload (image): status {res.status_code}")
                return
            else:
                print(f"Image download returned status {img_res.status_code}, falling back to text.")
        except Exception as err:
            print(f"Failed to attach image to Discord, falling back to text: {err}")

    # Fallback / Text-only branch
    payload = {"content": content}
    res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
    print(f"Direct Discord upload (text): status {res.status_code}")

def process_and_send_posts():
    scraped_posts = fetch_apify_task_results()
    if not scraped_posts:
        print("Apify returned 0 posts or failed.")
        return

    seen_ids = load_seen_ids()
    new_posts = []

    for post in scraped_posts:
        post_id = str(post.get("id") or post.get("postId") or post.get("postUrl") or post.get("url") or "")
        if post_id and post_id not in seen_ids:
            new_posts.append((post_id, post))

    if not new_posts:
        print("Profile change detected, but every post was already in seen_ids.txt (likely a deletion).")
        print("Skipped triggers. 0 ops used.")
        return

    print(f"Found {len(new_posts)} genuine new post(s)!")

    # Reverse so oldest sends first, newest last
    new_posts.reverse()

    for post_id, post_data in new_posts:
        # 1. Deliver to Discord directly (permanent attachment)
        send_to_discord(post_data)

        # 2. Deliver to Make as fallback/comparison
        if MAKE_TEST_WEBHOOK_URL:
            try:
                res = requests.post(MAKE_TEST_WEBHOOK_URL, json=post_data, timeout=30)
                print(f"Sent post {post_id} to Make: status {res.status_code}")
            except Exception as err:
                print(f"Failed to post {post_id} to Make: {err}")

        seen_ids.add(post_id)
        time.sleep(2)  # Discord rate limit buffer

    save_seen_ids(seen_ids)
    print("Finished. Updated seen_ids.txt.")

def main():
    last_seen = get_last_seen()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document"
    }

    try:
        session = requests.Session()
        res = session.get(RAW_URL, headers=headers, timeout=15)
        
        title_match = re.search(r'<title>(.*?)</title>', res.text, re.IGNORECASE)
        page_title = title_match.group(1) if title_match else "No <title> found"
        print(f"Page title returned by FB: '{page_title}'")
        print(f"Final URL: {res.url}")

        matches = re.findall(r'/(?:posts|reel|videos)/([0-9]{8,})', res.text)
        if not matches:
            matches = re.findall(r'"post_id":"([0-9]+)"', res.text)
        if not matches:
            matches = re.findall(r'story_fbid=([0-9]+)', res.text)

        if not matches:
            print("No post IDs parsed. First 500 characters of response:")
            print(res.text[:500].replace('\n', ' '))
            return

        latest_id = matches[0]
        print(f"Latest post ID seen: {latest_id}")

        if latest_id != last_seen:
            print(f"Change detected! (Old: '{last_seen}' -> New: '{latest_id}')")
            
            seen_ids = load_seen_ids()
            if latest_id in seen_ids:
                print(f"Post {latest_id} is already in seen_ids.txt — a newer post was likely deleted.")
                print("Updating latest_post_v2.txt without running Apify. 0 Apify spend!")
                save_last_seen(latest_id)
                return

            save_last_seen(latest_id)
            process_and_send_posts()
        else:
            print(f"No new post detected (current ID matches '{latest_id}'). Exiting.")

    except Exception as e:
        print(f"Error checking profile: {e}")

if __name__ == "__main__":
    main()
