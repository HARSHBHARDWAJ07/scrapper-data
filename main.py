import os
import csv
import io
import asyncio
import aiohttp
from datetime import datetime
from typing import List, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ----------------------------
# CONFIGURATION
# ----------------------------
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
if not APIFY_TOKEN:
    raise ValueError("Please set APIFY_TOKEN in environment variables (Render dashboard).")

BASE_URL = "https://api.apify.com/v2"
ACTOR_ID = "apify/instagram-scraper"

app = FastAPI(title="Instagram Scraper API", version="1.0")


# ----------------------------
# MODELS
# ----------------------------
class ScrapeRequest(BaseModel):
    username: str


# ----------------------------
# SCRAPER
# ----------------------------
async def scrape_user_posts(username: str, max_posts: int = 30) -> List[Dict]:
    """Scrape Instagram posts for a specific user from Apify actor"""

    run_input = {
        "usernames": [username],
        "resultsType": "posts",
        "resultsLimit": max_posts,
        "searchType": "user",
        "searchLimit": 1,
        "commentsLimit": 10,
        "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }

    headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}

    async with aiohttp.ClientSession() as session:
        # Start run
        run_url = f"{BASE_URL}/acts/{ACTOR_ID}/runs"
        async with session.post(run_url, json=run_input, headers=headers) as resp:
            if resp.status != 201:
                raise HTTPException(status_code=500, detail=f"Failed to start scrape: {await resp.text()}")
            run_data = await resp.json()
            run_id = run_data["data"]["id"]

        # Poll until done
        status_url = f"{BASE_URL}/actor-runs/{run_id}"
        dataset_url = f"{BASE_URL}/actor-runs/{run_id}/dataset/items"

        while True:
            async with session.get(status_url, headers=headers) as resp:
                status_data = await resp.json()
                status = status_data["data"]["status"]

                if status == "SUCCEEDED":
                    break
                elif status == "FAILED":
                    raise HTTPException(status_code=500, detail="Scraping failed")
                await asyncio.sleep(5)

        # Fetch results
        async with session.get(dataset_url, headers=headers) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=500, detail=f"Failed to get results: {await resp.text()}")
            return await resp.json()


def process_results(raw_results: List[Dict]) -> List[Dict]:
    """Clean and select only required fields"""
    processed = []
    for post in raw_results:
        processed.append({
            "post_url": post.get("url", ""),
            "caption": post.get("caption", ""),
            "hashtags": ", ".join(post.get("hashtags", [])),
            "top_comments": " | ".join([c.get("text", "") for c in post.get("latestComments", [])[:5]])
        })
    return processed


def results_to_csv(posts: List[Dict]) -> io.StringIO:
    """Convert posts list to CSV string buffer"""
    output = io.StringIO()
    if not posts:
        raise HTTPException(status_code=404, detail="No posts found")

    fieldnames = ["post_url", "caption", "hashtags", "top_comments"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(posts)
    output.seek(0)
    return output


# ----------------------------
# ROUTES
# ----------------------------
@app.post("/scrape_posts")
async def scrape_posts(payload: ScrapeRequest):
    try:
        raw = await scrape_user_posts(payload.username)
        processed = process_results(raw)
        csv_buffer = results_to_csv(processed)

        filename = f"{payload.username}_posts_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
        return StreamingResponse(
            iter([csv_buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
