import os
import re
import requests

APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
APIFY_TASK_ID = os.environ.get("APIFY_TASK_ID")
MAKE_TEST_WEBHOOK_URL = os.environ.get("MAKE_TEST_WEBHOOK_URL")

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
    # This runs the task and directly waits to return the items in 1 request
    endpoint = f"https://api.apify.com/v2/actor-tasks/{APIFY_TASK_ID}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    response = requests.post(endpoint, json={}, timeout=180)
    
    if response.status_code in [200, 201]:
        print("Apify run finished successfully. Processing dataset...")
        return response.json()
    else:
        print(f"Failed to run Apify: {response.status_code} - {response.text}")
        return []

def process_and_send_posts():
    scraped_posts = fetch_apify_task_results()
    if not scraped_posts:
        print("Apify returned 0 posts or failed.")
        return

    seen_ids = load_seen_ids()
    new_posts = []

    for post in scraped_posts:
        # Pull whatever ID key Apify provides (id, postId, url, etc.)
        post_id = str(post.get("id") or post.get("postId") or post.get("postUrl") or post.get("url") or "")
        if post_id and post_id not in seen_ids:
            new_posts.append((post_id, post))

    if not new_posts:
        print("Profile change detected, but every post was already in seen_ids.txt (likely a deletion).")
        print("Skipped calling Make. 0 Make operations used.")
        return

    print(f"Found {len(new_posts)} genuine new post(s)! Sending to Make...")

    # Reverse so the oldest post posts first, newest last
    new_posts.reverse()

    for post_id, post_data in new_posts:
        if MAKE_TEST_WEBHOOK_URL:
            try:
                res = requests.post(MAKE_TEST_WEBHOOK_URL, json=post_data, timeout=30)
                print(f"Sent post {post_id} to Make: status {res.status_code}")
            except Exception as err:
                print(f
