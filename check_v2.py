import io
import json
import os
import re
import socket
import sys
import time
from datetime import datetime
import requests
import urllib3.util.connection as urllib3_cn
import yt_dlp

# Force IPv4 resolution
def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

# Environment Secrets
APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
APIFY_TASK_ID = os.environ.get("APIFY_TASK_ID")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# Profile URL to monitor
PROFILE_URL = "https://www.facebook.com/people/Anthony-Martin/61593822099768/"

# Tracking files
LATEST_POST_FILE = "latest_post_v2.txt"
SEEN_IDS_FILE = "seen_ids.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}


def load_seen_ids():
    if not os.path.exists(SEEN_IDS_FILE):
        return set()
    with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def append_seen_id(post_id):
    with open(SEEN_IDS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")


def load_latest_post_id():
    if not os.path.exists(LATEST_POST_FILE):
        return None
    with open(LATEST_POST_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()
        return content if content else None


def save_latest_post_id(post_id):
    with open(LATEST_POST_FILE, "w", encoding="utf-8") as f:
        f.write(f"{post_id}\n")


def fetch_all_post_ids_from_profile():
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        res = session.get(PROFILE_URL, timeout=15)
        if res.status_code != 200:
            print(f"Failed to fetch profile: HTTP {res.status_code}")
            return []

        # Find all post/reel IDs visible in HTML scripts and tags
        matches = []
        matches.extend(re.findall(r'"post_id":"(\d+)"', res.text))
        matches.extend(re.findall(r'/posts/(\d+)', res.text))
        matches.extend(re.findall(r'/reel/(\d+)', res.text))

        # Preserve order while removing duplicates
        seen_in_page = set()
        unique_ids = []
        for pid in matches:
            if pid not in seen_in_page:
                seen_in_page.add(pid)
                unique_ids.append(pid)

        return unique_ids
    except Exception as e:
        print(f"Error checking profile: {e}")
        return []


def run_apify_task():
    print("Change detected on profile! Running Apify task synchronously...")
    endpoint = f"https://api.apify.com/v2/actor-tasks/{APIFY_TASK_ID}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    try:
        res = requests.post(endpoint, timeout=180)
        if res.status_code in [200, 201]:
            print("Apify run finished successfully. Processing dataset...")
            return res.json()
        print(f"Apify run failed ({res.status_code}): {res.text}")
        return None
    except Exception as e:
        print(f"Apify execution error: {e}")
        return None


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


def download_reel_with_ytdlp(url, output_filename="reel.mp4"):
    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": output_filename,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": 24 * 1024 * 1024,  # Cap under Discord 25MB limit
    }
    try:
        print(f"Attempting video download via yt-dlp for: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if os.path.exists(output_filename) and os.path.getsize(output_filename) > 0:
            return output_filename
    except Exception as e:
        print(f"yt-dlp download failed: {e}")
    return None


def send_to_discord(post_data):
    if not DISCORD_WEBHOOK_URL:
        print("Warning: DISCORD_WEBHOOK_URL not configured.")
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
        "\u200b",
    ]
    content = "\n".join(content_lines)

    headers = {
        "User-Agent": HEADERS["User-Agent"]
    }

    media = post_data.get("media") or []
    first_media = media[0] if (isinstance(media, list) and len(media) > 0 and isinstance(media[0], dict)) else {}

    is_reel_or_video = (
        "reel" in post_url.lower()
        or first_media.get("__typename") == "Video"
        or post_data.get("videoUrl")
    )

    # BRANCH 1: Download video via yt-dlp & upload as playable file
    if is_reel_or_video and post_url:
        temp_video = download_reel_with_ytdlp(post_url, "temp_reel.mp4")
        if temp_video:
            try:
                size_mb = os.path.getsize(temp_video) / (1024 * 1024)
                print(f"Downloaded video successfully ({size_mb:.2f} MB). Uploading to Discord...")
                payload = {"content": content}
                with open(temp_video, "rb") as f:
                    files = {
                        "payload_json": (None, json.dumps(payload), "application/json"),
                        "file": ("reel.mp4", f, "video/mp4"),
                    }
                    res = requests.post(DISCORD_WEBHOOK_URL, files=files, timeout=90)
                print(f"Direct Discord upload (playable video): status {res.status_code}")
                if os.path.exists(temp_video):
                    os.remove(temp_video)
                if res.status_code in [200, 204]:
                    return
            except Exception as err:
                print(f"Discord video upload error: {err}")
                if os.path.exists(temp_video):
                    os.remove(temp_video)

    # BRANCH 2: High-res thumbnail / photo embed / profile picture
    image_url = None
    user_data = post_data.get("user") or {}

    candidates = [
        first_media.get("thumbnail"),
        first_media.get("largeUrl"),
        first_media.get("originalUrl"),
        post_data.get("imageUrl"),
        post_data.get("image"),
        user_data.get("profilePic"),
        user_data.get("profile_picture"),
        post_data.get("profilePicture"),
    ]

    for candidate in candidates:
        if candidate and isinstance(candidate, str):
            candidate_clean = candidate.strip()
            if "fbcdn.net" in candidate_clean or any(ext in candidate_clean.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                image_url = candidate_clean
                break

    if image_url:
        try:
            print(f"Downloading image asset: {image_url[:60]}...")
            download_headers = {
                **headers,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            }
            img_res = requests.get(image_url, headers=download_headers, timeout=20)
            if img_res.status_code == 200:
                payload = {
                    "content": content,
                    "embeds": [{"image": {"url": "attachment://post_image.jpg"}}],
                }
                files = {
                    "payload_json": (None, json.dumps(payload), "application/json"),
                    "files[0]": ("post_image.jpg", io.BytesIO(img_res.content), "image/jpeg"),
                }
                res = requests.post(DISCORD_WEBHOOK_URL, files=files, timeout=30)
                print(f"Direct Discord upload (image/thumbnail): status {res.status_code}")
                return
        except Exception as err:
            print(f"Image attachment failed, falling back to text: {err}")

    # BRANCH 3: Plain text
    payload = {"content": content}
    res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
    print(f"Direct Discord upload (text): status {res.status_code}")


def main():
    seen_ids = load_seen_ids()
    old_post_id = load_latest_post_id()

    page_ids = fetch_all_post_ids_from_profile()
    if not page_ids:
        print("Could not retrieve profile post IDs. Exiting.")
        sys.exit(0)

    # First run ever initialization
    if not seen_ids and old_post_id is None:
        print(f"First run initialized. Storing initial IDs: {page_ids[:5]}")
        for pid in page_ids:
            append_seen_id(pid)
        save_latest_post_id(page_ids[0])
        sys.exit(0)

    # Find if ANY ID visible on the page is genuinely unseen
    unseen_page_ids = [pid for pid in page_ids if pid not in seen_ids]

    if not unseen_page_ids:
        print("No new posts detected on profile (all visible IDs have been seen).")
        sys.exit(0)

    print(f"Genuine new post ID(s) detected: {unseen_page_ids}! Running Apify...")

    items = run_apify_task()
    if not items:
        print("Apify dataset was empty or failed. Storing detected IDs to prevent retry loops.")
        for pid in unseen_page_ids:
            append_seen_id(pid)
            seen_ids.add(pid)
        save_latest_post_id(unseen_page_ids[0])
        sys.exit(0)

    # Process items returned by Apify that haven't been delivered yet
    new_posts = []
    for item in items:
        p_id = str(item.get("postId") or item.get("id") or "")
        if p_id and p_id not in seen_ids:
            new_posts.append((p_id, item))

    print(f"Found {len(new_posts)} genuine new post(s) to deliver!")

    for p_id, post_data in reversed(new_posts):
        send_to_discord(post_data)
        append_seen_id(p_id)
        seen_ids.add(p_id)

    # Record all IDs seen on the page so out-of-order items never re-trigger
    for pid in unseen_page_ids:
        if pid not in seen_ids:
            append_seen_id(pid)
            seen_ids.add(pid)

    save_latest_post_id(page_ids[0])
    print("Finished. Updated seen_ids.txt.")


if __name__ == "__main__":
    main()
