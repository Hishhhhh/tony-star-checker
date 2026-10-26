import io
import json
import os
import socket
import sys
import time
from datetime import datetime
import requests
import urllib3.util.connection as urllib3_cn

# Force IPv4
def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

TEST_DISCORD_WEBHOOK_URL = os.environ.get("TEST_DISCORD_WEBHOOK_URL")

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
    if not TEST_DISCORD_WEBHOOK_URL:
        print("Error: TEST_DISCORD_WEBHOOK_URL secret not set.")
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
        "\u200b"
    ]
    content = "\n".join(content_lines)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    media = post_data.get("media") or []
    first_media = media[0] if (isinstance(media, list) and len(media) > 0 and isinstance(media[0], dict)) else {}

    # 1. Video detection (checks top level and inside media array)
    video_url = (
        post_data.get("videoUrl")
        or post_data.get("downloadUrl")
        or first_media.get("videoUrl")
        or first_media.get("downloadUrl")
        or first_media.get("url") if str(first_media.get("url", "")).endswith(".mp4") else None
    )

    # 2. Image / Thumbnail detection
    image_url = None
    candidates = [
        first_media.get("thumbnail"),
        first_media.get("largeUrl"),
        first_media.get("originalUrl"),
        post_data.get("imageUrl")
    ]
    for candidate in candidates:
        if candidate and ("fbcdn.net" in candidate or any(ext in str(candidate).lower() for ext in [".jpg", ".jpeg", ".png", ".webp"])):
            image_url = candidate
            break

    # Branch 1: Playable Video
    if video_url:
        try:
            print(f"Detected video asset: {video_url[:60]}...")
            with requests.get(video_url, headers=headers, stream=True, timeout=45) as v_res:
                if v_res.status_code == 200:
                    video_bytes = io.BytesIO()
                    total_bytes = 0
                    max_limit = 24 * 1024 * 1024

                    for chunk in v_res.iter_content(chunk_size=1024 * 64):
                        total_bytes += len(chunk)
                        if total_bytes > max_limit:
                            print(f"Video exceeds 24 MB limit ({total_bytes / (1024*1024):.1f}MB). Falling back to thumbnail.")
                            video_bytes = None
                            break
                        video_bytes.write(chunk)

                    if video_bytes:
                        video_bytes.seek(0)
                        payload = {"content": content}
                        files = {
                            "payload_json": (None, json.dumps(payload), "application/json"),
                            "file": ("reel.mp4", video_bytes, "video/mp4")
                        }
                        res = requests.post(TEST_DISCORD_WEBHOOK_URL, files=files, timeout=60)
                        print(f"Direct Discord upload (playable video): status {res.status_code}")
                        return
                else:
                    print(f"Video download returned HTTP {v_res.status_code}")
        except Exception as err:
            print(f"Video upload failed, falling back to thumbnail: {err}")

    # Branch 2: Image / Thumbnail Embed
    if image_url:
        try:
            print(f"Downloading image/thumbnail asset: {image_url[:60]}...")
            download_headers = {
                **headers,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
            }
            img_res = requests.get(image_url, headers=download_headers, timeout=20)
            if img_res.status_code == 200:
                payload = {
                    "content": content,
                    "embeds": [{"image": {"url": "attachment://post_image.jpg"}}]
                }
                files = {
                    "payload_json": (None, json.dumps(payload), "application/json"),
                    "files[0]": ("post_image.jpg", io.BytesIO(img_res.content), "image/jpeg")
                }
                res = requests.post(TEST_DISCORD_WEBHOOK_URL, files=files, timeout=30)
                print(f"Direct Discord upload (image/thumbnail): status {res.status_code}")
                return
            else:
                print(f"Image download returned HTTP {img_res.status_code}")
        except Exception as err:
            print(f"Image attachment failed, falling back to text: {err}")

    # Branch 3: Plain Text
    payload = {"content": content}
    res = requests.post(TEST_DISCORD_WEBHOOK_URL, json=payload, timeout=30)
    print(f"Direct Discord upload (plain text): status {res.status_code}")

if __name__ == "__main__":
    raw_input = os.environ.get("POST_JSON_DATA", "").strip()
    if not raw_input and len(sys.argv) > 1:
        raw_input = sys.argv[1].strip()

    if not raw_input:
        print("Error: No JSON data provided.")
        sys.exit(1)

    try:
        data = json.loads(raw_input)
        # If user copied a whole dataset array, pick the first item
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        send_to_discord(data)
    except Exception as e:
        print(f"JSON Parsing Error: {e}")
        sys.exit(1)
