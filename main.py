import os
import csv
import io
import requests
import json
import time
from datetime import datetime
from typing import List, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------------
# FASTAPI APP
# ----------------------------
app = FastAPI(
    title="Instagram Post Extractor", 
    version="4.0",
    description="Extract Instagram posts with title, caption, and hashtags only"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# MODELS
# ----------------------------
class ScrapeRequest(BaseModel):
    username: str = Field(..., description="Instagram username (without @)")
    limit: Optional[int] = Field(default=50, ge=1, le=1000, description="Number of posts to extract (1-1000)")
    extract_all: Optional[bool] = Field(default=False, description="Extract all available posts (ignores limit)")

class PostData(BaseModel):
    title: str
    caption: str
    hashtags: str

class ScrapeResponse(BaseModel):
    status: str
    username: str
    total_posts: int
    extracted_posts: int
    message: str

# ----------------------------
# APIFY INSTAGRAM SCRAPER - SIMPLIFIED
# ----------------------------
class InstagramPostExtractor:
    def __init__(self, apify_token: str):
        self.apify_token = apify_token
        self.base_url = "https://api.apify.com/v2"
        self.actor_id = "apify/instagram-scraper"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.apify_token}",
            "Content-Type": "application/json"
        })
        
    def extract_posts(
        self, 
        username: str, 
        limit: int = 50,
        extract_all: bool = False
    ) -> List[Dict]:
        """
        Extract Instagram posts with only essential data: title, caption, hashtags
        """
        
        # Clean username
        username = username.replace("@", "").strip().lower()
        
        # Set limit - if extract_all is True, set high limit
        actual_limit = 10000 if extract_all else limit
        
        # Simplified configuration - only extract what we need
        run_input = {
            "directUrls": [f"https://www.instagram.com/{username}/"],
            "resultsType": "posts",
            "resultsLimit": actual_limit,
            "searchType": "hashtag",
            "searchLimit": 1,
            "addParentData": False,
            "enhanceUserSearchWithFacebookPage": False,
            "likedByLimit": 0,
            "includeLocationInfo": False,
            "commentsLimit": 0,  # No comments needed
            "extendOutputFunction": "",
            "extendScraperFunction": "",
            "customData": {},
            "proxy": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"]
            }
        }
        
        logger.info(f"🚀 Extracting posts for @{username} {'(ALL POSTS)' if extract_all else f'(Limit: {limit})'}")
        start_time = time.time()
        
        try:
            # Start the extraction
            run_url = f"{self.base_url}/acts/{self.actor_id}/runs"
            
            response = self.session.post(run_url, json=run_input, timeout=30)
            
            if response.status_code != 201:
                logger.error(f"Failed to start extraction: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=500, 
                    detail=f"Failed to start extraction: {response.text}"
                )
            
            run_data = response.json()
            run_id = run_data["data"]["id"]
            logger.info(f"⏳ Extraction started. Run ID: {run_id}")
            
            # Wait for completion and get results
            results = self._wait_for_results(run_id, extract_all)
            
            end_time = time.time()
            logger.info(f"✅ Extraction completed in {end_time - start_time:.2f} seconds")
            logger.info(f"📊 Extracted {len(results)} posts")
            
            return results
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during extraction: {e}")
            raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error during extraction: {e}")
            raise HTTPException(status_code=500, detail=f"Extraction error: {str(e)}")
    
    def _wait_for_results(self, run_id: str, extract_all: bool = False) -> List[Dict]:
        """Wait for extraction to complete and return results"""
        
        status_url = f"{self.base_url}/actor-runs/{run_id}"
        dataset_url = f"{self.base_url}/actor-runs/{run_id}/dataset/items"
        
        # Longer timeout for extract_all option
        max_wait_time = 600 if extract_all else 300
        start_wait_time = time.time()
        
        # Poll for completion with timeout
        while time.time() - start_wait_time < max_wait_time:
            try:
                response = self.session.get(status_url, timeout=30)
                
                if response.status_code != 200:
                    logger.warning(f"Status check failed: {response.status_code}")
                    time.sleep(5)
                    continue
                
                status_data = response.json()
                status = status_data["data"]["status"]
                
                if status == "SUCCEEDED":
                    logger.info("✅ Extraction completed successfully")
                    break
                elif status == "FAILED":
                    error_msg = status_data["data"].get("statusMessage", "Unknown error")
                    logger.error(f"Extraction failed: {error_msg}")
                    raise HTTPException(status_code=500, detail=f"Extraction failed: {error_msg}")
                elif status in ["RUNNING", "READY"]:
                    logger.info(f"⏳ Status: {status}...")
                    time.sleep(15 if extract_all else 10)
                else:
                    logger.info(f"🔄 Status: {status}")
                    time.sleep(5)
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"Network error during status check: {e}")
                time.sleep(10)
                continue
        else:
            # Timeout reached
            raise HTTPException(status_code=408, detail="Extraction timeout - try reducing the limit or try again later")
        
        # Get results
        try:
            response = self.session.get(dataset_url, timeout=60)
            if response.status_code == 200:
                results = response.json()
                return results if results else []
            else:
                logger.error(f"Failed to get results: {response.status_code} - {response.text}")
                raise HTTPException(status_code=500, detail=f"Failed to get results: {response.text}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting results: {e}")
            raise HTTPException(status_code=500, detail=f"Network error getting results: {str(e)}")
    
    def process_results(self, raw_results: List[Dict]) -> List[Dict]:
        """Process and extract only title, caption, and hashtags"""
        if not raw_results:
            return []
            
        processed_posts = []
        
        for i, post in enumerate(raw_results):
            try:
                # Extract caption
                caption = post.get("caption", "").strip()
                
                # Create title from caption (full caption as title if no separate title exists)
                title = caption if caption else f"Post {i+1}"
                
                # Extract hashtags
                hashtags_list = post.get("hashtags", [])
                hashtags = ", ".join([f"#{tag}" if not tag.startswith("#") else tag for tag in hashtags_list])
                
                # Create minimal post data with only required fields
                processed_post = {
                    "title": title,
                    "caption": caption,
                    "hashtags": hashtags
                }
                
                processed_posts.append(processed_post)
                
            except Exception as e:
                logger.warning(f"⚠️ Error processing post {i}: {e}")
                continue
        
        return processed_posts

# ----------------------------
# UTILITY FUNCTIONS
# ----------------------------
def validate_username(username: str) -> str:
    """Validate and clean Instagram username"""
    username = username.strip().replace("@", "").lower()
    
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
    
    if len(username) > 30:
        raise HTTPException(status_code=400, detail="Username too long (max 30 characters)")
    
    # Basic username validation
    import re
    if not re.match("^[a-zA-Z0-9._]+$", username):
        raise HTTPException(status_code=400, detail="Invalid username format (only letters, numbers, dots, underscores allowed)")
    
    return username

def create_csv_response(posts: List[Dict], username: str) -> StreamingResponse:
    """Create CSV response with only title, caption, and hashtags"""
    output = io.StringIO()
    fieldnames = ["title", "caption", "hashtags"]
    
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(posts)

    buffer = io.BytesIO()
    buffer.write(output.getvalue().encode("utf-8"))
    buffer.seek(0)
    
    headers = {
        "Content-Disposition": f"attachment; filename={username}_posts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    }
    
    return StreamingResponse(
        io.BytesIO(buffer.read()), 
        media_type="text/csv", 
        headers=headers
    )

# ----------------------------
# FASTAPI ROUTES
# ----------------------------
@app.get("/")
def root():
    return {
        "status": "ok", 
        "message": "Instagram Post Extractor API 🚀",
        "version": "4.0",
        "description": "Extract Instagram posts with title, caption, and hashtags only",
        "endpoints": {
            "extract": "/extract_posts",
            "extract_all": "/extract_posts (with extract_all=true)",
            "health": "/health",
            "docs": "/docs"
        }
    }

@app.get("/health")
def health_check():
    """Health check endpoint"""
    apify_token = os.getenv("APIFY_TOKEN")
    
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "apify_configured": bool(apify_token),
        "version": "4.0",
        "features": ["title", "caption", "hashtags", "custom_limits", "extract_all"]
    }

@app.post("/extract_posts")
def extract_posts_endpoint(payload: ScrapeRequest):
    """
    Extract Instagram posts with only essential data
    
    Parameters:
    - username: Instagram username (without @)
    - limit: Number of posts to extract (1-1000, default: 50)
    - extract_all: Extract all available posts (ignores limit)
    
    Returns:
    - CSV file with title, caption, and hashtags only
    """
    
    # Validate input
    username = validate_username(payload.username)
    limit = payload.limit or 50
    extract_all = payload.extract_all or False
    
    # Validate limit
    if not extract_all and (limit < 1 or limit > 1000):
        raise HTTPException(
            status_code=400, 
            detail="Limit must be between 1 and 1000 posts"
        )
    
    # Get Apify token from environment
    apify_token = os.getenv("APIFY_TOKEN")
    if not apify_token:
        logger.error("APIFY_TOKEN environment variable not set")
        raise HTTPException(
            status_code=500, 
            detail="APIFY_TOKEN environment variable not set. Please configure your Apify API token."
        )
    
    logger.info(f"Starting extraction for @{username} {'(ALL POSTS)' if extract_all else f'(Limit: {limit})'}")
    
    try:
        extractor = InstagramPostExtractor(apify_token)
        
        # Extract posts
        raw_posts = extractor.extract_posts(
            username=username,
            limit=limit,
            extract_all=extract_all
        )
        
        # Process the results (only title, caption, hashtags)
        posts = extractor.process_results(raw_posts)
        
        if not posts:
            logger.warning(f"No posts found for user: {username}")
            raise HTTPException(
                status_code=404, 
                detail=f"No posts found for user '{username}'. The user might not exist, be private, or have no posts."
            )
        
        logger.info(f"Successfully extracted {len(posts)} posts for @{username}")
        
        # Return CSV file with only essential data
        return create_csv_response(posts, username)
        
    except HTTPException as e:
        # Re-raise HTTP exceptions as-is
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in extract_posts_endpoint: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"An unexpected error occurred: {str(e)}"
        )

@app.get("/extract_posts/{username}")
def extract_posts_get_endpoint(
    username: str, 
    limit: int = Query(default=50, ge=1, le=1000, description="Number of posts to extract"),
    extract_all: bool = Query(default=False, description="Extract all available posts")
):
    """
    Alternative GET endpoint for extracting posts
    """
    payload = ScrapeRequest(
        username=username, 
        limit=limit,
        extract_all=extract_all
    )
    return extract_posts_endpoint(payload)

@app.post("/extract_all_posts/{username}")
def extract_all_posts_endpoint(username: str):
    """
    Convenience endpoint to extract ALL posts from a user
    """
    payload = ScrapeRequest(
        username=username,
        extract_all=True
    )
    return extract_posts_endpoint(payload)

# Error handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": "Endpoint not found", "message": "The requested endpoint does not exist"}
    )

@app.exception_handler(500)
async def internal_error_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "message": "Something went wrong on our end"}
    )

# ----------------------------
# ENTRY POINT
# ----------------------------
if __name__ == "__main__":
    # Check for required environment variables
    if not os.getenv("APIFY_TOKEN"):
        print("⚠️ Warning: APIFY_TOKEN environment variable not set!")
        print("Get your token from: https://console.apify.com/account/integrations")
    
    port = int(os.getenv("PORT", 8000))
    
    print(f"🚀 Starting Instagram Post Extractor API on port {port}")
    print("📚 API Documentation available at: http://localhost:8000/docs")
    print("✨ Features: Title, Caption, Hashtags extraction with custom limits")
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        timeout_keep_alive=300,
        access_log=True
    )
