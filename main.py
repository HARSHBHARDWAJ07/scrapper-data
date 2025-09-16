import os
import csv
import io
import requests
import json
import time
from datetime import datetime
from typing import List, Dict

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
# APIFY INSTAGRAM SCRAPER (SYNC VERSION)
# ----------------------------
class ApifyInstagramScraper:
    def __init__(self, apify_token: str):
        self.apify_token = apify_token
        self.base_url = "https://api.apify.com/v2"
        self.actor_id = "apify/instagram-scraper"
        
    def scrape_user_posts(
        self, 
        username: str, 
        max_posts: int = 20,
        include_comments: bool = True
    ) -> List[Dict]:
        """
        Scrape Instagram posts for a specific user using Apify API
        """
        
        # Configuration for the Instagram scraper
        run_input = {
            "usernames": [username],
            "resultsType": "posts",
            "resultsLimit": max_posts,
            "searchType": "user",
            "searchLimit": 1,
            "addParentData": False,
            "commentsLimit": 10 if include_comments else 0,
            "proxy": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"]
            }
        }
        
        # Start the scraping task
        print(f"🚀 Starting Instagram scrape for @{username}")
        start_time = time.time()
        
        # Start the run
        run_url = f"{self.base_url}/acts/{self.actor_id}/runs"
        headers = {
            "Authorization": f"Bearer {self.apify_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(run_url, json=run_input, headers=headers)
        if response.status_code != 201:
            raise HTTPException(status_code=500, detail=f"Failed to start scraping: {response.text}")
        
        run_data = response.json()
        run_id = run_data["data"]["id"]
        print(f"⏳ Scraping started. Run ID: {run_id}")
        
        # Wait for completion and get results
        results = self._wait_for_results(run_id, headers)
        
        end_time = time.time()
        print(f"✅ Scraping completed in {end_time - start_time:.2f} seconds")
        print(f"📊 Found {len(results)} posts")
        
        return results
    
    def _wait_for_results(self, run_id: str, headers: Dict) -> List[Dict]:
        """Wait for scraping to complete and return results"""
        
        status_url = f"{self.base_url}/actor-runs/{run_id}"
        dataset_url = f"{self.base_url}/actor-runs/{run_id}/dataset/items"
        
        # Poll for completion
        while True:
            response = requests.get(status_url, headers=headers)
            status_data = response.json()
            status = status_data["data"]["status"]
            
            if status == "SUCCEEDED":
                print("✅ Scraping completed successfully")
                break
            elif status == "FAILED":
                raise HTTPException(status_code=500, detail="Scraping failed")
            elif status in ["RUNNING", "READY"]:
                print(f"⏳ Status: {status}...")
                time.sleep(5)
            else:
                print(f"🔄 Status: {status}")
                time.sleep(3)
        
        # Get results
        response = requests.get(dataset_url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(status_code=500, detail=f"Failed to get results: {response.text}")
    
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
def scrape_posts_endpoint(payload: ScrapeRequest):
    username = payload.username.lower().strip()
    
    # Get Apify token from environment
    apify_token = os.getenv("APIFY_TOKEN")
    if not apify_token:
        raise HTTPException(status_code=500, detail="APIFY_TOKEN environment variable not set")
    
    scraper = ApifyInstagramScraper(apify_token)
    
    try:
        # Scrape posts using Apify
        raw_posts = scraper.scrape_user_posts(
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
