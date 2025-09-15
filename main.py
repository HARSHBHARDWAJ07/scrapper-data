import os
import csv
import time
from typing import List, Dict, Optional

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from colorama import init, Fore
import pyfiglet

# ----------------------------
# CONFIGURATION
# ----------------------------
init(autoreset=True)

COLORS = [Fore.LIGHTGREEN_EX, Fore.RED, Fore.WHITE, Fore.CYAN, Fore.YELLOW]
RESULTS_DIR = "scraped_results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# Load Instagram Graph API token from env
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")  # must set in Render
if not IG_ACCESS_TOKEN:
    raise ValueError("Please set IG_ACCESS_TOKEN in environment variables.")

# ----------------------------
# FASTAPI APP
# ----------------------------
app = FastAPI(title="Instagram Tools", version="3.0")

# ----------------------------
# MODELS
# ----------------------------
class ScrapeRequest(BaseModel):
    username: str
    keyword: Optional[str] = None   # optional keyword

# ----------------------------
# HELPERS
# ----------------------------
def show_banner() -> None:
    banner = pyfiglet.Figlet(font='slant', width=300).renderText('IG Tools')
    print(f"{COLORS[0]}{banner}")
    print(f"{Fore.RED}Instagram Scrapers Suite | Version: 3.0 | Author: Kev\n")
    print(f"{Fore.LIGHTGREEN_EX}HTTP Server Mode: Active\n")

def fetch_ig_user_id(username: str) -> str:
    """Get IG User ID from username via Graph API"""
    url = f"https://graph.facebook.com/v17.0/{username}?fields=id&access_token={IG_ACCESS_TOKEN}"
    resp = requests.get(url)
    if resp.status_code != 200:
        raise HTTPException(status_code=404, detail=f"User {username} not found")
    data = resp.json()
    return data["id"]

def fetch_ig_posts(user_id: str) -> List[Dict]:
    """Fetch posts from IG Graph API"""
    posts = []
    url = f"https://graph.facebook.com/v17.0/{user_id}/media?fields=id,caption,media_url,timestamp,permalink,like_count,comments_count&access_token={IG_ACCESS_TOKEN}"
    resp = requests.get(url)
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch posts")
    data = resp.json().get("data", [])
    for item in data:
        posts.append({
            "post_id": item.get("id"),
            "timestamp": item.get("timestamp"),
            "caption": item.get("caption", ""),
            "likes": item.get("like_count", 0),
            "comments": item.get("comments_count", 0),
            "media_url": item.get("media_url", ""),
            "url": item.get("permalink", "")
        })
    return posts

def filter_posts(posts: List[Dict], keyword: Optional[str]) -> List[Dict]:
    """Filter posts by keyword if provided"""
    if not keyword:
        return posts
    return [p for p in posts if keyword.lower() in p["caption"].lower()]

def create_csv(username: str, posts: List[Dict], keyword: Optional[str]) -> str:
    """Save posts to CSV"""
    if not posts:
        raise HTTPException(status_code=404, detail="No posts found to write CSV")
    filename = os.path.join(RESULTS_DIR, f"{username}_posts_{int(time.time())}.csv")
    fieldnames = list(posts[0].keys()) + ["keyword"]
    for p in posts:
        p["keyword"] = keyword or ""
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(posts)
    return filename

# ----------------------------
# ROUTES
# ----------------------------
@app.post("/scrape_posts")
def scrape_posts_endpoint(payload: ScrapeRequest):
    username = payload.username
    keyword = payload.keyword

    try:
        user_id = fetch_ig_user_id(username)
        posts = fetch_ig_posts(user_id)
        posts = filter_posts(posts, keyword)
        filename = create_csv(username, posts, keyword)
        return FileResponse(
            filename,
            media_type="text/csv",
            filename=f"{username}_posts.csv"
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------------
# ENTRY POINT
# ----------------------------
if __name__ == "__main__":
    show_banner()
    print(f"{Fore.LIGHTGREEN_EX}[*] Server running at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)


