import os
import random
import csv
import time
from typing import List, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from colorama import init, Fore
import pyfiglet
import asyncio

# ----------------------------
# CONFIGURATION
# ----------------------------
init(autoreset=True)

COLORS = [Fore.LIGHTGREEN_EX, Fore.RED, Fore.WHITE, Fore.CYAN, Fore.YELLOW]
RESULTS_DIR = "scraped_results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# ----------------------------
# FASTAPI APP
# ----------------------------
app = FastAPI(title="Instagram Tools", version="2.2")

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
    print(f"{random.choice(COLORS)}{banner}")
    print(f"{Fore.RED}Instagram Scrapers Suite | Version: 2.2 | Author: Kev\n")
    print(f"{Fore.LIGHTGREEN_EX}HTTP Server Mode: Active\n")

async def scrape_instagram_posts(username: str, keyword: Optional[str]) -> List[Dict]:
    """Simulate async scraping"""
    await asyncio.sleep(1)  # simulate network delay
    return [
        {
            'post_id': f'{username}_{i}',
            'timestamp': f'2023-05-{10+i:02d} 14:30:00',
            'caption': f'Sample caption {i} by {username}',
            'likes': random.randint(50, 500),
            'comments': random.randint(5, 50),
            'hashtags': '#instagram #sample #python',
            'image_url': f'https://example.com/{username}/image_{i}.jpg',
            'url': f'https://www.instagram.com/p/{username}_{i}/',
            'keyword': keyword or ""
        }
        for i in range(5)
    ]

def create_csv(username: str, posts: List[Dict]) -> str:
    """Save posts to CSV"""
    filename = os.path.join(RESULTS_DIR, f"{username}_posts_{int(time.time())}.csv")
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=posts[0].keys())
        writer.writeheader()
        writer.writerows(posts)
    return filename

# ----------------------------
# ROUTES
# ----------------------------
@app.post("/scrape_posts")
async def scrape_posts_endpoint(payload: ScrapeRequest):
    username = payload.username
    keyword = payload.keyword

    try:
        posts = await scrape_instagram_posts(username, keyword)
        if not posts:
            raise HTTPException(status_code=404, detail="No posts found")
        filename = create_csv(username, posts)
        return FileResponse(
            filename,
            media_type="text/csv",
            filename=f"{username}_posts.csv"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------------
# ENTRY POINT
# ----------------------------
if __name__ == "__main__":
    show_banner()
    print(f"{Fore.LIGHTGREEN_EX}[*] Server running at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)

