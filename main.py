# main.py
import os
import csv
import time
import logging
from typing import List, Dict, Optional

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from colorama import init, Fore
import pyfiglet

# ----------------------------
# CONFIGURATION
# ----------------------------
init(autoreset=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ig-tools")

COLORS = [Fore.LIGHTGREEN_EX, Fore.RED, Fore.WHITE, Fore.CYAN, Fore.YELLOW]
RESULTS_DIR = "scraped_results"
os.makedirs(RESULTS_DIR, exist_ok=True)

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

def _safe_keyword_for_filename(keyword: Optional[str]) -> str:
    if not keyword:
        return "nokey"
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in keyword.strip())

def fetch_ig_user_id(username: str, token: str) -> str:
    """
    Get IG User ID from username via Graph API.
    NOTE: If your token/permissions don't allow resolving a username this will return an error body
    from Facebook Graph that will help debug.
    """
    url = f"https://graph.facebook.com/v17.0/{username}"
    params = {"fields": "id", "access_token": token}
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        logger.error("fetch_ig_user_id error (%s): %s", resp.status_code, resp.text)
        raise HTTPException(status_code=404, detail=f"User {username} not found or Graph API error: {resp.text}")
    data = resp.json()
    if "id" not in data:
        logger.error("fetch_ig_user_id missing id in response: %s", data)
        raise HTTPException(status_code=500, detail="Graph API did not return an id")
    return data["id"]

def fetch_ig_posts(user_id: str, token: str) -> List[Dict]:
    """
    Fetch posts from IG Graph API. Returns a list of dicts with consistent keys.
    """
    posts: List[Dict] = []
    url = f"https://graph.facebook.com/v17.0/{user_id}/media"
    params = {
        "fields": "id,caption,media_url,timestamp,permalink,like_count,comments_count",
        "access_token": token,
        # optional: "limit": 50
    }
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        logger.error("fetch_ig_posts failed: %s", resp.text)
        raise HTTPException(status_code=500, detail=f"Failed to fetch posts: {resp.text}")
    data = resp.json().get("data", [])
    for item in data:
        posts.append({
            "post_id": item.get("id"),
            "timestamp": item.get("timestamp"),
            "caption": item.get("caption", "") or "",
            "likes": item.get("like_count", 0) or 0,
            "comments": item.get("comments_count", 0) or 0,
            "media_url": item.get("media_url", "") or "",
            "url": item.get("permalink", "") or ""
        })
    return posts

def filter_posts(posts: List[Dict], keyword: Optional[str]) -> List[Dict]:
    """Filter posts by keyword if provided (case-insensitive)."""
    if not keyword:
        return posts
    kw = keyword.lower()
    return [p for p in posts if kw in (p.get("caption") or "").lower()]

def create_csv(username: str, posts: List[Dict], keyword: Optional[str]) -> str:
    """Save posts to CSV and return filename. Adds a keyword column to each row."""
    if not posts:
        raise HTTPException(status_code=404, detail="No posts found to write CSV")
    safe_kw = _safe_keyword_for_filename(keyword)
    filename = os.path.join(RESULTS_DIR, f"{username}_{safe_kw}_posts_{int(time.time())}.csv")
    fieldnames = list(posts[0].keys())
    if "keyword" not in fieldnames:
        fieldnames.append("keyword")
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
@app.get("/health")
def health():
    """Simple health endpoint for Render health checks."""
    return {"status": "ok"}

@app.post("/scrape_posts")
async def scrape_posts_endpoint(request: Request):
    """
    Accepts either JSON or form-encoded data:
      JSON:  {"username":"manali", "keyword":"travel"}
      FORM: username=manali&keyword=travel

    Returns a CSV file (FileResponse) containing posts (keyword included).
    """
    # Read token at request-time so the app doesn't crash at import time
    IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
    if not IG_ACCESS_TOKEN:
        # Clear, non-crashing error — Render will not keep restarting workers due to import-time exception.
        raise HTTPException(status_code=500, detail="IG_ACCESS_TOKEN is not set in environment variables.")

    # Parse body: prefer JSON, else form
    username: Optional[str] = None
    keyword: Optional[str] = None
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body = await request.json()
            username = body.get("username")
            keyword = body.get("keyword")
        else:
            form = await request.form()
            username = form.get("username")
            keyword = form.get("keyword")
    except Exception as e:
        logger.exception("Failed to parse request body: %s", e)
        raise HTTPException(status_code=400, detail="Unable to parse request body (expecting JSON or form data).")

    if not username:
        raise HTTPException(status_code=400, detail="username is required")

    try:
        user_id = fetch_ig_user_id(username, IG_ACCESS_TOKEN)
        posts = fetch_ig_posts(user_id, IG_ACCESS_TOKEN)
        posts = filter_posts(posts, keyword)
        filename = create_csv(username, posts, keyword)
        download_name = f"{username}_{_safe_keyword_for_filename(keyword)}_posts.csv"
        return FileResponse(filename, media_type="text/csv", filename=download_name)
    except HTTPException:
        # re-raise so FastAPI will send the intended status code
        raise
    except Exception as e:
        logger.exception("Unexpected error in scrape_posts_endpoint: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------------
# ENTRY POINT
# ----------------------------
if __name__ == "__main__":
    # show banner for local runs
    show_banner()
    port = int(os.getenv("PORT", 8000))
    print(f"{Fore.LIGHTGREEN_EX}[*] Server running at http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
