import os
import requests

APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
ACTOR_ID = os.environ.get("APIFY_ACTOR_ID")  # Or your specific task ID
MAKE_TEST_WEBHOOK_URL = os.environ.get("MAKE_TEST_WEBHOOK_URL")

SEEN_FILE = "seen_ids.txt"
LATEST_POST_FILE = "latest_post_v2.txt"

def load_seen_ids():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_seen_ids(seen_ids):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        for post_id in sorted(seen_ids):
            f.write(f"{post_id}\n")

def run_apify_and_get_items():
    # Runs the actor/task synchronously and returns the items directly
    # If using an actor: https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items
    # If using a task:  https://api.apify.com/v2/actor-tasks/{ACTOR_ID}/run-sync-get-dataset-items
    url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    
    # Send empty payload {} if your task already has saved input settings
    payload = {} 
    
    response = requests.post(url, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()

def main():
    # 1. Your existing check logic runs here to see if the profile text/content changed.
    # If a change is detected:
    
    seen_ids = load_seen_ids()
    scraped_posts = run_apify_and_get_items()
    
    new_posts = []
    for post in scraped_posts:
        # Check whatever unique ID key your Apify actor outputs
        post_id = str(post.get("id") or post.get("postId") or post.get("url"))
        if post_id and post_id not in seen_ids:
            new_posts.append(post)
            seen_ids.add(post_id)

    if not new_posts:
        print("Profile changed, but all posts already recorded (e.g. deletion). Zero Make ops used.")
        return

    print(f"Found {len(new_posts)} new post(s). Sending to Make...")
    
    # Reverse list so oldest post is sent first, newest post last
    new_posts.reverse()

    for post in new_posts:
        if MAKE_TEST_WEBHOOK_URL:
            requests.post(MAKE_TEST_WEBHOOK_URL, json=post, timeout=30)

    save_seen_ids(seen_ids)
    print("Done. Saved new IDs.")

if __name__ == "__main__":
    main()
