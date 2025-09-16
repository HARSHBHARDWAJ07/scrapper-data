import os
import csv
import io
from typing import List, Dict

import instaloader
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from colorama import init, Fore
import pyfiglet

# ----------------------------
# CONFIGURATION
# ----------------------------
init(autoreset=True)

# Instaloader instance
L = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    download_comments=False,
    save_metadata=False,
    compress_json=False,
)

# ----------------------------
# FASTAPI APP
# ----------------------------
app = FastAPI(title="Instagram Scraper API", version="1.3")


# ----------------------------
# MODELS
# ----------------------------
class ScrapeRequest(BaseModel):
    username: str


# ----------------------------
# HELPERS
# ----------------------------
def show_banner() -> None:
    banner = pyfiglet.Figlet(font='slant', width=120).renderText('IG Scraper')
    print(f"{Fore.LIGHTGREEN_EX}{banner}")
    print(f"{Fore.RED}Instagram Scraper Suite | Version: 1.3 | Render Deployment Ready\n")
    print(f"{Fore.LIGHTGREEN_EX}HTTP Server Mode: Active\n")


def fetch_ig_posts(username: str) -> List[Dict]:
    """Fetch posts from Instagram using Instaloader"""
    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"User {username} not found: {str(e)}")

    posts = []
    for post in profile.get_posts():
        hashtags = " ".join([f"#{t}" for t in post.caption_hashtags]) if post.caption_hashtags else ""
        comments_text = []
        try:
            for c in post.get_comments():
                comments_text.append(c.text)
        except Exception:
            comments_text = []

        posts.append({
            "post_id": post.mediaid,
            "taken_at": post.date_utc.isoformat(),
            "caption": post.caption or "",
            "hashtags": hashtags,
            "likes": post.likes,
            "comments_count": post.comments,
            "comments": " | ".join(comments_text),
            "media_url": post.url,
            "is_video": post.is_video,
            "shortcode": post.shortcode,
            "url": f"https://www.instagram.com/p/{post.shortcode}/"
        })

    return posts


def generate_csv(username: str, posts: List[Dict]) -> io.BytesIO:
    """Generate CSV in memory and return as BytesIO"""
    if not posts:
        raise HTTPException(status_code=404, detail="No posts found to return")

    output = io.StringIO()
    fieldnames = list(posts[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(posts)

    buffer = io.BytesIO()
    buffer.write(output.getvalue().encode("utf-8"))
    buffer.seek(0)
    return buffer


# ----------------------------
# ROUTES
# ----------------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Instagram Scraper API is running on Render 🚀"}


@app.post("/scrape_posts")
def scrape_posts_endpoint(payload: ScrapeRequest):
    username = payload.username

    try:
        posts = fetch_ig_posts(username)
        csv_buffer = generate_csv(username, posts)

        headers = {
            "Content-Disposition": f"attachment; filename={username}_posts.csv"
        }
        return StreamingResponse(csv_buffer, media_type="text/csv", headers=headers)

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------
# ENTRY POINT
# ----------------------------
if __name__ == "__main__":
    show_banner()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

