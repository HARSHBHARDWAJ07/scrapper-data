import os
import csv
import io
import time
import random
import re
import subprocess
import sys
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
app = FastAPI(title="Instagram Scraper API", version="2.1")

# ----------------------------
# MODELS
# ----------------------------
class ScrapeRequest(BaseModel):
    username: str

# ----------------------------
# CHROME INSTALLATION & SETUP
# ----------------------------
def install_chrome():
    """Install Chrome browser on Ubuntu/Debian systems"""
    try:
        print("Checking if Chrome is installed...")
        result = subprocess.run(['google-chrome', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Chrome already installed: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass

    try:
        print("Installing Chrome...")
        
        # Update package list
        subprocess.run(['apt-get', 'update'], check=True)
        
        # Install dependencies
        subprocess.run([
            'apt-get', 'install', '-y',
            'wget', 'gnupg', 'unzip', 'curl', 'xvfb'
        ], check=True)
        
        # Add Google's signing key
        subprocess.run([
            'wget', '-q', '-O', '-',
            'https://dl.google.com/linux/linux_signing_key.pub'
        ], stdout=subprocess.PIPE, check=True)
        
        # Add Chrome repository
        with open('/etc/apt/sources.list.d/google-chrome.list', 'w') as f:
            f.write('deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main\n')
        
        # Update and install Chrome
        subprocess.run(['apt-get', 'update'], check=True)
        subprocess.run(['apt-get', 'install', '-y', 'google-chrome-stable'], check=True)
        
        print("Chrome installed successfully!")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"Failed to install Chrome: {e}")
        return False
    except Exception as e:
        print(f"Error during Chrome installation: {e}")
        return False

def create_driver():
    """Create and configure Chrome driver"""
    try:
        chrome_options = Options()
        
        # Essential options for server deployment
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--disable-images")
        chrome_options.add_argument("--disable-javascript")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-popup-blocking")
        
        # Memory and performance optimizations
        chrome_options.add_argument("--memory-pressure-off")
        chrome_options.add_argument("--max_old_space_size=4096")
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-renderer-backgrounding")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        
        # Stealth options
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        
        # User agent
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # Window size
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Try to use system Chrome first, then fall back to ChromeDriverManager
        chrome_paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium"
        ]
        
        chrome_binary = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_binary = path
                break
        
        if chrome_binary:
            chrome_options.binary_location = chrome_binary
            print(f"Using Chrome binary: {chrome_binary}")
        
        # Initialize driver with error handling
        try:
            # Try with specific Chrome version first
            driver = webdriver.Chrome(
                service=ChromeService(ChromeDriverManager(version="120.0.6099.109").install()),
                options=chrome_options
            )
        except Exception as e1:
            print(f"Failed with specific version: {e1}")
            try:
                # Try with latest version
                driver = webdriver.Chrome(
                    service=ChromeService(ChromeDriverManager().install()),
                    options=chrome_options
                )
            except Exception as e2:
                print(f"Failed with latest version: {e2}")
                # Try with system chromedriver if available
                try:
                    driver = webdriver.Chrome(options=chrome_options)
                except Exception as e3:
                    print(f"All Chrome driver attempts failed: {e3}")
                    raise Exception("Could not initialize Chrome driver")
        
        # Execute stealth script
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
        driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})")
        
        return driver
        
    except Exception as e:
        print(f"Error creating driver: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize browser: {str(e)}")

# ----------------------------
# INSTAGRAM SCRAPER
# ----------------------------
class InstagramScraper:
    def __init__(self):
        try:
            self.driver = create_driver()
            self.wait = WebDriverWait(self.driver, 30)
            print("Instagram scraper initialized successfully")
        except Exception as e:
            print(f"Failed to initialize scraper: {e}")
            raise
    
    def login(self, username: str, password: str):
        """Login to Instagram account"""
        try:
            print("Navigating to Instagram login page...")
            self.driver.get("https://www.instagram.com/accounts/login/")
            time.sleep(random.uniform(5, 8))
            
            # Accept cookies if prompted
            try:
                cookie_selectors = [
                    "//button[contains(text(), 'Accept')]",
                    "//button[contains(text(), 'Allow')]",
                    "//button[contains(text(), 'Accept All')]"
                ]
                for selector in cookie_selectors:
                    try:
                        cookie_btn = WebDriverWait(self.driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                        cookie_btn.click()
                        time.sleep(2)
                        break
                    except:
                        continue
            except:
                pass
            
            # Fill login form
            print("Filling login form...")
            username_field = self.wait.until(
                EC.presence_of_element_located((By.NAME, "username"))
            )
            password_field = self.driver.find_element(By.NAME, "password")
            
            # Clear fields and type
            username_field.clear()
            password_field.clear()
            
            self.type_like_human(username_field, username)
            time.sleep(random.uniform(1, 2))
            self.type_like_human(password_field, password)
            time.sleep(random.uniform(1, 2))
            
            # Click login button
            login_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")
            login_btn.click()
            time.sleep(random.uniform(6, 10))
            
            # Handle post-login prompts
            self.handle_post_login_prompts()
            
            # Check if login was successful
            if "challenge" in self.driver.current_url.lower() or "login" in self.driver.current_url.lower():
                print("Login may have failed - still on login/challenge page")
                return False
            
            print("Login successful!")
            return True
            
        except Exception as e:
            print(f"Login failed: {str(e)}")
            return False
    
    def handle_post_login_prompts(self):
        """Handle various prompts after login"""
        prompts = [
            "//div[contains(text(), 'Not now')] | //div[contains(text(), 'Not Now')]",
            "//button[contains(text(), 'Not now')] | //button[contains(text(), 'Not Now')]",
            "//button[contains(text(), 'Skip')] | //div[contains(text(), 'Skip')]",
            "//button[contains(text(), 'Maybe Later')]",
            "//svg[@aria-label='Close']/.."
        ]
        
        for prompt in prompts:
            try:
                element = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, prompt))
                )
                element.click()
                time.sleep(2)
                print("Dismissed a prompt")
            except:
                continue
    
    def type_like_human(self, element, text):
        """Type text in a human-like manner"""
        for character in text:
            element.send_keys(character)
            time.sleep(random.uniform(0.08, 0.2))
    
    def scrape_posts(self, username: str, max_posts: int = 20):
        """Scrape posts from a profile"""
        try:
            print(f"Navigating to profile: {username}")
            profile_url = f"https://www.instagram.com/{username}/"
            self.driver.get(profile_url)
            time.sleep(random.uniform(5, 8))
            
            # Check for various error conditions
            page_source = self.driver.page_source.lower()
            
            if "sorry, this page isn't available" in page_source:
                raise HTTPException(status_code=404, detail=f"User {username} not found")
            
            if "this account is private" in page_source:
                raise HTTPException(status_code=403, detail=f"User {username} has a private profile")
            
            if "user not found" in page_source:
                raise HTTPException(status_code=404, detail=f"User {username} not found")
            
            # Wait for posts to load
            time.sleep(5)
            
            posts = []
            post_urls = set()
            scroll_attempts = 0
            max_scroll_attempts = 10
            
            print("Collecting post URLs...")
            
            while len(post_urls) < max_posts and scroll_attempts < max_scroll_attempts:
                # Multiple selectors for post links
                post_selectors = [
                    f"//a[contains(@href, '/p/')]",
                    f"//a[contains(@href, '/reel/')]",
                    "//article//a[@href]"
                ]
                
                for selector in post_selectors:
                    try:
                        post_elements = self.driver.find_elements(By.XPATH, selector)
                        for element in post_elements:
                            href = element.get_attribute("href")
                            if href and ("/p/" in href or "/reel/" in href):
                                if href not in post_urls:
                                    post_urls.add(href)
                                    if len(post_urls) >= max_posts:
                                        break
                    except:
                        continue
                    
                    if len(post_urls) >= max_posts:
                        break
                
                if len(post_urls) >= max_posts:
                    break
                
                # Scroll down
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(3, 5))
                scroll_attempts += 1
                
                print(f"Found {len(post_urls)} posts so far...")
            
            if not post_urls:
                print("No posts found - checking if profile has posts...")
                # Try alternative method to find posts
                try:
                    self.driver.execute_script("window.scrollTo(0, 500);")
                    time.sleep(3)
                    post_elements = self.driver.find_elements(By.TAG_NAME, "a")
                    for element in post_elements:
                        href = element.get_attribute("href")
                        if href and "/p/" in href:
                            post_urls.add(href)
                except:
                    pass
            
            if not post_urls:
                return []  # Return empty list instead of raising error
            
            # Limit to max_posts
            post_urls = list(post_urls)[:max_posts]
            print(f"Scraping {len(post_urls)} posts...")
            
            # Scrape each post
            post_data = []
            for i, post_url in enumerate(post_urls):
                try:
                    print(f"Scraping post {i+1}/{len(post_urls)}")
                    post_info = self.scrape_single_post(post_url)
                    post_data.append(post_info)
                    time.sleep(random.uniform(3, 6))
                except Exception as e:
                    print(f"Failed to scrape post {post_url}: {str(e)}")
                    continue
            
            return post_data
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"Error scraping posts: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error scraping posts: {str(e)}")
    
    def scrape_single_post(self, post_url: str):
        """Scrape data from a single post"""
        try:
            self.driver.get(post_url)
            time.sleep(random.uniform(4, 7))
            
            post_data = {
                "post_url": post_url,
                "shortcode": post_url.split("/p/")[1].strip("/") if "/p/" in post_url else post_url.split("/reel/")[1].strip("/"),
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
            
            # Get caption
            caption_selectors = [
                "//h1",
                "//div[contains(@class, '_a9zs')]",
                "//span[contains(@class, '_aacl')]",
                "//article//div//span"
            ]
            
            for selector in caption_selectors:
                try:
                    caption_element = self.driver.find_element(By.XPATH, selector)
                    caption_text = caption_element.text.strip()
                    if caption_text and len(caption_text) > 10:  # Avoid empty or very short text
                        post_data['caption'] = caption_text
                        
                        # Extract hashtags
                        hashtags = re.findall(r'#\w+', caption_text)
                        post_data['hashtags'] = ', '.join(hashtags)
                        
                        # Set title
                        post_data['title'] = caption_text[:50] + "..." if len(caption_text) > 50 else caption_text
                        break
                except:
                    continue
            
            # Get likes
            likes_selectors = [
                "//a[contains(@href, 'liked_by')]//span",
                "//span[contains(text(), 'likes')]",
                "//button[contains(@class, '_abl-')]//span"
            ]
            
            for selector in likes_selectors:
                try:
                    likes_elements = self.driver.find_elements(By.XPATH, selector)
                    for element in likes_elements:
                        likes_text = element.text.strip().replace(',', '').replace('.', '')
                        if likes_text.isdigit():
                            post_data['likes'] = likes_text
                            break
                    if post_data['likes'] != "0":
                        break
                except:
                    continue
            
            # Get timestamp
            try:
                time_element = self.driver.find_element(By.XPATH, "//time[@datetime]")
                post_data['timestamp'] = time_element.get_attribute("datetime")
            except:
                try:
                    time_element = self.driver.find_element(By.XPATH, "//time")
                    post_data['timestamp'] = time_element.get_attribute("title")
                except:
                    pass
            
            # Check if video
            if "/reel/" in post_url:
                post_data['is_video'] = "True"
            else:
                try:
                    video_indicators = [
                        "//video",
                        "//div[contains(@aria-label, 'Video')]",
                        "//span[contains(text(), 'REEL')]"
                    ]
                    for indicator in video_indicators:
                        if self.driver.find_elements(By.XPATH, indicator):
                            post_data['is_video'] = "True"
                            break
                except:
                    pass
            
            # Get comments (simplified)
            try:
                comment_elements = self.driver.find_elements(By.XPATH, "//div[contains(@class, '_a9zr')]//span")[:5]
                comments = []
                for element in comment_elements:
                    comment_text = element.text.strip()
                    if comment_text and len(comment_text) > 5:
                        comments.append(comment_text)
                
                if comments:
                    post_data['comments'] = " | ".join(comments)
                    post_data['comments_count'] = str(len(comments))
            except:
                pass
                
        except Exception as e:
            print(f"Error scraping post details: {str(e)}")
        
        return post_data
    
    def close(self):
        """Close the driver"""
        try:
            if hasattr(self, 'driver') and self.driver:
                self.driver.quit()
        except Exception as e:
            print(f"Error closing driver: {e}")

# ----------------------------
# STARTUP EVENT
# ----------------------------
@app.on_event("startup")
async def startup_event():
    """Install Chrome on startup if needed"""
    if os.getenv("INSTALL_CHROME", "false").lower() == "true":
        print("Installing Chrome browser...")
        install_chrome()

# ----------------------------
# FASTAPI ROUTES
# ----------------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Instagram Scraper API is running 🚀", "version": "2.1"}

@app.get("/health")
def health_check():
    """Health check endpoint"""
    try:
        # Quick driver test
        test_driver = create_driver()
        test_driver.quit()
        return {"status": "healthy", "chrome": "available"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.post("/scrape_posts")
def scrape_posts_endpoint(payload: ScrapeRequest):
    """Scrape Instagram posts for a given username"""
    username = payload.username.lower().strip().replace("@", "")
    
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    
    scraper = None
    try:
        print(f"Starting scrape for user: {username}")
        scraper = InstagramScraper()
        
        # Optional login
        ig_username = os.getenv("IG_USERNAME")
        ig_password = os.getenv("IG_PASSWORD")
        
        if ig_username and ig_password:
            print("Attempting to login...")
            login_success = scraper.login(ig_username, ig_password)
            if not login_success:
                print("Login failed, continuing without authentication...")
        
        # Scrape posts
        posts = scraper.scrape_posts(username, max_posts=20)
        
        if not posts:
            raise HTTPException(status_code=404, detail=f"No posts found for user: {username}")
        
        print(f"Successfully scraped {len(posts)} posts")
        
        # Generate CSV
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
        error_msg = f"Unexpected error: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
    finally:
        if scraper:
            scraper.close()

# ----------------------------
# ENTRY POINT
# ----------------------------
if __name__ == "__main__":
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=int(os.getenv("PORT", 8000)),
        timeout_keep_alive=300,
        timeout=300
    )
