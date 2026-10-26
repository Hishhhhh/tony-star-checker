import io
import json
import os
import socket
import sys
import time
from datetime import datetime
import requests
import urllib3.util.connection as urllib3_cn
import yt_dlp

# Force IPv4
def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

DISCORD_WEBHOOK_URL = (
    os.environ.get("TEST_DISCORD_WEBHOOK_URL") 
    or os.environ.get("DISCORD_WEBHOOK_URL")
)

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
        'format': 'best[ext=mp4]/best',
        'outtmpl': output_filename,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 24 * 1024 * 1024  # Cap download at 24 MB
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
        print("Error: Webhook URL secret not set.")
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

    is_reel_or_video = (
        "reel" in post_url.lower() 
        or first_media.get("__typename") == "Video"
        or post_data.get("videoUrl")
    )

    # BRANCH 1: Try downloading video via yt-dlp
    if is_reel_or_video and post_url:
        video_file = download_reel_with_ytdlp(post_url, "temp_reel.mp4")
        if video_file:
            try:
                file_size_mb = os.path.getsize(video_file) / (1024 * 1024)
                print(f"Downloaded video successfully ({file_size_mb:.2f} MB). Uploading to Discord...")
                payload = {"content": content}
                with open(video_file, "rb") as f:
                    files = {
                        "payload_json": (None, json.dumps(payload), "application/json"),
                        "file": ("reel.mp4", f, "video/mp4")
                    }
                    res = requests.post(DISCORD_WEBHOOK_URL, files=files, timeout=90)
                print(f"Direct Discord upload (playable video): status {res.status_code}")
                if os.path.exists(video_file):
                    os.remove(video_file)
                if res.status_code in [200, 204]:
                    return
            except Exception as err:
                print(f"Discord video upload error: {err}")
                if os.path.exists(video_file):
                    os.remove(video_file)

    # BRANCH 2: Fallback to high-res thumbnail preview
    image_url = None
    candidates = [
        first_media.get("thumbnail"),
        first_media.get("largeUrl"),
        first_media.get("originalUrl"),
        post_data.get("imageUrl")
    ]
    for candidate in candidates:
        if candidate and ("fbcdn.net" in str(candidate) or any(ext in str(candidate).lower() for ext in [".jpg", ".jpeg", ".png", ".webp"])):
            image_url = candidate
            break

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
                res = requests.post(DISCORD_WEBHOOK_URL, files=files, timeout=30)
                print(f"Direct Discord upload (image/thumbnail): status {res.status_code}")
                return
        except Exception as err:
            print(f"Image attachment failed, falling back to text: {err}")

    # BRANCH 3: Plain text fallback
    payload = {"content": content}
    res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
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
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        send_to_discord(data)
    except Exception as e:
        print(f"JSON Parsing Error: {e}")
        sys.exit(1)
