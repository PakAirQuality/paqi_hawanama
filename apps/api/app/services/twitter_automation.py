"""
Twitter automation service for posting Lahore air quality data.
"""

import hashlib
import logging
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional
from zoneinfo import ZoneInfo
from pathlib import Path

import tweepy
from app.core.config import settings

logger = logging.getLogger(__name__)

# Constants
TZ = ZoneInfo("Asia/Karachi")  # Lahore local time
STATE_DIR = Path("/tmp/lahore_twitter_state")
STATE_DIR.mkdir(parents=True, exist_ok=True)


class TwitterAutomationService:
    """Service for automating Twitter posts about Lahore air quality with AQI-based rules."""
    
    def __init__(self):
        self.client = None
        self.monthly_post_limit = 480
        self.state_file = STATE_DIR / f"state_{datetime.now(TZ).strftime('%Y-%m')}.json"
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
            wait_on_rate_limit=False,  # Never block the service on rate limits
        )
    
    def _load_state(self) -> Dict:
        """Load posting state from JSON file."""
        try:
            if self.state_file.exists():
                return json.loads(self.state_file.read_text())
        except Exception as e:
            logger.warning(f"State load failed: {e}")
        return {
            "last_posted_category": None,
            "last_posted_at": None,
            "last_hazardous_post_hour": None,
            "last_tweet_hash": None
        }

    def _save_state(self, state: Dict) -> None:
        """Save posting state to JSON file."""
        try:
            self.state_file.write_text(json.dumps(state, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"State save failed: {e}")
    
    def _hour_key_from_ts(self, ts: Optional[str]) -> str:
        """Create robust hour key from timestamp, handling naive vs tz-aware strings."""
        if not ts:
            return datetime.now(TZ).strftime("%Y-%m-%dT%H:00%z")
        try:
            dt = datetime.fromisoformat(ts)  # may be naive or aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc).astimezone(TZ)
            else:
                dt = dt.astimezone(TZ)
            return dt.strftime("%Y-%m-%dT%H:00%z")
        except Exception:
            return datetime.now(TZ).strftime("%Y-%m-%dT%H:00%z")
    
    async def fetch_lahore_history(self, hours: int = 2) -> List[Dict]:
        """Fetch Lahore city average history data from the API endpoint."""
        try:
            logger.info(f"Fetching Lahore city average history for last {hours} hours...")
            
            # Import the function we need
            from app.routers.history import city_average_history
            from app.core.database import get_database
            
            # Get database session and call the function directly
            async for db in get_database():
                result = await city_average_history(city="Lahore", hours=hours, db=db)
                break
            
            logger.info(f"Successfully fetched {len(result)} history entries for Lahore")
            return result
                
        except Exception as e:
            logger.error(f"Failed to fetch Lahore history data: {e}")
            raise RuntimeError(f"History data fetch failed: {e}")
    
    def get_aqi_category(self, aqi: int) -> str:
        """Get AQI category from AQI value."""
        if aqi is None:
            return "Unknown"
        elif aqi <= 50:
            return "Good"
        elif aqi <= 100:
            return "Moderate"
        elif aqi <= 150:
            return "Unhealthy for Sensitive Groups"
        elif aqi <= 200:
            return "Unhealthy"
        elif aqi <= 300:
            return "Very Unhealthy"
        elif aqi <= 500:
            return "Hazardous"
        else:
            return "Beyond Index"
    
    def should_post_tweet(self, current_data: Dict, *, last_posted_category: Optional[str], last_hazardous_post_hour: Optional[str]) -> Dict:
        """
        Determine if a tweet should be posted based on PKT rules.
        
        Rules:
        1. Post when AQI category changes vs. LAST POSTED category (not previous hour)
        2. Post once per hour if category is Hazardous (≥301) or Beyond Index (>500)
        3. Skip otherwise
        
        Returns: {'should_post': bool, 'reason': str, 'hazard_hour_gate': Optional[str]}
        """
        current_aqi = current_data.get("avg_aqi")
        if current_aqi is None:
            return {"should_post": False, "reason": "No current AQI data available", "hazard_hour_gate": None}

        current_category = self.get_aqi_category(current_aqi)

        # Compute the "hour key" for one-per-hour gating using robust timestamp handling
        hour_key = self._hour_key_from_ts(current_data.get("timestamp_pk"))

        # Rule 2: Hazardous or Beyond Index → at most once per hour
        if current_aqi >= 301:
            if last_hazardous_post_hour == hour_key:
                return {"should_post": False, "reason": f"Hazardous+ but already posted this hour ({hour_key})", "hazard_hour_gate": hour_key}
            return {"should_post": True, "reason": f"AQI {current_aqi} is {current_category} (≥301) - hourly post", "hazard_hour_gate": hour_key}

        # Rule 1: Post when category changes vs LAST POSTED CATEGORY (not previous hour)
        if last_posted_category is None:
            return {"should_post": True, "reason": "First run - no last posted category", "hazard_hour_gate": None}
        if current_category != last_posted_category:
            return {"should_post": True, "reason": f"Category changed {last_posted_category} → {current_category}", "hazard_hour_gate": None}

        return {"should_post": False, "reason": f"No category change ({current_category})", "hazard_hour_gate": None}
    
    async def get_monthly_post_count(self) -> int:
        """
        Get current month's post count from simple storage.
        For now, we'll use a simple file-based counter.
        """
        try:
            import os
            from pathlib import Path
            
            # Create a simple counter file based on current month
            current_month = datetime.now(TZ).strftime("%Y-%m")
            counter_file = Path(f"/tmp/twitter_posts_{current_month}.txt")
            
            if counter_file.exists():
                with open(counter_file, 'r') as f:
                    return int(f.read().strip())
            else:
                return 0
        except Exception as e:
            logger.warning(f"Failed to read monthly post count: {e}")
            return 0
    
    async def increment_monthly_post_count(self) -> int:
        """Increment and return the monthly post count."""
        try:
            import os
            from pathlib import Path
            
            current_month = datetime.now(TZ).strftime("%Y-%m")
            counter_file = Path(f"/tmp/twitter_posts_{current_month}.txt")
            
            # Get current count
            current_count = await self.get_monthly_post_count()
            new_count = current_count + 1
            
            # Write new count
            with open(counter_file, 'w') as f:
                f.write(str(new_count))
            
            logger.info(f"Monthly post count incremented to {new_count}")
            return new_count
        except Exception as e:
            logger.error(f"Failed to increment monthly post count: {e}")
            return 0
        
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
        # Get current time but round down to the nearest hour (:00)
        current_time = datetime.now(TZ)
        timestamp = current_time.strftime("%d-%m-%Y %H:00")
        pm25 = city_data["avg_pm25_concentration"]
        aqi = city_data["aqi"]
        health_message = city_data["health_message"] or ""

        tweet = f"{timestamp}; PM2.5 conc. {pm25:.1f} μg/m³; {aqi} Air Quality Index (AQI); {health_message}"

        if len(tweet) > 280:
            # fall back: drop emojis/punctuation but keep hashtags/words, then truncate if still long
            import re
            health_slim = re.sub(r"[^\w\s#]", "", health_message)
            tweet = f"{timestamp}; PM2.5 conc. {pm25:.1f} μg/m³; {aqi} Air Quality Index (AQI); {health_slim}"
            if len(tweet) > 280:
                keep = 280 - len(f"{timestamp}; PM2.5 conc. {pm25:.1f} μg/m³; {aqi} Air Quality Index (AQI); ")
                tweet = f"{timestamp}; PM2.5 conc. {pm25:.1f} μg/m³; {aqi} Air Quality Index (AQI); {health_slim[:max(0, keep-3)]}..."
        return tweet
    
    def post_tweet(self, text: str, max_retries: int = 3) -> str:
        """Post tweet and return tweet ID with non-blocking rate limit handling."""
        if not self.client:
            raise RuntimeError("Twitter client not initialized")
        
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Attempting to post tweet (attempt {attempt}/{max_retries})")
                response = self.client.create_tweet(text=text)
                tweet_id = str(response.data["id"])
                logger.info(f"Tweet posted successfully. ID: {tweet_id}")
                return tweet_id
            except tweepy.TooManyRequests as e:
                # Rate limit hit - return immediately without blocking
                logger.warning(f"Twitter rate limit exceeded: {e}")
                raise RuntimeError(f"Twitter rate limit exceeded - service will not be blocked: {e}")
            except tweepy.Forbidden as e:
                # Twitter API access forbidden
                logger.error(f"Twitter API access forbidden: {e}")
                raise RuntimeError(f"Twitter API access forbidden: {e}")
            except tweepy.TweepyException as e:
                last_error = e
                logger.warning(f"Tweet attempt {attempt} failed: {e}")
                # Check if this is a rate limit error that wasn't caught above
                if "rate limit" in str(e).lower():
                    logger.warning("Rate limit detected in TweepyException - returning immediately")
                    raise RuntimeError(f"Twitter rate limit exceeded: {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(2 * attempt)  # Exponential backoff for non-rate-limit errors
                    continue
            except Exception as e:
                last_error = e
                logger.warning(f"Unexpected error on attempt {attempt}: {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(1)  # Brief pause for unexpected errors
                    continue
        
        logger.error(f"Failed to post tweet after {max_retries} attempts: {last_error}")
        raise RuntimeError(f"Tweet failed after {max_retries} attempts: {last_error}")
    
    def content_hash(self, text: str) -> str:
        """Generate hash of tweet content for deduplication."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    
    async def post_lahore_pm25_update(self, dry_run: bool = False) -> Dict:
        """
        Main method with PKT rules implemented correctly.
        
        Rules:
        1. Post when AQI category changes vs. LAST POSTED category (not previous hour)
        2. Post once per hour if category is Hazardous (≥301) or Beyond Index (>500)
        3. Skip otherwise
        4. Safety rail: stop at 480 posts/month
        
        Args:
            dry_run: If True, don't actually post to Twitter
            
        Returns:
            Dict with status and details
        """
        try:
            logger.info("Starting Lahore PKT rules Twitter automation")
            
            # Check monthly post limit first
            monthly_count = await self.get_monthly_post_count()
            if monthly_count >= self.monthly_post_limit:
                return {
                    "status": "skipped",
                    "message": f"Monthly post limit reached ({monthly_count}/{self.monthly_post_limit})",
                    "tweet_id": None,
                    "monthly_count": monthly_count
                }
            
            # Load state
            state = self._load_state()
            last_posted_category = state.get("last_posted_category")
            last_hazardous_post_hour = state.get("last_hazardous_post_hour")
            
            # Fetch last 2 hours to get "current" hour data
            history_data = await self.fetch_lahore_history(hours=2)
            if not history_data:
                return {"status": "skipped", "message": "No history data available", "tweet_id": None}

            current_data = history_data[-1]
            # Validate data before proceeding
            if current_data.get("avg_pm25") is None or current_data.get("avg_aqi") is None:
                return {"status": "skipped", "message": "Current hour has no valid PM2.5/AQI", "tweet_id": None}

            decision = self.should_post_tweet(
                current_data,
                last_posted_category=last_posted_category,
                last_hazardous_post_hour=last_hazardous_post_hour
            )
            if not decision["should_post"]:
                return {
                    "status": "skipped",
                    "message": decision["reason"],
                    "tweet_id": None,
                    "current_aqi": current_data.get("avg_aqi"),
                    "monthly_count": monthly_count
                }

            # Build normalized data for tweet text
            normalized_data = {
                "city": "Lahore",
                "avg_pm25_concentration": current_data.get("avg_pm25"),
                "aqi": current_data.get("avg_aqi"),
                "health_message": current_data.get("health_message", ""),
                "total_stations": current_data.get("stations_used", 0),
            }
            pm25_val = normalized_data["avg_pm25_concentration"]
            aqi_val = normalized_data["aqi"]
            if pm25_val is None or aqi_val is None:
                return {"status": "skipped", "message": "Invalid PM2.5/AQI", "tweet_id": None}

            # Additional NaN guard for PM2.5
            if pm25_val != pm25_val:  # Check for NaN
                return {"status": "skipped", "message": "PM2.5 is NaN", "tweet_id": None}

            tweet_text = self.build_tweet_text(normalized_data)
            tweet_hash = self.content_hash(tweet_text)

            # Content dedupe to avoid repeats outside Hazardous+
            state_last_hash = state.get("last_tweet_hash")
            if tweet_hash == state_last_hash and current_data.get("avg_aqi", 0) < 301:
                return {"status": "skipped", "message": "Duplicate tweet content (non-Hazardous+)", "tweet_id": None}

            logger.info(f"Generated tweet ({len(tweet_text)} chars): {tweet_text}")
            logger.info(f"Posting reason: {decision['reason']}")

            if dry_run:
                return {
                    "status": "dry_run",
                    "message": "Dry run - tweet not posted",
                    "tweet_text": tweet_text,
                    "tweet_hash": tweet_hash,
                    "posting_reason": decision["reason"],
                    "city_data": normalized_data,
                    "monthly_count": monthly_count
                }

            tweet_id = self.post_tweet(tweet_text)
            new_monthly_count = await self.increment_monthly_post_count()

            # Update state AFTER successful post
            state["last_posted_category"] = self.get_aqi_category(aqi_val)
            state["last_posted_at"] = datetime.now(TZ).isoformat()
            state["last_tweet_hash"] = tweet_hash
            if decision["hazard_hour_gate"]:
                state["last_hazardous_post_hour"] = decision["hazard_hour_gate"]
            else:
                # Reset hazardous hour gate when not hazardous
                state["last_hazardous_post_hour"] = None
            self._save_state(state)

            return {
                "status": "success",
                "message": "Tweet posted successfully",
                "tweet_id": tweet_id,
                "tweet_text": tweet_text,
                "tweet_hash": tweet_hash,
                "posting_reason": decision["reason"],
                "city_data": normalized_data,
                "monthly_count": new_monthly_count
            }
            
        except Exception as e:
            logger.error(f"Twitter automation failed: {e}")
            return {
                "status": "error",
                "message": f"Failed to post tweet: {str(e)}",
                "tweet_id": None
            }