import os
import csv
import io
import asyncio
import aiohttp
import re
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

# Correct endpoint: run-sync-get-dataset-items
BASE_URL = f"https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items?token={APIFY_TOKEN}"

app = FastAPI(title="Instagram Scraper API", version="1.0")

# ----------------------------
# MODELS
# ----------------------------

class ScrapeRequest(BaseModel):
    username: str
    limit: int = None  # Optional limit parameter

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------

def validate_username(username: str) -> bool:
    """Validate Instagram username format"""
    # Instagram usernames: 1-30 chars, alphanumeric + dots + underscores, no consecutive dots
    pattern = r'^[a-zA-Z0-9._]{1,30}$'
    if not re.match(pattern, username):
        return False
    if '..' in username:  # No consecutive dots
        return False
    return True

def handle_apify_response(response_data) -> List[Dict]:
    """Handle Apify API response and check for errors"""
    # If response is a list, check for error objects
    if isinstance(response_data, list):
        if len(response_data) == 0:
            raise HTTPException(status_code=404, detail="No posts found - account may be private, doesn't exist, or has no posts")
        
        # Check if first item is an error object
        first_item = response_data[0]
        if isinstance(first_item, dict) and "error" in first_item:
            error_type = first_item.get("error", "unknown")
            error_desc = first_item.get("errorDescription", "Unknown error occurred")
            
            if error_type == "no_items":
                raise HTTPException(
                    status_code=404, 
                    detail="Account not found, is private, or has no posts available"
                )
            else:
                raise HTTPException(
                    status_code=500, 
                    detail=f"Scraping failed: {error_desc}"
                )
    
    # If response is a dict, it might be an error response
    elif isinstance(response_data, dict):
        if "error" in response_data:
            error_msg = response_data.get("error", {}).get("message", "Unknown API error")
            raise HTTPException(status_code=500, detail=f"API Error: {error_msg}")
        
        # If it's a dict but not an error, it might be wrapped data
        if "items" in response_data:
            return response_data["items"]
        else:
            raise HTTPException(status_code=500, detail="Unexpected response format from scraper")
    
    else:
        raise HTTPException(status_code=500, detail="Invalid response format from scraper")
    
    return response_data

# ----------------------------
# SCRAPER
# ----------------------------

async def scrape_user_posts(username: str, results_limit: int = None) -> List[Dict]:
    """Scrape Instagram posts for a specific user from Apify actor"""
    
    # Validate username format
    if not validate_username(username):
        raise HTTPException(
            status_code=400, 
            detail="Invalid username format. Username should contain only letters, numbers, dots, and underscores (1-30 characters)"
        )
    
    # Set default limit to get all posts if not specified
    if results_limit is None:
        results_limit = 10000  # Large number to get all posts
    
    # Use directUrls instead of usernames
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

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
            async with session.post(BASE_URL, json=run_input) as resp:
                # Accept both 200 and 201 as success codes
                if resp.status not in [200, 201]:
                    error_text = await resp.text()
                    raise HTTPException(
                        status_code=500, 
                        detail=f"Apify API returned status {resp.status}: {error_text}"
                    )
                
                try:
                    result = await resp.json()
                except Exception as e:
                    raise HTTPException(
                        status_code=500, 
                        detail=f"Failed to parse response from scraper: {str(e)}"
                    )
                
                # Handle and validate the response
                return handle_apify_response(result)
                
    except aiohttp.ClientError as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Network error while connecting to scraper: {str(e)}"
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504, 
            detail="Scraping request timed out. The account may have too many posts or be temporarily unavailable."
        )

def process_results(raw_results: List[Dict], limit: int = None) -> List[Dict]:
    """Clean and select only required fields: caption, hashtags, title"""
    if not raw_results:
        raise HTTPException(status_code=404, detail="No posts found")
    
    processed = []
    for post in raw_results:
        # Skip invalid post objects
        if not isinstance(post, dict):
            continue
        
        # Extract only the required fields
        processed_post = {
            "caption": post.get("caption", ""),
            "hashtags": ", ".join(post.get("hashtags", [])) if post.get("hashtags") else "",
            "title": post.get("title", "")
        }
        processed.append(processed_post)
        
        # Apply limit if specified
        if limit and len(processed) >= limit:
            break
    
    if not processed:
        raise HTTPException(status_code=404, detail="No valid posts found")
    
    return processed

def results_to_csv(posts: List[Dict]) -> io.StringIO:
    """Convert posts list to CSV string buffer"""
    output = io.StringIO()
    
    if not posts:
        raise HTTPException(status_code=404, detail="No posts found")

    # Only these three fields
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
async def scrape_posts(payload: ScrapeRequest):
    try:
        # Add request logging for debugging
        print(f"Received request: {payload}")
        
        # Clean username (remove @ if present)
        username = payload.username.lstrip('@').strip()
        
        if not username:
            raise HTTPException(status_code=400, detail="Username cannot be empty")
        
        print(f"Processing username: {username}")
        
        # Validate limit if provided
        limit = payload.limit
        if limit is not None and limit <= 0:
            raise HTTPException(status_code=400, detail="Limit must be a positive number")
        
        print(f"Using limit: {limit}")
        
        # Scrape posts (will get all posts if limit is None)
        raw = await scrape_user_posts(username, results_limit=limit)
        
        print(f"Scraped {len(raw) if raw else 0} posts")
        
        # Process results with limit applied
        processed = process_results(raw, limit=limit)
        
        print(f"Processed {len(processed)} posts")
        
        # Generate CSV
        csv_buffer = results_to_csv(processed)
        
        # Create filename with limit info
        limit_suffix = f"_limit_{limit}" if limit else "_all"
        filename = f"{username}_posts{limit_suffix}_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
        
        print(f"Returning CSV file: {filename}")
        
        return StreamingResponse(
            iter([csv_buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException as e:
        print(f"HTTP Exception: {e.detail}")
        raise e
    except Exception as e:
        # Catch any unexpected errors
        print(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"An unexpected error occurred: {str(e)}"
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
