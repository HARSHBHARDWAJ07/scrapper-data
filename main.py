import os
import csv
import io
import asyncio
import aiohttp
import json
import time
from datetime import datetime
from typing import List, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ----------------------------
# FASTAPI APP
# ----------------------------
app = FastAPI(title="Instagram Scraper API", version="3.0")

# ----------------------------
# MODELS
# ----------------------------
class ScrapeRequest(BaseModel):
    username: str

# ----------------------------
# APIFY INSTAGRAM SCRAPER
# ----------------------------
class ApifyInstagramScraper:
    def __init__(self, apify_token: str):
        """
        Initialize Apify Instagram Scraper
        Get your token from: https://console.apify.com/account/integrations
        """
        self.apify_token = apify_token
        self.base_url = "https://api.apify.com/v2"
        self.actor_id = "apify/instagram-scraper"
        
    async def scrape_user_posts(
        self, 
        username: str, 
        max_posts: int = 20,
        include_comments: bool = True
    ) -> List[Dict]:
        """
        Scrape Instagram posts for a specific user
        
        Args:
            username: Instagram username (without @)
            max_posts: Maximum number of posts to scrape
            include_comments: Whether to include comments
            
        Returns:
            List of post dictionaries
        """
        
        # Configuration for the Instagram scraper
        run_input = {
            "usernames": [username],
            "resultsType": "posts",
            "resultsLimit": max_posts,
            "searchType": "user",
            "searchLimit": 1,
            "addParentData": False,
            "enhanceUserSearchWithFacebookPage": False,
            "isUserTaggedFeedURL": False,
            "onlyPostsWithLocation": False,
            "likedByLimit": 5,
            "includeLocationInfo": False,
            "commentsLimit": 10 if include_comments else 0,
            "extendOutputFunction": "",
            "extendScraperFunction": "",
            "customData": {},
            "proxy": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"]
            }
        }
        
        async with aiohttp.ClientSession() as session:
            # Start the scraping task
            print(f"🚀 Starting Instagram scrape for @{username}")
            start_time = time.time()
            
            run_url = f"{self.base_url}/acts/{self.actor_id}/runs"
            headers = {"Authorization": f"Bearer {self.apify_token}"}
            
            # Start the run
            async with session.post(
                run_url, 
                json=run_input, 
                headers=headers
            ) as response:
                if response.status != 201:
                    error_text = await response.text()
                    raise HTTPException(status_code=500, detail=f"Failed to start scraping: {error_text}")
                
                run_data = await response.json()
                run_id = run_data["data"]["id"]
                print(f"⏳ Scraping started. Run ID: {run_id}")
            
            # Wait for completion and get results
            results = await self._wait_for_results(session, run_id, headers)
            
            end_time = time.time()
            print(f"✅ Scraping completed in {end_time - start_time:.2f} seconds")
            print(f"📊 Found {len(results)} posts")
            
            return results
    
    async def _wait_for_results(
        self, 
        session: aiohttp.ClientSession, 
        run_id: str, 
        headers: Dict
    ) -> List[Dict]:
        """Wait for scraping to complete and return results"""
        
        status_url = f"{self.base_url}/actor-runs/{run_id}"
        dataset_url = f"{self.base_url}/actor-runs/{run_id}/dataset/items"
        
        # Poll for completion
        while True:
            async with session.get(status_url, headers=headers) as response:
                status_data = await response.json()
                status = status_data["data"]["status"]
                
                if status == "SUCCEEDED":
                    print("✅ Scraping completed successfully")
                    break
                elif status == "FAILED":
                    raise HTTPException(status_code=500, detail="Scraping failed")
                elif status in ["RUNNING", "READY"]:
                    print(f"⏳ Status: {status}...")
                    await asyncio.sleep(5)
                else:
                    print(f"🔄 Status: {status}")
                    await asyncio.sleep(3)
        
        # Get results
        async with session.get(dataset_url, headers=headers) as response:
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                raise HTTPException(status_code=500, detail=f"Failed to get results: {error_text}")
    
    def process_results(self, raw_results: List[Dict]) -> List[Dict]:
        """Process and clean the scraped results"""
        processed_posts = []
        
        for post in raw_results:
            try:
                # Extract title from caption (first 50 chars)
                caption = post.get("caption", "")
                title = caption[:50] + "..." if len(caption) > 50 else caption
                
                processed_post = {
                    "post_url": post.get("url", ""),
                    "shortcode": post.get("shortCode", ""),
                    "title": title,
                    "caption": caption,
                    "hashtags": ", ".join(post.get("hashtags", [])),
                    "likes": post.get("likesCount", 0),
                    "comments_count": post.get("commentsCount", 0),
                    "timestamp": post.get("timestamp", ""),
                    "is_video": "True" if post.get("type") == "Video" else "False",
                    "scraped_at": datetime.utcnow().isoformat()
                }
                
                # Process comments
                comments = []
                for comment in post.get("latestComments", [])[:10]:
                    comments.append(f"{comment.get('ownerUsername', '')}: {comment.get('text', '')}")
                
                processed_post["comments"] = " | ".join(comments)
                processed_posts.append(processed_post)
                
            except Exception as e:
                print(f"⚠️ Error processing post: {e}")
                continue
        
        return processed_posts

# ----------------------------
# FASTAPI ROUTES
# ----------------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Instagram Scraper API is running 🚀"}

@app.post("/scrape_posts")
async def scrape_posts_endpoint(payload: ScrapeRequest):
    username = payload.username.lower().strip()
    
    # Get Apify token from environment
    apify_token = os.getenv("APIFY_TOKEN")
    if not apify_token:
        raise HTTPException(status_code=500, detail="APIFY_TOKEN environment variable not set")
    
    scraper = ApifyInstagramScraper(apify_token)
    
    try:
        # Scrape posts using Apify
        raw_posts = await scraper.scrape_user_posts(
            username=username,
            max_posts=20,
            include_comments=True
        )
        
        # Process the results
        posts = scraper.process_results(raw_posts)
        
        # Generate CSV
        if not posts:
            raise HTTPException(status_code=404, detail="No posts found for this user")
        
        output = io.StringIO()
        fieldnames = [
            "post_url", "shortcode", "title", "caption", "hashtags", 
            "likes", "comments_count", "comments", "timestamp", "is_video", "scraped_at"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(posts)

        buffer = io.BytesIO()
        buffer.write(output.getvalue().encode("utf-8"))
        buffer.seek(0)
        
        headers = {
            "Content-Disposition": f"attachment; filename={username}_posts.csv"
        }
        return StreamingResponse(buffer, media_type="text/csv", headers=headers)
        
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------------
# ENTRY POINT
# ----------------------------
if __name__ == "__main__":
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=int(os.getenv("PORT", 8000)),
        timeout_keep_alive=120
    )
