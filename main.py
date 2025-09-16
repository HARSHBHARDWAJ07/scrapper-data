import os
import csv
import io
import asyncio
import aiohttp
import re
from datetime import datetime
from typing import List, Dict, Union
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

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------

def validate_username(username: str) -> bool:
    """Validate Instagram username format"""
    pattern = r'^[a-zA-Z0-9._]{1,30}$'
    if not re.match(pattern, username):
        return False
    if '..' in username:  # No consecutive dots
        return False
    return True

def extract_hashtags_from_caption(caption: str) -> List[str]:
    """Extract hashtags from caption text"""
    if not caption:
        return []
    hashtag_pattern = r'#(\w+)'
    hashtags = re.findall(hashtag_pattern, caption)
    return hashtags

def clean_response_text(response_text: str) -> str:
    """Clean the response text to extract JSON part"""
    # Remove the error message at the beginning if present
    if response_text.startswith("The service was not able to process your request"):
        # Find where the actual JSON starts (after "Apify API returned status XXX:")
        json_start = response_text.find("[{")
        if json_start != -1:
            return response_text[json_start:]
    return response_text

def handle_apify_response(response_data: Union[str, List, Dict]) -> List[Dict]:
    """Handle Apify API response and check for errors"""
    
    # If response is a string, try to parse it as JSON
    if isinstance(response_data, str):
        cleaned_text = clean_response_text(response_data)
        try:
            import json
            response_data = json.loads(cleaned_text)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to parse response JSON: {str(e)}"
            )
    
    # If response is a list, check for error objects
    if isinstance(response_data, list):
        if len(response_data) == 0:
            raise HTTPException(
                status_code=404, 
                detail="No posts found - account may be private, doesn't exist, or has no posts"
            )

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

async def scrape_user_posts(username: str, max_posts: int = 30) -> List[Dict]:
    """Scrape Instagram posts for a specific user from Apify actor"""

    # Validate username format
    if not validate_username(username):
        raise HTTPException(
            status_code=400, 
            detail="Invalid username format. Username should contain only letters, numbers, dots, and underscores (1-30 characters)"
        )

    # Build the Instagram URL from username
    instagram_url = f"https://www.instagram.com/{username}/"

    # Updated run_input based on working configuration
    run_input = {
        "directUrls": [instagram_url],
        "resultsType": "posts",
        "resultsLimit": max_posts,
        "searchType": "user",
        "searchLimit": 1,
        "addParentData": False,
        "enhanceUserSearchWithFacebookPage": False,
        "includeHasStories": False,
        "commentsLimit": 10,
        "extendOutputFunction": "($) => {\n  const caption = $.caption || \"\";\n  const hashtags = caption.match(/#\\w+/g) || [];\n  return {\n    postTitle: $.title || caption.split(\" \")[0] || \"\",\n    caption,\n    hashtags\n  };\n}",
        "extendScraperFunction": "async ({ page, request, customData, Apify, signal, label }) => {}",
        "customData": {},
        "proxy": {
            "useApifyProxy": True, 
            "apifyProxyGroups": ["RESIDENTIAL"]
        },
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
            async with session.post(BASE_URL, json=run_input) as resp:
                # Get response text first to handle mixed content
                response_text = await resp.text()
                
                if resp.status not in [200, 201]:
                    raise HTTPException(
                        status_code=500, 
                        detail=f"Apify API returned status {resp.status}: {response_text}"
                    )

                try:
                    # Handle the response which might be mixed text + JSON
                    result = handle_apify_response(response_text)
                    return result
                except Exception as e:
                    raise HTTPException(
                        status_code=500, 
                        detail=f"Failed to parse response from scraper: {str(e)}"
                    )

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

def process_results(raw_results: List[Dict]) -> List[Dict]:
    """Clean and select only required fields"""
    if not raw_results:
        raise HTTPException(status_code=404, detail="No posts found")

    processed = []
    for post in raw_results:
        # Skip invalid post objects
        if not isinstance(post, dict):
            continue
        
        # Extract caption
        caption = post.get("caption", "")
        
        # Extract hashtags - try multiple methods
        hashtags = []
        
        # Method 1: From extendOutputFunction
        if "hashtags" in post and isinstance(post["hashtags"], list):
            hashtags = [tag.replace('#', '') for tag in post["hashtags"]]
        
        # Method 2: Extract from caption if no hashtags found
        if not hashtags and caption:
            hashtags = extract_hashtags_from_caption(caption)
        
        # Method 3: Check original hashtags field
        if not hashtags and "hashtags" in post and isinstance(post["hashtags"], list):
            hashtags = post["hashtags"]
        
        hashtags_str = ", ".join(hashtags) if hashtags else ""
        
        # Extract comments
        comments = []
        latest_comments = post.get("latestComments", [])
        if isinstance(latest_comments, list):
            for comment in latest_comments[:5]:  # Top 5 comments
                if isinstance(comment, dict) and "text" in comment:
                    comments.append(comment["text"])
        
        comments_str = " | ".join(comments)
        
        processed.append({
            "post_url": post.get("url", ""),
            "caption": caption,
            "hashtags": hashtags_str,
            "comments_count": post.get("commentsCount", 0),
            "top_comments": comments_str,
            "post_id": post.get("id", ""),
            "short_code": post.get("shortCode", "")
        })

    if not processed:
        raise HTTPException(status_code=404, detail="No valid posts found")

    return processed

def results_to_csv(posts: List[Dict]) -> io.StringIO:
    """Convert posts list to CSV string buffer"""
    output = io.StringIO()

    if not posts:
        raise HTTPException(status_code=404, detail="No posts found")

    fieldnames = ["post_url", "caption", "hashtags", "comments_count", "top_comments", "post_id", "short_code"]
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
        # Clean username (remove @ if present)
        username = payload.username.lstrip('@').strip()

        if not username:
            raise HTTPException(status_code=400, detail="Username cannot be empty")

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
        # Catch any unexpected errors
        raise HTTPException(
            status_code=500, 
            detail=f"An unexpected error occurred: {str(e)}"
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# ----------------------------
# TEST ENDPOINT FOR DEBUGGING
# ----------------------------

@app.post("/debug_response")
async def debug_response(payload: ScrapeRequest):
    """Debug endpoint to see raw response from Apify"""
    try:
        username = payload.username.lstrip('@').strip()
        if not username:
            raise HTTPException(status_code=400, detail="Username cannot be empty")
        
        raw = await scrape_user_posts(username)
        return {"raw_data": raw, "count": len(raw) if isinstance(raw, list) else 0}
    
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Debug error: {str(e)}")
