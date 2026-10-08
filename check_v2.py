import os
import re
import requests
import time

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
                print(f"Failed to post {post_id} to Make: {err}")
        # Add to seen IDs once sent
        seen_ids.add(post_id)
        time.sleep(2)  # Gives Discord time to breathe between messages

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
            
            # Check if this ID has already been seen in history (deletion guard)
            seen_ids = load_seen_ids()
            if latest_id in seen_ids:
                print(f"Post {latest_id} is already in seen_ids.txt — a newer post was likely deleted.")
                print("Updating latest_post_v2.txt without running Apify. 0 Apify spend, 0 Make ops!")
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
