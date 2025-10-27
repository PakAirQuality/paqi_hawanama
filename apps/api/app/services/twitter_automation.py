"""
Twitter automation service for posting Lahore air quality data.
"""

import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Optional
from zoneinfo import ZoneInfo

import tweepy
from app.core.config import settings

logger = logging.getLogger(__name__)

# Constants
TZ = ZoneInfo("Asia/Karachi")  # Lahore local time


class TwitterAutomationService:
    """Service for automating Twitter posts about Lahore air quality."""
    
    def __init__(self):
        self.client = None
        self._init_twitter_client()
    
    def _init_twitter_client(self) -> None:
        """Initialize Twitter API client using configuration settings."""
        if not all([
            settings.Bearer_token_twitter,
            settings.API_Key_twitter,
            settings.API_Key_Secret_twitter,
            settings.Access_Token_twitter,
            settings.Access_Token_Secret_twitter
        ]):
            raise ValueError("Missing required Twitter API credentials in configuration")
        
        self.client = tweepy.Client(
            bearer_token=settings.Bearer_token_twitter,
            consumer_key=settings.API_Key_twitter,
            consumer_secret=settings.API_Key_Secret_twitter,
            access_token=settings.Access_Token_twitter,
            access_token_secret=settings.Access_Token_Secret_twitter,
            wait_on_rate_limit=True,
        )
        
    async def fetch_lahore_data(self) -> Dict:
        """Fetch Lahore city average air quality data by calling the function directly (no HTTP)."""
        try:
            logger.info("Fetching Lahore city average data directly from database...")
            
            # Import the function we need
            from app.routers.current import city_average
            
            # Call the function directly - it handles its own database session
            result = await city_average(city="Lahore")
            
            # Convert Pydantic model to dict
            data = {
                "city": result.city,
                "avg_pm25_concentration": result.avg_pm25_concentration,
                "aqi": result.aqi,
                "health_message": result.health_message,
                "total_stations": result.total_stations
            }
            
            logger.info(f"Successfully fetched city average data for {data['city']}: PM2.5={data['avg_pm25_concentration']}, AQI={data['aqi']}")
            return data
                
        except Exception as e:
            logger.error(f"Failed to fetch Lahore city average data directly: {e}")
            raise RuntimeError(f"Direct data fetch failed: {e}")
    
    def normalize_city_data(self, data: Dict) -> Dict:
        """Normalize and validate city average data."""
        if not isinstance(data, dict):
            raise ValueError("API response must be a dictionary")
        
        required_fields = ["city", "avg_pm25_concentration", "aqi", "health_message"]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"API response missing required field: {field}")
        
        try:
            pm25 = float(data["avg_pm25_concentration"])
            aqi = int(data["aqi"]) if data["aqi"] is not None else None
            
            if pm25 != pm25:  # Check for NaN
                raise ValueError("PM2.5 concentration is NaN")
                
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid PM2.5 or AQI data: {e}")
        
        return {
            "city": str(data["city"]).strip(),
            "avg_pm25_concentration": pm25,
            "aqi": aqi,
            "health_message": str(data["health_message"]).strip(),
            "total_stations": data.get("total_stations", 0)
        }
    
    def build_tweet_text(self, city_data: Dict) -> str:
        """
        Build Twitter post text from city average data.
        Format: 29-07-2025 15:00; PM2.5 conc. 38.1 μg/m³; 107 Air Quality Index (AQI); Unhealthy for #Sensitive Groups
        """
        timestamp = datetime.now(TZ).strftime("%d-%m-%Y %H:%M")
        pm25 = city_data["avg_pm25_concentration"]
        aqi = city_data["aqi"]
        health_message = city_data["health_message"]
        
        # Clean health message - remove emojis but keep hashtags
        import re
        # Remove emoji characters but keep text and hashtags
        health_clean = re.sub(r'[^\w\s#]', '', health_message).strip()
        # Clean up extra spaces
        health_clean = re.sub(r'\s+', ' ', health_clean)
        
        tweet = f"{timestamp}; PM2.5 conc. {pm25:.1f} μg/m³; {aqi} Air Quality Index (AQI); {health_clean}"
        
        # Ensure within 280 character limit
        if len(tweet) > 280:
            # Truncate health message if needed
            max_health_len = 280 - len(f"{timestamp}; PM2.5 conc. {pm25:.1f} μg/m³; {aqi} Air Quality Index (AQI); ")
            if max_health_len > 0:
                health_clean = health_clean[:max_health_len-3] + "..."
                tweet = f"{timestamp}; PM2.5 conc. {pm25:.1f} μg/m³; {aqi} Air Quality Index (AQI); {health_clean}"
            else:
                # Fallback if even basic info is too long
                tweet = f"{timestamp}; PM2.5 conc. {pm25:.1f} μg/m³; {aqi} AQI"
            
        return tweet
    
    def post_tweet(self, text: str, max_retries: int = 3) -> str:
        """Post tweet and return tweet ID with timeout handling."""
        if not self.client:
            raise RuntimeError("Twitter client not initialized")
        
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Attempting to post tweet (attempt {attempt}/{max_retries})")
                # Set a longer timeout for the HTTP client used by tweepy
                response = self.client.create_tweet(text=text)
                tweet_id = str(response.data["id"])
                logger.info(f"Tweet posted successfully. ID: {tweet_id}")
                return tweet_id
            except tweepy.TweepyException as e:
                last_error = e
                logger.warning(f"Tweet attempt {attempt} failed: {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(2 * attempt)  # Exponential backoff
                    continue
            except Exception as e:
                last_error = e
                logger.warning(f"Unexpected error on attempt {attempt}: {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(2 * attempt)
                    continue
        
        logger.error(f"Failed to post tweet after {max_retries} attempts: {last_error}")
        raise RuntimeError(f"Tweet failed after {max_retries} attempts: {last_error}")
    
    def content_hash(self, text: str) -> str:
        """Generate hash of tweet content for deduplication."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    
    async def post_lahore_pm25_update(self, dry_run: bool = False) -> Dict:
        """
        Main method to fetch city average data and post Twitter update.
        
        Args:
            dry_run: If True, don't actually post to Twitter
            
        Returns:
            Dict with status and details
        """
        try:
            logger.info("Starting Lahore city average Twitter automation")
            
            # Fetch and process data
            raw_data = await self.fetch_lahore_data()
            city_data = self.normalize_city_data(raw_data)
            
            if not city_data or city_data["avg_pm25_concentration"] is None:
                return {
                    "status": "skipped",
                    "message": "No valid city average data to post",
                    "tweet_id": None
                }
            
            # Build tweet
            tweet_text = self.build_tweet_text(city_data)
            tweet_hash = self.content_hash(tweet_text)
            
            logger.info(f"Generated tweet ({len(tweet_text)} chars): {tweet_text}")
            
            if dry_run:
                return {
                    "status": "dry_run",
                    "message": "Dry run - tweet not posted",
                    "tweet_text": tweet_text,
                    "tweet_hash": tweet_hash,
                    "city_data": city_data
                }
            
            # Post to Twitter
            tweet_id = self.post_tweet(tweet_text)
            
            return {
                "status": "success",
                "message": "Tweet posted successfully",
                "tweet_id": tweet_id,
                "tweet_text": tweet_text,
                "tweet_hash": tweet_hash,
                "city_data": city_data
            }
            
        except Exception as e:
            logger.error(f"Twitter automation failed: {e}")
            return {
                "status": "error",
                "message": f"Failed to post tweet: {str(e)}",
                "tweet_id": None
            }