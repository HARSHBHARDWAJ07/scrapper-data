import os
import csv
import io
import time
import random
import re
from datetime import datetime
from typing import List, Dict

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService

# ----------------------------
# FASTAPI APP
# ----------------------------
app = FastAPI(title="Instagram Scraper API", version="2.0")

# ----------------------------
# MODELS
# ----------------------------
class ScrapeRequest(BaseModel):
    username: str

# ----------------------------
# SELENIUM SETUP
# ----------------------------
def create_driver():
    """Create and configure Chrome driver"""
    chrome_options = Options()
    
    # Basic options
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Stealth options to avoid detection
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    
    # Headless option (uncomment for production)
    chrome_options.add_argument("--headless=new")
    
    # Set user agent
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Initialize driver
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=chrome_options
    )
    
    # Execute stealth script
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

# ----------------------------
# INSTAGRAM SCRAPER
# ----------------------------
class InstagramScraper:
    def __init__(self):
        self.driver = create_driver()
        self.wait = WebDriverWait(self.driver, 20)
    
    def login(self, username: str, password: str):
        """Login to Instagram account"""
        try:
            print("Navigating to Instagram login page...")
            self.driver.get("https://www.instagram.com/accounts/login/")
            time.sleep(random.uniform(3, 5))
            
            # Accept cookies if prompted (EU)
            try:
                cookie_btn = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Allow')]"))
                )
                cookie_btn.click()
                time.sleep(1)
            except:
                pass
            
            # Fill login form
            print("Filling login form...")
            username_field = self.wait.until(
                EC.presence_of_element_located((By.NAME, "username"))
            )
            password_field = self.driver.find_element(By.NAME, "password")
            
            # Type slowly to mimic human behavior
            self.type_like_human(username_field, username)
            time.sleep(random.uniform(0.5, 1.5))
            self.type_like_human(password_field, password)
            time.sleep(random.uniform(0.5, 1.5))
            
            # Click login button
            login_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")
            login_btn.click()
            time.sleep(random.uniform(4, 6))
            
            # Handle "Save Info" prompt
            try:
                not_now_btn = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//div[contains(text(), 'Not now')]"))
                )
                not_now_btn.click()
                time.sleep(2)
            except:
                pass
            
            # Handle notification prompt
            try:
                not_now_btn = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Not Now')]"))
                )
                not_now_btn.click()
                time.sleep(2)
            except:
                pass
            
            print("Login successful!")
            return True
            
        except Exception as e:
            print(f"Login failed: {str(e)}")
            return False
    
    def type_like_human(self, element, text):
        """Type text in a human-like manner"""
        for character in text:
            element.send_keys(character)
            time.sleep(random.uniform(0.05, 0.15))
    
    def scrape_posts(self, username: str, max_posts: int = 20):
        """Scrape posts from a profile"""
        try:
            print(f"Navigating to profile: {username}")
            self.driver.get(f"https://www.instagram.com/{username}/")
            time.sleep(random.uniform(4, 6))
            
            # Check if profile exists
            if "Sorry, this page isn't available." in self.driver.page_source:
                raise HTTPException(status_code=404, detail=f"User {username} not found")
            
            # Check if profile is private
            if "This account is private" in self.driver.page_source:
                raise HTTPException(status_code=403, detail=f"User {username} has a private profile")
            
            posts = []
            post_urls = set()
            scroll_attempts = 0
            max_scroll_attempts = 8
            
            print("Scrolling to load posts...")
            # Scroll to load posts
            while len(post_urls) < max_posts and scroll_attempts < max_scroll_attempts:
                # Find all post links
                post_elements = self.driver.find_elements(
                    By.XPATH, "//a[contains(@href, '/p/') and contains(@href, '/"+username+"/')]"
                )
                
                for element in post_elements:
                    href = element.get_attribute("href")
                    if href and href not in post_urls:
                        post_urls.add(href)
                
                # Scroll down
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(2, 4))
                
                # Check if we're getting new posts
                if len(post_urls) > len(posts):
                    posts = list(post_urls)
                    scroll_attempts = 0
                else:
                    scroll_attempts += 1
            
            # Limit to max_posts
            post_urls = list(post_urls)[:max_posts]
            print(f"Found {len(post_urls)} posts. Starting detailed scraping...")
            
            # Scrape each post
            post_data = []
            for i, post_url in enumerate(post_urls):
                try:
                    print(f"Scraping post {i+1}/{len(post_urls)}: {post_url}")
                    post_info = self.scrape_single_post(post_url)
                    post_data.append(post_info)
                    time.sleep(random.uniform(2, 4))  # Be polite with delays
                except Exception as e:
                    print(f"Failed to scrape post {post_url}: {str(e)}")
                    continue
            
            return post_data
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error scraping posts: {str(e)}")
    
    def scrape_single_post(self, post_url: str):
        """Scrape data from a single post"""
        self.driver.get(post_url)
        time.sleep(random.uniform(3, 5))
        
        post_data = {
            "post_url": post_url,
            "shortcode": post_url.split("/p/")[1].strip("/"),
            "scraped_at": datetime.utcnow().isoformat(),
            "title": "",
            "caption": "",
            "hashtags": "",
            "likes": "0",
            "comments_count": "0",
            "comments": "",
            "timestamp": "",
            "is_video": "False"
        }
        
        try:
            # Get caption and hashtags
            try:
                caption_element = self.wait.until(
                    EC.presence_of_element_located((By.XPATH, "//h1[contains(@class, '_aacl')] | //div[contains(@class, '_a9zs')]"))
                )
                caption_text = caption_element.text
                post_data['caption'] = caption_text
                
                # Extract hashtags from caption
                hashtags = re.findall(r'#\w+', caption_text)
                post_data['hashtags'] = ', '.join(hashtags)
                
                # Use first part of caption as title
                if caption_text:
                    post_data['title'] = caption_text[:50] + "..." if len(caption_text) > 50 else caption_text
            except:
                pass
            
            # Get likes
            try:
                # Try multiple selectors for likes
                selectors = [
                    "//section[contains(@class, '_ae5m')]//span//span",
                    "//a[contains(@href, 'liked_by')]//span",
                    "//span[contains(text(), 'likes')]",
                    "//span[contains(text(), 'Likes')]/preceding-sibling::span"
                ]
                
                for selector in selectors:
                    try:
                        likes_element = self.driver.find_element(By.XPATH, selector)
                        likes_text = likes_element.text.strip()
                        if likes_text and likes_text.isdigit():
                            post_data['likes'] = likes_text
                            break
                    except:
                        continue
            except:
                pass
            
            # Get timestamp
            try:
                time_element = self.driver.find_element(By.XPATH, "//time[@datetime]")
                post_data['timestamp'] = time_element.get_attribute("datetime")
            except:
                pass
            
            # Check if video
            try:
                video_indicator = self.driver.find_element(
                    By.XPATH, "//span[contains(@class, 'video')] | //div[contains(@aria-label, 'Video')]"
                )
                post_data['is_video'] = "True"
            except:
                pass
            
            # Get comments
            try:
                # Try to load more comments if available
                try:
                    view_more_btn = self.driver.find_element(
                        By.XPATH, "//div[contains(text(), 'View') and contains(text(), 'comments')] | //span[contains(text(), 'Load') and contains(text(), 'comments')]"
                    )
                    view_more_btn.click()
                    time.sleep(2)
                except:
                    pass
                
                # Extract comments
                comment_elements = self.driver.find_elements(
                    By.XPATH, "//div[contains(@class, '_a9zr')]//div[contains(@class, '_a9zs')]"
                )
                
                comments = []
                for comment_element in comment_elements[:10]:  # Limit to first 10 comments
                    comments.append(comment_element.text)
                
                post_data['comments'] = " | ".join(comments)
                post_data['comments_count'] = str(len(comments))
                
            except:
                pass
                
        except Exception as e:
            print(f"Error scraping post details: {str(e)}")
        
        return post_data
    
    def close(self):
        """Close the driver"""
        self.driver.quit()

# ----------------------------
# FASTAPI ROUTES
# ----------------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Instagram Scraper API is running 🚀"}

@app.post("/scrape_posts")
def scrape_posts_endpoint(payload: ScrapeRequest):
    username = payload.username.lower().strip()
    scraper = InstagramScraper()
    
    try:
        # Login with environment variables (optional)
        ig_username = os.getenv("IG_USERNAME")
        ig_password = os.getenv("IG_PASSWORD")
        
        if ig_username and ig_password:
            print("Attempting to login with provided credentials...")
            if not scraper.login(ig_username, ig_password):
                print("Login failed, continuing without authentication...")
        
        posts = scraper.scrape_posts(username, max_posts=20)
        
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
    finally:
        scraper.close()

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

