import os
import csv
import io
import asyncio
import aiohttp
import re
import urllib.parse
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

# ----------------------------
# SCRAPER
# ----------------------------

async def scrape_user_posts(username: str, results_limit: int = 1000) -> List[Dict]:
    """Scrape Instagram posts using working configuration"""
    
    if not validate_username(username):
        raise HTTPException(status_code=400, detail="Invalid username format")
    
    instagram_url = f"https://www.instagram.com/{username}/"
    print(f"Scraping: {instagram_url}")
    
    # Use the exact working configuration from your example
    run_input = {
        "directUrls": [instagram_url],
        "resultsType": "posts",
        "resultsLimit": results_limit,
        "searchType": "user",
        "searchLimit": 1,
        "addParentData": False,
        "enhanceUserSearchWithFacebookPage": False,
        "includeHasStories": False,
        "extendOutputFunction": "($) => {\n  const caption = $.caption || \"\";\n  const hashtags = caption.match(/#\\w+/g) || [];\n  const title = $.title || caption || \"\";\n  return {\n    caption,\n    hashtags,\n    title\n };\n}",
        "extendScraperFunction": "async ({ page, request, customData, Apify, signal, label }) => {}",
        "customData": {},
        "proxy": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"]
        }
    }

    try:
        # Use longer timeout for Instagram scraping
        timeout = aiohttp.ClientTimeout(total=600)  # 10 minutes
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            print(f"Sending request to Apify API...")
            
            async with session.post(BASE_URL, json=run_input) as resp:
                print(f"Response status: {resp.status}")
                
                if resp.status not in [200, 201]:
                    error_text = await resp.text()
                    print(f"API Error: {error_text}")
                    raise HTTPException(
                        status_code=500, 
                        detail=f"Apify API error (status {resp.status}): {error_text[:200]}"
                    )
                
                try:
                    result = await resp.json()
                    print(f"Received {len(result) if isinstance(result, list) else 'non-list'} items")
                    
                    # Handle the response
                    if isinstance(result, list):
                        if len(result) == 0:
                            raise HTTPException(status_code=404, detail="No posts found - account may be private or empty")
                        
                        # Check for error in first item
                        first_item = result[0]
                        if isinstance(first_item, dict) and "error" in first_item:
                            error_type = first_item.get("error")
                            error_desc = first_item.get("errorDescription", "")
                            
                            if error_type == "no_items":
                                raise HTTPException(status_code=404, detail="Account not found, is private, or has no posts")
                            else:
                                raise HTTPException(status_code=500, detail=f"Scraping failed: {error_desc}")
                        
                        # Filter out any error objects and return valid posts
                        valid_posts = []
                        for item in result:
                            if isinstance(item, dict) and "error" not in item:
                                valid_posts.append(item)
                        
                        if not valid_posts:
                            raise HTTPException(status_code=404, detail="No valid posts found")
                        
                        print(f"Found {len(valid_posts)} valid posts")
                        return valid_posts
                    
                    else:
                        raise HTTPException(status_code=500, detail="Unexpected response format")
                        
                except Exception as json_error:
                    print(f"JSON parsing error: {json_error}")
                    raise HTTPException(status_code=500, detail="Invalid response format from scraper")
                
    except asyncio.TimeoutError:
        print("Request timed out")
        raise HTTPException(status_code=504, detail="Scraping request timed out - try again later")
    except aiohttp.ClientError as e:
        print(f"Network error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Scraping error: {str(e)}")

def process_results(raw_results: List[Dict]) -> List[Dict]:
    """Process results to extract caption, hashtags, and title"""
    print(f"Processing {len(raw_results)} posts")
    
    processed = []
    for i, post in enumerate(raw_results):
        if not isinstance(post, dict):
            continue
        
        # Extract data using the field names from extendOutputFunction
        caption = post.get("caption", "")
        hashtags = post.get("hashtags", [])
        title = post.get("postTitle", "") or post.get("title", "")
        
        # Convert hashtags to string if it's a list
        if isinstance(hashtags, list):
            hashtags_str = ", ".join(hashtags)
        else:
            hashtags_str = str(hashtags) if hashtags else ""
        
        processed_post = {
            "caption": caption,
            "hashtags": hashtags_str,
            "title": title
        }
        
        processed.append(processed_post)
        
        if i < 3:  # Log first few posts for debugging
            print(f"Post {i}: caption={len(caption)} chars, hashtags={len(hashtags_str)} chars, title={len(title)} chars")
    
    print(f"Successfully processed {len(processed)} posts")
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
        username = None
        
        # Parse request body
        content_type = request.headers.get("content-type", "").lower()
        print(f"Content-Type: {content_type}")
        
        # Try JSON first (most common)
        try:
            json_data = await request.json()
            username = json_data.get("username")
            if username:
                print(f"Got username from JSON: {username}")
        except:
            pass
        
        # Try form data as fallback
        if not username:
            try:
                form_data = await request.form()
                username = form_data.get("username")
                if username:
                    print(f"Got username from form: {username}")
            except:
                pass
        
        # Try raw body parsing as last resort
        if not username:
            try:
                body = await request.body()
                body_str = body.decode('utf-8')
                if 'username=' in body_str:
                    parsed = urllib.parse.parse_qs(body_str)
                    if 'username' in parsed:
                        username = parsed['username'][0]
                        print(f"Got username from raw parsing: {username}")
            except:
                pass
        
        if not username:
            raise HTTPException(status_code=400, detail="Username is required")
        
        # Clean username
        username = str(username).lstrip('@').strip()
        if not username:
            raise HTTPException(status_code=400, detail="Username cannot be empty")
        
        print(f"Processing username: {username}")
        
        # Scrape posts
        raw_posts = await scrape_user_posts(username, results_limit=1000)
        
        # Process results
        processed_posts = process_results(raw_posts)
        
        if not processed_posts:
            raise HTTPException(status_code=404, detail="No posts found after processing")
        
        # Generate CSV
        csv_buffer = results_to_csv(processed_posts)
        
        filename = f"{username}_posts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        print(f"Returning {len(processed_posts)} posts as {filename}")
        
        return StreamingResponse(
            iter([csv_buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.get("/")
async def root():
    return {"message": "Instagram Scraper API", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
