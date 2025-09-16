import os
import csv
import io
import asyncio
import aiohttp
import re
from datetime import datetime
from typing import List, Dict
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

# ----------------------------
# CONFIGURATION
# ----------------------------

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
if not APIFY_TOKEN:
    raise ValueError("Please set APIFY_TOKEN in environment variables (Render dashboard).")

BASE_URL = f"https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items?token={APIFY_TOKEN}"

app = FastAPI(title="Instagram Scraper API", version="1.0")

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------

def validate_username(username: str) -> bool:
    """Validate Instagram username format"""
    pattern = r'^[a-zA-Z0-9._]{1,30}$'
    if not re.match(pattern, username):
        return False
    if '..' in username:
        return False
    return True

def handle_apify_response(response_data) -> List[Dict]:
    """Handle Apify API response and check for errors"""
    if isinstance(response_data, list):
        if len(response_data) == 0:
            raise HTTPException(status_code=404, detail="No posts found")
        
        first_item = response_data[0]
        if isinstance(first_item, dict) and "error" in first_item:
            error_type = first_item.get("error", "unknown")
            if error_type == "no_items":
                raise HTTPException(status_code=404, detail="Account not found or private")
            else:
                raise HTTPException(status_code=500, detail="Scraping failed")
    
    elif isinstance(response_data, dict):
        if "error" in response_data:
            raise HTTPException(status_code=500, detail="API Error")
        if "items" in response_data:
            return response_data["items"]
    
    return response_data

# ----------------------------
# SCRAPER
# ----------------------------

async def scrape_user_posts(username: str, results_limit: int = 10000) -> List[Dict]:
    """Scrape Instagram posts"""
    
    if not validate_username(username):
        raise HTTPException(status_code=400, detail="Invalid username format")
    
    instagram_url = f"https://www.instagram.com/{username}/"
    
    run_input = {
        "directUrls": [instagram_url],
        "resultsType": "posts",
        "resultsLimit": results_limit,
        "searchType": "user",
        "searchLimit": 1,
        "addParentData": False,
        "enhanceUserSearchWithFacebookPage": False,
        "includeHasStories": False,
        "extendOutputFunction": "($) => {\n  const caption = $.caption || \"\";\n  const hashtags = caption.match(/#\\w+/g) || [];\n  const title = $.title || caption || \"\";\n  return {\n    caption,\n    hashtags,\n    title\n  };\n}",
        "extendScraperFunction": "async ({ page, request, customData, Apify, signal, label }) => {}",
        "customData": {},
        "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
        async with session.post(BASE_URL, json=run_input) as resp:
            if resp.status not in [200, 201]:
                raise HTTPException(status_code=500, detail="Scraper API error")
            
            result = await resp.json()
            return handle_apify_response(result)

def process_results(raw_results: List[Dict]) -> List[Dict]:
    """Process results to get only caption, hashtags, title"""
    if not raw_results:
        raise HTTPException(status_code=404, detail="No posts found")
    
    processed = []
    for post in raw_results:
        if not isinstance(post, dict):
            continue
        
        processed.append({
            "caption": post.get("caption", ""),
            "hashtags": ", ".join(post.get("hashtags", [])) if post.get("hashtags") else "",
            "title": post.get("title", "")
        })
    
    return processed

def results_to_csv(posts: List[Dict]) -> io.StringIO:
    """Convert to CSV"""
    output = io.StringIO()
    fieldnames = ["caption", "hashtags", "title"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(posts)
    output.seek(0)
    return output

# ----------------------------
# ROUTES
# ----------------------------

@app.post("/scrape_posts")
async def scrape_posts(request: Request):
    try:
        # Get form data
        form_data = await request.form()
        username = form_data.get("username")
        
        print(f"Received username: {username}")
        
        if not username:
            raise HTTPException(status_code=400, detail="Username is required")
        
        # Clean username
        username = str(username).lstrip('@').strip()
        
        if not username:
            raise HTTPException(status_code=400, detail="Username cannot be empty")
        
        print(f"Processing: {username}")
        
        # Scrape posts
        raw = await scrape_user_posts(username)
        processed = process_results(raw)
        csv_buffer = results_to_csv(processed)
        
        filename = f"{username}_posts_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
        
        return StreamingResponse(
            iter([csv_buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
