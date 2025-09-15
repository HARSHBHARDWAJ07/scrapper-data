import os
import sys
import random
import csv
import time
from typing import List, Dict, Optional

import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from colorama import init, Fore
import pyfiglet
import asyncio

# ----------------------------
# CONFIGURATION
# ----------------------------
init(autoreset=True)

COLORS = [
    Fore.LIGHTGREEN_EX, Fore.RED, Fore.WHITE,
    Fore.CYAN, Fore.YELLOW
]

RESULTS_DIR = "scraped_results"
os.makedirs(RESULTS_DIR, exist_ok=True)

scraping_status: Dict[str, Dict] = {}

# ----------------------------
# FASTAPI APP
# ----------------------------
app = FastAPI(title="Instagram Tools", version="2.0")

# ----------------------------
# MODELS
# ----------------------------
class ScrapeRequest(BaseModel):
    username: str

# ----------------------------
# HELPERS
# ----------------------------
def clear_screen() -> None:
    os.system('cls' if os.name == 'nt' else 'clear')

def show_banner() -> None:
    banner = pyfiglet.Figlet(font='slant', width=300).renderText('IG Tools')
    print(f"{random.choice(COLORS)}{banner}")
    print(f"{Fore.RED}Instagram Scrapers Suite | Version: 2.0 | Author: Kev\n")
    print(f"{Fore.LIGHTGREEN_EX}HTTP Server Mode: Active\n")

async def scrape_instagram_posts(username: str) -> List[Dict]:
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
            'url': f'https://www.instagram.com/p/{username}_{i}/'
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

def update_status(req_id: str, status: str, message: str, filename: Optional[str] = None, post_count: int = 0):
    scraping_status[req_id].update({
        'status': status,
        'message': message,
        'filename': filename,
        'post_count': post_count
    })

# ----------------------------
# ROUTES
# ----------------------------
@app.post("/scrape_posts")
async def scrape_posts_endpoint(payload: ScrapeRequest, background_tasks: BackgroundTasks):
    username = payload.username
    req_id = str(int(time.time()))

    scraping_status[req_id] = {
        'username': username,
        'status': 'processing',
        'message': 'Scraping started',
        'filename': None
    }

    async def task():
        try:
            posts = await scrape_instagram_posts(username)
            if not posts:
                update_status(req_id, "error", "No posts found")
                return
            filename = create_csv(username, posts)
            update_status(req_id, "completed", f"Scraped {len(posts)} posts", filename, len(posts))
        except Exception as e:
            update_status(req_id, "error", str(e))

    background_tasks.add_task(task)
    return {"request_id": req_id, "status": "processing", "message": f"Scraping started for {username}"}

@app.get("/scrape_status/{req_id}")
async def get_scrape_status(req_id: str):
    status = scraping_status.get(req_id)
    if not status:
        raise HTTPException(status_code=404, detail="Invalid request ID")
    return status

@app.get("/download_csv/{req_id}")
async def download_csv(req_id: str):
    status = scraping_status.get(req_id)
    if not status:
        raise HTTPException(status_code=404, detail="Invalid request ID")
    if status['status'] != 'completed':
        raise HTTPException(status_code=400, detail="CSV not ready yet")
    if not status['filename'] or not os.path.exists(status['filename']):
        raise HTTPException(status_code=404, detail="CSV file not found")
    return FileResponse(status['filename'], media_type="text/csv", filename=f"{status['username']}_posts.csv")

# ----------------------------
# MAIN MENU (OPTIONAL)
# ----------------------------
def main_menu():
    while True:
        clear_screen()
        show_banner()
        print(f"{Fore.LIGHTGREEN_EX}[1] Session Manager")
        print("[2] Follower Scraper")
        print("[3] Following Scraper")
        print("[4] Post Scraper API (HTTP)")
        print("[5] Exit")
        print(f"\n{Fore.CYAN}API: POST /scrape_posts {{'username': 'instagram_username'}}\n")

        choice = input(f"{Fore.LIGHTGREEN_EX}Enter choice: {Fore.RED}").strip()
        if choice == '4':
            print(f"\nPost Scraper API → http://localhost:8000")
            input("\nPress Enter to return...")
        elif choice == '5':
            print(f"{Fore.LIGHTGREEN_EX}Goodbye!")
            sys.exit(0)
        else:
            print(f"{Fore.YELLOW}Not implemented yet")
            time.sleep(1)

# ----------------------------
# ENTRY POINT
# ----------------------------
if __name__ == "__main__":
    # Run FastAPI with uvicorn
    show_banner()
    print(f"{Fore.LIGHTGREEN_EX}[*] Server running at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
