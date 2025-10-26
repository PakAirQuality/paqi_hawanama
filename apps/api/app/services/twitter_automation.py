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
from app.core.database import get_database

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
        """Fetch top 10 PM2.5 stations data by calling the function directly (no HTTP)."""
        try:
            logger.info("Fetching Lahore data directly from database...")
            
            # Import the function we need
            from app.routers.current import city_top10_pm25
            
            # Get database session
            async for db in get_database():
                # Call the function directly instead of HTTP request
                result = await city_top10_pm25(city="Lahore", db=db)
                
                # Convert Pydantic model to dict
                data = {
                    "city": result.city,
                    "top_stations": [
                        {
                            "station_id": station.station_id,
                            "station_name": station.station_name,
                            "pm25_concentration": station.pm25_concentration
                        }
                        for station in result.top_stations
                    ],
                    "total_stations": result.total_stations
                }
                
                logger.info(f"Successfully fetched data for {len(data['top_stations'])} stations")
                return data
                
        except Exception as e:
            logger.error(f"Failed to fetch Lahore data directly: {e}")
            raise RuntimeError(f"Direct data fetch failed: {e}")
    
    def normalize_station_data(self, data: Dict) -> List[Dict]:
        """Normalize and clean station data."""
        top_stations = data.get("top_stations", [])
        if not isinstance(top_stations, list):
            raise ValueError("API response missing 'top_stations' list")
        
        cleaned = []
        for station in top_stations:
            name = str(station.get("station_name", "—")).strip()
            try:
                pm25 = float(station.get("pm25_concentration", float("nan")))
            except Exception:
                pm25 = float("nan")
            
            if name and pm25 == pm25:  # exclude NaN
                cleaned.append({
                    "station_name": name,
                    "pm25_concentration": pm25
                })
        
        # Sort by PM2.5 concentration descending and keep top 10
        cleaned.sort(key=lambda x: x["pm25_concentration"], reverse=True)
        return cleaned[:10]
    
    def build_tweet_text(self, stations: List[Dict]) -> str:
        """Build Twitter post text from station data."""
        timestamp = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
        header = f"Lahore PM2.5 • Top 10 (last 24h) • {timestamp}\n"
        
        lines = []
        for i, station in enumerate(stations, 1):
            name = station["station_name"]
            if len(name) > 22:
                name = name[:19] + "..."
            pm25 = station["pm25_concentration"]
            lines.append(f"{i}) {name}: {pm25:.1f} µg/m³")
        
        body = "\n".join(lines)
        tail = "\n#AirQuality #PM25 #Lahore"
        tweet = header + body + tail
        
        # Ensure within 280 character limit
        if len(tweet) > 280:
            tweet = header + body  # Remove hashtags first
        
        while len(tweet) > 280 and lines:
            lines.pop()  # Remove entries until it fits
            body = "\n".join(lines)
            tweet = header + body
        
        if len(tweet) > 280:
            tweet = tweet[:279]  # Hard cap fallback
            
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
        Main method to fetch data and post Twitter update.
        
        Args:
            dry_run: If True, don't actually post to Twitter
            
        Returns:
            Dict with status and details
        """
        try:
            logger.info("Starting Lahore PM2.5 Twitter automation")
            
            # Fetch and process data
            raw_data = await self.fetch_lahore_data()
            stations = self.normalize_station_data(raw_data)
            
            if not stations:
                return {
                    "status": "skipped",
                    "message": "No valid station data to post",
                    "tweet_id": None
                }
            
            # Build tweet
            tweet_text = self.build_tweet_text(stations)
            tweet_hash = self.content_hash(tweet_text)
            
            logger.info(f"Generated tweet ({len(tweet_text)} chars): {tweet_text}")
            
            if dry_run:
                return {
                    "status": "dry_run",
                    "message": "Dry run - tweet not posted",
                    "tweet_text": tweet_text,
                    "tweet_hash": tweet_hash,
                    "stations_count": len(stations)
                }
            
            # Post to Twitter
            tweet_id = self.post_tweet(tweet_text)
            
            return {
                "status": "success",
                "message": "Tweet posted successfully",
                "tweet_id": tweet_id,
                "tweet_text": tweet_text,
                "tweet_hash": tweet_hash,
                "stations_count": len(stations)
            }
            
        except Exception as e:
            logger.error(f"Twitter automation failed: {e}")
            return {
                "status": "error",
                "message": f"Failed to post tweet: {str(e)}",
                "tweet_id": None
            }