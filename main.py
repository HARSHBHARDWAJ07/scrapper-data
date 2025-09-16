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

def handle_apify_response(response_data) -> List[Dict]:
    """Handle Apify API response and check for errors"""
    print(f"Handling response - type: {type(response_data)}")
    
    if isinstance(response_data, list):
        print(f"List response with {len(response_data)} items")
        
        if len(response_data) == 0:
            raise HTTPException(status_code=404, detail="No posts found")
        
        first_item = response_data[0]
        print(f"First item: {first_item}")
        
        if isinstance(first_item, dict) and "error" in first_item:
            error_type = first_item.get("error", "unknown")
            error_desc = first_item.get("errorDescription", "Unknown error")
            print(f"Error in response: {error_type} - {error_desc}")
            
            if error_type == "no_items":
                raise HTTPException(status_code=404, detail="Account not found, private, or has no posts")
            else:
                raise HTTPException(status_code=500, detail=f"Scraping failed: {error_desc}")
    
    elif isinstance(response_data, dict):
        print(f"Dict response: {response_data}")
        
        if "error" in response_data:
            error_msg = response_data.get("error", {})
            print(f"Dict error: {error_msg}")
            raise HTTPException(status_code=500, detail=f"API Error: {error_msg}")
        
        if "items" in response_data:
            print(f"Found items in dict: {len(response_data['items'])}")
            return response_data["items"]
    
    print(f"Returning response_data as-is")
    return response_data

# ----------------------------
# SCRAPER
# ----------------------------

async def scrape_user_posts(username: str, results_limit: int = 10000) -> List[Dict]:
    """Scrape Instagram posts"""
    
    if not validate_username(username):
        raise HTTPException(status_code=400, detail="Invalid username format")
    
    instagram_url = f"https://www.instagram.com/{username}/"
    print(f"Instagram URL: {instagram_url}")
    
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

    print(f"Making request to: {BASE_URL}")
    print(f"Request payload: {run_input}")

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
            async with session.post(BASE_URL, json=run_input) as resp:
                print(f"Response status: {resp.status}")
                
                if resp.status not in [200, 201]:
                    error_text = await resp.text()
                    print(f"Error response: {error_text}")
                    raise HTTPException(status_code=500, detail=f"Scraper API error: {error_text}")
                
                result = await resp.json()
                print(f"Raw result type: {type(result)}")
                print(f"Raw result length: {len(result) if isinstance(result, list) else 'N/A'}")
                
                if isinstance(result, list) and len(result) > 0:
                    print(f"First item: {result[0]}")
                
                return handle_apify_response(result)
                
    except aiohttp.ClientError as e:
        print(f"Network error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")
    except asyncio.TimeoutError as e:
        print(f"Timeout error: {str(e)}")
        raise HTTPException(status_code=504, detail="Request timeout")
    except Exception as e:
        print(f"Unexpected error in scrape_user_posts: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Scraping error: {str(e)}")

def process_results(raw_results: List[Dict]) -> List[Dict]:
    """Process results to get only caption, hashtags, title"""
    print(f"Processing {len(raw_results) if raw_results else 0} raw results")
    
    if not raw_results:
        raise HTTPException(status_code=404, detail="No posts found")
    
    processed = []
    for i, post in enumerate(raw_results):
        print(f"Processing post {i}: {type(post)}")
        
        if not isinstance(post, dict):
            print(f"Skipping non-dict post: {post}")
            continue
        
        # Log available keys for debugging
        print(f"Post keys: {list(post.keys())}")
        
        processed_post = {
            "caption": post.get("caption", ""),
            "hashtags": ", ".join(post.get("hashtags", [])) if post.get("hashtags") else "",
            "title": post.get("title", "")
        }
        
        print(f"Processed post: {processed_post}")
        processed.append(processed_post)
    
    print(f"Final processed count: {len(processed)}")
    
    if not processed:
        raise HTTPException(status_code=404, detail="No valid posts found")
    
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
        
        # Try multiple ways to get the username
        content_type = request.headers.get("content-type", "").lower()
        print(f"Content-Type: {content_type}")
        
        # Method 1: Try form data
        try:
            form_data = await request.form()
            username = form_data.get("username")
            print(f"Form data - username: {username}")
            if username:
                print(f"Got username from form: {username}")
        except Exception as e:
            print(f"Form parsing failed: {e}")
        
        # Method 2: Try JSON if form failed
        if not username:
            try:
                json_data = await request.json()
                username = json_data.get("username")
                print(f"JSON data - username: {username}")
                if username:
                    print(f"Got username from JSON: {username}")
            except Exception as e:
                print(f"JSON parsing failed: {e}")
        
        # Method 3: Try raw body parsing
        if not username:
            try:
                body = await request.body()
                body_str = body.decode('utf-8')
                print(f"Raw body: {body_str}")
                
                # Parse URL-encoded data manually
                if 'username=' in body_str:
                    import urllib.parse
                    parsed = urllib.parse.parse_qs(body_str)
                    if 'username' in parsed:
                        username = parsed['username'][0]
                        print(f"Got username from raw parsing: {username}")
            except Exception as e:
                print(f"Raw body parsing failed: {e}")
        
        print(f"Final username received: {username}")
        
        if not username:
            raise HTTPException(status_code=400, detail="Username is required - check your request format")
        
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
