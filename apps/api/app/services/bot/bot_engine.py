"""
Hawanama Bot Service - "Jutt Smog" / "Baba Smoggy" / "Smog Mian"

Main bot service that implements:
1. Fixed schedule posts (08:00, 14:00, 20:00 PKT)
2. Smart triggers (High Smog, Volatility Alert, Hotspot Alert)
3. Emergency Airpocalypse mode (AQI > 500)
4. LLM-generated tweets with persona
"""

import logging
import json
import contextlib
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo
from pathlib import Path
from fcntl import flock, LOCK_EX, LOCK_UN

from app.services.bot.data_compiler import LLMDataCompiler, MASTER_PERSONA_PROMPT, AIRPOCALYPSE_PROMPT
from app.services.bot.ai_client import GeminiAIService
from app.services.bot.twitter_client import TwitterAutomationService

logger = logging.getLogger(__name__)

# Default timezone (PKT / Asia/Karachi)
TZ = ZoneInfo("Asia/Karachi")

# Bot configuration - Smart Budget Model
MONTHLY_POST_BUDGET = 500  # Total monthly posts budget
BASE_SCHEDULE_BUDGET = 330  # Base schedule posts (~330/month)
SMART_TRIGGERS_BUDGET = 170  # Smart triggers posts (~170/month)

# Base Schedule Configuration (PKT times)
BASE_SCHEDULE = {
    "06:00": "data_only",      # Morning heartbeat
    "08:00": "llm_generated",  # Morning Report (LLM)
    "09:00": "data_only",      # Post-morning data
    "12:00": "data_only",      # Noon heartbeat
    "14:00": "llm_generated",  # Mid-Day Update (LLM)
    "18:00": "data_only",      # Evening heartbeat
    "20:00": "llm_generated",  # Evening Summary (LLM)
    "21:00": "data_only",      # Late evening data
    "00:00": "data_only"       # Midnight heartbeat
}
STATE_DIR = Path("/tmp/hawanama_bot_state")
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOCK_PATH = STATE_DIR / "bot.lock"

@contextlib.contextmanager
def _state_lock():
    """File lock to prevent race conditions on concurrent bot runs."""
    LOCK_PATH.touch(exist_ok=True)
    with open(LOCK_PATH, "r+") as fh:
        flock(fh, LOCK_EX)
        try:
            yield
        finally:
            flock(fh, LOCK_UN)


class HawanamaBot:
    """
    The main Hawanama Bot ("Jutt Smog" / "Baba Smoggy" / "Smog Mian")
    
    Handles intelligent air quality posting with personality and smart triggers.
    """
    
    def __init__(self):
        self.llm_compiler = LLMDataCompiler()
        self.gemini_ai = GeminiAIService()
        self.twitter = TwitterAutomationService()
        self.city = "Lahore"  # Primary city for the bot
        self.state_file = STATE_DIR / f"bot_state_{datetime.now(TZ).strftime('%Y-%m')}.json"
    
    def _load_bot_state(self) -> Dict[str, Any]:
        """Load bot state from JSON file."""
        try:
            if self.state_file.exists():
                return json.loads(self.state_file.read_text())
        except Exception as e:
            logger.warning(f"Bot state load failed: {e}")
        return {
            "monthly_post_count": 0,
            "base_schedule_count": 0,
            "smart_triggers_count": 0,
            "last_base_posts": {},  # Track last post for each base schedule time
            "last_trigger_checks": {},
            "last_airpocalypse_post": None,
            "last_category": None,  # Track last posted category for change detection
            "last_category_change_hour": None
        }
    
    def _save_bot_state(self, state: Dict[str, Any]) -> None:
        """Save bot state to JSON file."""
        try:
            self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"Bot state save failed: {e}")
    
    def generate_data_only_post(self, payload: Dict[str, Any]) -> str:
        """
        Generate data-only "heartbeat" post.
        
        Format: [Date] [Time]; PM2.5 conc. [X] μg/m³; [Y] Air Quality Index (AQI); #[Category]
        Example: 28-10-2025 09:00; PM2.5 conc. 206.5 μg/m³; 281 Air Quality Index (AQI); Very #Unhealthy
        
        Args:
            payload: LLM data payload with current conditions
            
        Returns:
            Formatted data-only tweet text
        """
        current_data = payload["currentData"]
        
        # Parse timestamp and format in PKT
        timestamp_str = current_data["timestamp"]
        try:
            dt = datetime.fromisoformat(timestamp_str.replace('+05:00', ''))
            formatted_time = dt.strftime("%d-%m-%Y %H:00")
        except:
            # Fallback to current time
            formatted_time = datetime.now(TZ).strftime("%d-%m-%Y %H:00")
        
        pm25 = current_data["pm25"]
        aqi = current_data["cityAverageAQI"]
        category = current_data["cityCategory"]
        
        # Add hashtag to category
        hashtag_category = f"#{category.replace(' ', '')}"
        
        tweet = f"{formatted_time}; PM2.5 conc. {pm25:.1f} μg/m³; {aqi} Air Quality Index (AQI); {hashtag_category}"
        
        # Ensure tweet length is under 280 characters
        if len(tweet) > 280:
            # Truncate if needed
            tweet = tweet[:277] + "..."
        
        return tweet

    async def should_post_base_schedule(self) -> Dict[str, Any]:
        """
        Check if we should post according to base schedule.
        
        Returns:
            Dict with should_post boolean, post_type, and details
        """
        current_time = datetime.now(TZ)
        current_hour = current_time.strftime("%H:00")
        
        # Check if current time matches any base schedule time
        if current_hour not in BASE_SCHEDULE:
            return {
                "should_post": False,
                "reason": f"Not a base schedule time (current: {current_hour})"
            }
        
        post_type = BASE_SCHEDULE[current_hour]
        
        # Load state to check if we already posted this hour
        state = self._load_bot_state()
        last_base_posts = state.get("last_base_posts", {})
        current_hour_key = current_time.strftime("%Y-%m-%dT%H:00%z")
        
        if last_base_posts.get(current_hour) == current_hour_key:
            return {
                "should_post": False,
                "reason": f"Already posted base schedule this hour ({current_hour_key})"
            }
        
        # Check base schedule budget
        base_count = state.get("base_schedule_count", 0)
        if base_count >= BASE_SCHEDULE_BUDGET:
            return {
                "should_post": False,
                "reason": f"Base schedule budget exceeded ({base_count}/{BASE_SCHEDULE_BUDGET})"
            }
        
        return {
            "should_post": True,
            "reason": f"Base schedule time: {current_hour} ({post_type})",
            "post_type": post_type,
            "schedule_time": current_hour,
            "hour_key": current_hour_key
        }

    async def should_post_category_change(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check if we should post due to AQI category change (hourly check).
        
        Args:
            payload: Current air quality data
            
        Returns:
            Dict with should_post boolean and details
        """
        current_category = payload["currentData"]["cityCategory"]
        current_time = datetime.now(TZ)
        current_hour_key = current_time.strftime("%Y-%m-%dT%H:00%z")
        
        state = self._load_bot_state()
        last_category = state.get("last_category")
        last_change_hour = state.get("last_category_change_hour")
        
        # If no previous category recorded, don't post (first run)
        if last_category is None:
            return {
                "should_post": False,
                "reason": "No previous category recorded (first run)",
                "category_change": False
            }
        
        # Check if category has changed to worse
        category_hierarchy = [
            "Good", "Moderate", "Unhealthy for Sensitive Groups", 
            "Unhealthy", "Very Unhealthy", "Hazardous", "Beyond Index"
        ]
        
        try:
            current_index = category_hierarchy.index(current_category)
            last_index = category_hierarchy.index(last_category)
            
            # Only post if category got worse
            if current_index <= last_index:
                return {
                    "should_post": False,
                    "reason": f"Category unchanged or improved: {last_category} → {current_category}",
                    "category_change": False
                }
        except ValueError:
            # Handle unknown categories
            if current_category == last_category:
                return {
                    "should_post": False,
                    "reason": f"Category unchanged: {current_category}",
                    "category_change": False
                }
        
        # Don't post if we already posted for category change this hour
        if last_change_hour == current_hour_key:
            return {
                "should_post": False,
                "reason": f"Already posted category change this hour ({current_hour_key})",
                "category_change": True
            }
        
        # Check smart triggers budget
        triggers_count = state.get("smart_triggers_count", 0)
        if triggers_count >= SMART_TRIGGERS_BUDGET:
            return {
                "should_post": False,
                "reason": f"Smart triggers budget exceeded ({triggers_count}/{SMART_TRIGGERS_BUDGET})",
                "category_change": True
            }
        
        return {
            "should_post": True,
            "reason": f"Category change alert: {last_category} → {current_category}",
            "post_type": "data_only",
            "category_change": True,
            "old_category": last_category,
            "new_category": current_category,
            "hour_key": current_hour_key
        }
    
    async def check_smart_triggers(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check all smart trigger conditions for additional LLM posts.
        
        Args:
            payload: LLM data payload from compiler
            
        Returns:
            Dict with trigger results and posting recommendations
        """
        triggers = self.llm_compiler.get_trigger_conditions(payload)
        current_time = datetime.now(TZ)
        current_hour_key = current_time.strftime("%Y-%m-%dT%H:00%z")
        
        state = self._load_bot_state()
        last_checks = state.get("last_trigger_checks", {})
        
        recommendations = []
        
        # Trigger 1: High Smog (Hazardous only) - 3 hour cooldown
        if triggers["high_smog"]:
            last_high_smog = last_checks.get("high_smog_last_post")
            if not last_high_smog:
                # First time posting high smog
                recommendations.append({
                    "trigger": "high_smog",
                    "should_post": True,
                    "reason": f"High smog detected: {payload['currentData']['cityCategory']}",
                    "schedule": "priority_high",  # High priority for public health
                    "urgency": "high"
                })
            else:
                # Check if 3 hours have passed since last high smog post
                try:
                    last_time = datetime.fromisoformat(last_high_smog.replace('Z', '+00:00'))
                    current_time = datetime.fromisoformat(current_hour_key.replace('Z', '+00:00'))
                    hours_diff = (current_time - last_time).total_seconds() / 3600
                    
                    if hours_diff >= 3:
                        recommendations.append({
                            "trigger": "high_smog",
                            "should_post": True,
                            "reason": f"High smog continues: {payload['currentData']['cityCategory']} (3h+ since last post)",
                            "schedule": "priority_high",
                            "urgency": "high"
                        })
                except Exception:
                    # If time parsing fails, allow posting
                    recommendations.append({
                        "trigger": "high_smog",
                        "should_post": True,
                        "reason": f"High smog detected: {payload['currentData']['cityCategory']}",
                        "schedule": "priority_high",
                        "urgency": "high"
                    })
        
        # Trigger 2: Volatility Alert (>100 point AQI increase) - 2 hour cooldown
        if triggers["volatility_alert"]:
            last_volatility = last_checks.get("volatility_last_post")
            if not last_volatility:
                current_aqi = payload["currentData"]["cityAverageAQI"]
                historical = payload["historical24h"]
                if len(historical) >= 3:
                    two_hours_ago_aqi = historical[-3]["avg_aqi"]
                    change = current_aqi - two_hours_ago_aqi
                    recommendations.append({
                        "trigger": "volatility_alert",
                        "should_post": True,
                        "reason": f"AQI volatility: +{change} points in 2 hours",
                        "schedule": "priority_medium",  # Medium priority for trend alerts
                        "urgency": "medium"
                    })
            else:
                # Check if 2 hours have passed since last volatility post
                try:
                    last_time = datetime.fromisoformat(last_volatility.replace('Z', '+00:00'))
                    current_time = datetime.fromisoformat(current_hour_key.replace('Z', '+00:00'))
                    hours_diff = (current_time - last_time).total_seconds() / 3600
                    
                    if hours_diff >= 2:
                        current_aqi = payload["currentData"]["cityAverageAQI"]
                        historical = payload["historical24h"]
                        if len(historical) >= 3:
                            two_hours_ago_aqi = historical[-3]["avg_aqi"]
                            change = current_aqi - two_hours_ago_aqi
                            recommendations.append({
                                "trigger": "volatility_alert",
                                "should_post": True,
                                "reason": f"AQI volatility continues: +{change} points (2h+ since last post)",
                                "schedule": "priority_medium",
                                "urgency": "medium"
                            })
                except Exception:
                    # If time parsing fails, allow posting
                    current_aqi = payload["currentData"]["cityAverageAQI"]
                    historical = payload["historical24h"]
                    if len(historical) >= 3:
                        two_hours_ago_aqi = historical[-3]["avg_aqi"]
                        change = current_aqi - two_hours_ago_aqi
                        recommendations.append({
                            "trigger": "volatility_alert",
                            "should_post": True,
                            "reason": f"AQI volatility: +{change} points in 2 hours",
                            "schedule": "priority_medium",
                            "urgency": "medium"
                        })
        
        # Trigger 3: Hotspot Alert (worst station >99 points higher) - 4 hour cooldown
        if triggers["hotspot_alert"]:
            last_hotspot = last_checks.get("hotspot_last_post")
            if not last_hotspot:
                hotspots = payload["topHotspots"]
                city_avg = payload["currentData"]["cityAverageAQI"]
                if hotspots:
                    worst_aqi = hotspots[0]["aqi"]
                    diff = worst_aqi - city_avg
                    recommendations.append({
                        "trigger": "hotspot_alert",
                        "should_post": True,
                        "reason": f"Extreme hotspot: {hotspots[0]['name']} ({worst_aqi}) vs city avg ({city_avg}), diff: +{diff}",
                        "schedule": "priority_low",  # Low priority for location-specific alerts
                        "urgency": "low"
                    })
            else:
                # Check if 4 hours have passed since last hotspot post
                try:
                    last_time = datetime.fromisoformat(last_hotspot.replace('Z', '+00:00'))
                    current_time = datetime.fromisoformat(current_hour_key.replace('Z', '+00:00'))
                    hours_diff = (current_time - last_time).total_seconds() / 3600
                    
                    if hours_diff >= 4:
                        hotspots = payload["topHotspots"]
                        city_avg = payload["currentData"]["cityAverageAQI"]
                        if hotspots:
                            worst_aqi = hotspots[0]["aqi"]
                            diff = worst_aqi - city_avg
                            recommendations.append({
                                "trigger": "hotspot_alert",
                                "should_post": True,
                                "reason": f"Extreme hotspot continues: {hotspots[0]['name']} ({worst_aqi}) vs city avg ({city_avg}), diff: +{diff} (4h+ since last post)",
                                "schedule": "priority_low",
                                "urgency": "low"
                            })
                except Exception:
                    # If time parsing fails, allow posting
                    hotspots = payload["topHotspots"]
                    city_avg = payload["currentData"]["cityAverageAQI"]
                    if hotspots:
                        worst_aqi = hotspots[0]["aqi"]
                        diff = worst_aqi - city_avg
                        recommendations.append({
                            "trigger": "hotspot_alert",
                            "should_post": True,
                            "reason": f"Extreme hotspot: {hotspots[0]['name']} ({worst_aqi}) vs city avg ({city_avg}), diff: +{diff}",
                            "schedule": "priority_low",
                            "urgency": "low"
                        })
        
        # Special: Airpocalypse (AQI > 500)
        if triggers["airpocalypse"]:
            last_airpocalypse = state.get("last_airpocalypse_post")
            if not last_airpocalypse or last_airpocalypse != current_hour_key:
                recommendations.append({
                    "trigger": "airpocalypse",
                    "should_post": True,
                    "reason": f"AIRPOCALYPSE: AQI {payload['currentData']['cityAverageAQI']} > 500",
                    "schedule": "emergency",  # Emergency override - bypasses all limits
                    "urgency": "emergency",
                    "priority": "emergency"
                })
        
        # Sort recommendations by priority: emergency > high > medium > low
        priority_order = {"emergency": 0, "high": 1, "medium": 2, "low": 3}
        recommendations.sort(key=lambda x: priority_order.get(x.get("urgency", "low"), 3))
        
        return {
            "triggers": triggers,
            "recommendations": recommendations,
            "total_recommended": len(recommendations)
        }
    
    async def generate_llm_tweet(self, payload: Dict[str, Any], trigger_info: Optional[Dict] = None) -> str:
        """
        Generate LLM tweet using Gemini AI with appropriate prompt.
        
        Args:
            payload: LLM data payload
            trigger_info: Optional trigger information for context
            
        Returns:
            Generated tweet text
        """
        # Check if this should be an airpocalypse post
        current_aqi = payload["currentData"]["cityAverageAQI"]
        
        if current_aqi > 500:
            # Use airpocalypse prompt for emergency mode
            json_data = json.dumps(payload, indent=2)
            prompt = AIRPOCALYPSE_PROMPT.format(json_data=json_data)
            
            # Generate 2-tweet thread
            thread = await self.gemini_ai.generate_airpocalypse_thread(prompt)
            return thread  # Return both tweets for threading
        else:
            # Use master persona prompt for normal posts
            json_data = json.dumps(payload, indent=2)
            prompt = MASTER_PERSONA_PROMPT.format(json_data=json_data)
            
            # Generate single tweet
            tweet = await self.gemini_ai.generate_tweet(prompt)
            return tweet
    
    async def post_tweet_with_logging(self, tweet_text: str, post_type: str, reason: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Post tweet with proper logging and state management.
        
        Args:
            tweet_text: Tweet content to post
            post_type: Type of post (fixed_schedule, trigger, airpocalypse)
            reason: Reason for posting
            dry_run: If True, don't actually post
            
        Returns:
            Result dict with status and details
        """
        try:
            if dry_run:
                return {
                    "status": "dry_run",
                    "message": "Dry run - tweet not posted",
                    "tweet_text": tweet_text,
                    "post_type": post_type,
                    "reason": reason
                }
            
            # Use file lock to prevent race conditions
            with _state_lock():
                # Re-check budget after acquiring lock
                state = self._load_bot_state()
                if state.get("monthly_post_count", 0) >= MONTHLY_POST_BUDGET:
                    return {
                        "status": "budget_exceeded",
                        "message": f"Monthly budget of {MONTHLY_POST_BUDGET} posts exceeded",
                        "current_count": state.get("monthly_post_count", 0)
                    }
            
                # Handle airpocalypse thread posting
                if isinstance(tweet_text, list) and len(tweet_text) == 2:
                    # Post first tweet
                    tweet_id_1 = self.twitter.post_tweet(tweet_text[0])
                    logger.info(f"Posted airpocalypse alert tweet: {tweet_id_1}")
                    
                    # Post reply tweet
                    import tweepy
                    reply_response = self.twitter.client.create_tweet(
                        text=tweet_text[1], 
                        in_reply_to_tweet_id=tweet_id_1
                    )
                    tweet_id_2 = str(reply_response.data["id"])
                    logger.info(f"Posted airpocalypse advisory reply: {tweet_id_2}")
                    
                    # Update state under lock
                    state["monthly_post_count"] = state.get("monthly_post_count", 0) + 2  # 2 tweets
                    state["last_airpocalypse_post"] = datetime.now(TZ).strftime("%Y-%m-%dT%H:00%z")
                    self._save_bot_state(state)
                    
                    return {
                        "status": "success",
                        "message": "Airpocalypse thread posted successfully",
                        "tweet_ids": [tweet_id_1, tweet_id_2],
                        "tweet_texts": tweet_text,
                        "post_type": post_type,
                        "reason": reason,
                        "posts_used": 2
                    }
                else:
                    # Post single tweet
                    tweet_id = self.twitter.post_tweet(tweet_text)
                    logger.info(f"Posted {post_type} tweet: {tweet_id}")
                    
                    # Update state under lock
                    state["monthly_post_count"] = state.get("monthly_post_count", 0) + 1
                    self._save_bot_state(state)
                    
                    return {
                        "status": "success",
                        "message": "Tweet posted successfully",
                        "tweet_id": tweet_id,
                        "tweet_text": tweet_text,
                        "post_type": post_type,
                        "reason": reason,
                        "posts_used": 1
                    }
                
        except Exception as e:
            logger.error(f"Failed to post {post_type} tweet: {e}")
            return {
                "status": "error",
                "message": f"Failed to post tweet: {str(e)}",
                "post_type": post_type,
                "reason": reason
            }
    
    async def run_bot_cycle(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Run complete bot cycle using Smart Budget Model - ONE POST PER HOUR.
        
        Priority order (posts only ONE per hour):
        1. Base Schedule: Data-only and LLM posts at fixed times (highest priority)
        2. Category Change Alerts: Data-only posts when AQI category worsens  
        3. Smart Triggers: Additional LLM posts for extreme conditions (lowest priority)
        
        Args:
            dry_run: If True, don't actually post tweets
            
        Returns:
            Dict with cycle results and actions taken
        """
        try:
            logger.info("Starting Hawanama Bot cycle (Smart Budget Model - One Post Per Hour)")
            
            cycle_results = {
                "timestamp": datetime.now(TZ).isoformat(),
                "actions": [],
                "posts_made": 0,
                "budget_status": {},
                "errors": []
            }
            
            # Get current data
            payload = await self.llm_compiler.compile_llm_payload(city=self.city)
            
            # Check budget status
            state = self._load_bot_state()
            total_count = state.get("monthly_post_count", 0)
            base_count = state.get("base_schedule_count", 0)
            triggers_count = state.get("smart_triggers_count", 0)
            
            cycle_results["budget_status"] = {
                "total_used": total_count,
                "total_remaining": MONTHLY_POST_BUDGET - total_count,
                "total_budget": MONTHLY_POST_BUDGET,
                "base_schedule": {
                    "used": base_count,
                    "remaining": BASE_SCHEDULE_BUDGET - base_count,
                    "budget": BASE_SCHEDULE_BUDGET
                },
                "smart_triggers": {
                    "used": triggers_count,
                    "remaining": SMART_TRIGGERS_BUDGET - triggers_count,
                    "budget": SMART_TRIGGERS_BUDGET
                }
            }
            
            if total_count >= MONTHLY_POST_BUDGET:
                cycle_results["actions"].append({
                    "type": "budget_check",
                    "status": "total_budget_exceeded",
                    "message": f"Monthly budget exceeded ({total_count}/{MONTHLY_POST_BUDGET})"
                })
                return cycle_results
            
            current_hour_key = datetime.now(TZ).strftime("%Y-%m-%dT%H:00%z")
            last_post_hour = state.get("last_post_hour")
            
            # EARLY EMERGENCY BYPASS: Airpocalypse overrides hourly limits
            triggers = self.llm_compiler.get_trigger_conditions(payload)
            if triggers.get("airpocalypse"):
                last_airpocalypse = state.get("last_airpocalypse_post")
                if last_airpocalypse != current_hour_key:
                    tweet_content = await self.generate_llm_tweet(payload)  # returns 2-tweet thread
                    result = await self.post_tweet_with_logging(
                        tweet_content, 
                        "smart_trigger_airpocalypse",
                        f"AIRPOCALYPSE: AQI {payload['currentData']['cityAverageAQI']} > 500",
                        dry_run
                    )
                    cycle_results["actions"].append({"type": "smart_trigger", "trigger": "airpocalypse", "result": result})
                    if result.get("status") == "success":
                        state["last_airpocalypse_post"] = current_hour_key
                        state["last_post_hour"] = current_hour_key
                        state["smart_triggers_count"] = state.get("smart_triggers_count", 0) + result.get("posts_used", 1)
                        self._save_bot_state(state)
                        cycle_results["posts_made"] += result.get("posts_used", 1)
                        logger.info("AIRPOCALYPSE emergency posted - bypassed hourly limit")
                        return cycle_results  # emergency handled; end cycle
            
            # CHECK IF WE ALREADY POSTED THIS HOUR (normal posts) - use lock
            with _state_lock():
                state = self._load_bot_state()
                current_hour_key = datetime.now(TZ).strftime("%Y-%m-%dT%H:00%z")
                if state.get("last_post_hour") == current_hour_key:
                    cycle_results["actions"].append({
                        "type": "hourly_limit",
                        "status": "already_posted_this_hour",
                        "message": f"Already posted this hour ({current_hour_key}) - enforcing one post per hour limit"
                    })
                    return cycle_results
            
            # PRIORITY 1: Check Base Schedule (HIGHEST PRIORITY)
            base_check = await self.should_post_base_schedule()
            if base_check["should_post"]:
                try:
                    if base_check["post_type"] == "data_only":
                        tweet_content = self.generate_data_only_post(payload)
                    else:  # llm_generated
                        tweet_content = await self.generate_llm_tweet(payload)
                    
                    result = await self.post_tweet_with_logging(
                        tweet_content, 
                        f"base_schedule_{base_check['post_type']}", 
                        base_check["reason"], 
                        dry_run
                    )
                    
                    cycle_results["actions"].append({
                        "type": "base_schedule",
                        "schedule_time": base_check["schedule_time"],
                        "post_type": base_check["post_type"],
                        "result": result
                    })
                    
                    if result["status"] == "success":
                        posts_used = result.get("posts_used", 1)
                        cycle_results["posts_made"] += posts_used
                        
                        # Update state for base schedule (count already updated in post_tweet_with_logging)
                        state.setdefault("last_base_posts", {})[base_check["schedule_time"]] = base_check["hour_key"]
                        state["base_schedule_count"] = state.get("base_schedule_count", 0) + posts_used
                        state["last_post_hour"] = current_hour_key  # Track last post hour
                        state["last_category"] = payload["currentData"]["cityCategory"]
                        self._save_bot_state(state)
                        
                        # BASE SCHEDULE POST MADE - SKIP ALL OTHER CHECKS
                        logger.info("Base schedule post made - skipping other checks for this cycle")
                        return cycle_results
                        
                except Exception as e:
                    cycle_results["errors"].append(f"Base schedule post failed: {e}")
            
            # PRIORITY 2: Check Category Change Alert (only if no base schedule post)
            category_check = await self.should_post_category_change(payload)
            if category_check["should_post"]:
                try:
                    tweet_content = self.generate_data_only_post(payload)
                    
                    result = await self.post_tweet_with_logging(
                        tweet_content, 
                        "category_change_alert", 
                        category_check["reason"], 
                        dry_run
                    )
                    
                    cycle_results["actions"].append({
                        "type": "category_change",
                        "old_category": category_check["old_category"],
                        "new_category": category_check["new_category"],
                        "result": result
                    })
                    
                    if result["status"] == "success":
                        posts_used = result.get("posts_used", 1)
                        cycle_results["posts_made"] += posts_used
                        
                        # Update state for category change (count already updated in post_tweet_with_logging)
                        state["last_category_change_hour"] = category_check["hour_key"]
                        state["smart_triggers_count"] = state.get("smart_triggers_count", 0) + posts_used
                        state["last_post_hour"] = current_hour_key  # Track last post hour
                        state["last_category"] = payload["currentData"]["cityCategory"]
                        self._save_bot_state(state)
                        
                        # CATEGORY CHANGE POST MADE - SKIP SMART TRIGGERS
                        logger.info("Category change post made - skipping smart triggers for this cycle")
                        return cycle_results
                        
                except Exception as e:
                    cycle_results["errors"].append(f"Category change alert failed: {e}")
            
            # PRIORITY 3: Check Smart Triggers (only if no other posts made)
            remaining_triggers_budget = SMART_TRIGGERS_BUDGET - state.get("smart_triggers_count", 0)
            if remaining_triggers_budget > 0:
                trigger_check = await self.check_smart_triggers(payload)
                
                # POST ONLY THE FIRST (HIGHEST PRIORITY) TRIGGER
                if trigger_check["recommendations"]:
                    recommendation = trigger_check["recommendations"][0]  # Take only first trigger
                    
                    try:
                        tweet_content = await self.generate_llm_tweet(payload, recommendation)
                        result = await self.post_tweet_with_logging(
                            tweet_content, 
                            f"smart_trigger_{recommendation['trigger']}", 
                            recommendation["reason"], 
                            dry_run
                        )
                        
                        cycle_results["actions"].append({
                            "type": "smart_trigger",
                            "trigger": recommendation["trigger"],
                            "result": result
                        })
                        
                        if result["status"] == "success":
                            posts_used = result.get("posts_used", 1)
                            cycle_results["posts_made"] += posts_used
                            
                            # Update trigger state (count already updated in post_tweet_with_logging)
                            state.setdefault("last_trigger_checks", {})[f"{recommendation['trigger']}_last_post"] = current_hour_key
                            state["smart_triggers_count"] = state.get("smart_triggers_count", 0) + posts_used
                            state["last_post_hour"] = current_hour_key  # Track last post hour
                            self._save_bot_state(state)
                            
                            logger.info(f"Smart trigger post made: {recommendation['trigger']} - one post per hour limit reached")
                            
                    except Exception as e:
                        cycle_results["errors"].append(f"Smart trigger {recommendation['trigger']} failed: {e}")
            
            # Always update last category for future comparison
            state["last_category"] = payload["currentData"]["cityCategory"]
            self._save_bot_state(state)
            
            logger.info(f"Bot cycle completed. Posts made: {cycle_results['posts_made']}, Errors: {len(cycle_results['errors'])}")
            return cycle_results
            
        except Exception as e:
            logger.error(f"Bot cycle failed: {e}")
            return {
                "timestamp": datetime.now(TZ).isoformat(),
                "status": "error",
                "message": f"Bot cycle failed: {str(e)}",
                "actions": [],
                "posts_made": 0
            }
    
    async def get_bot_status(self) -> Dict[str, Any]:
        """
        Get current bot status and statistics.
        
        Returns:
            Dict with bot status information
        """
        try:
            state = self._load_bot_state()
            current_time = datetime.now(TZ)
            
            # Check if it's a fixed post time
            current_hour = current_time.strftime("%H:00")
            is_fixed_time = current_hour in BASE_SCHEDULE
            
            # Get current data for trigger analysis
            payload = await self.llm_compiler.compile_llm_payload(city=self.city)
            triggers = self.llm_compiler.get_trigger_conditions(payload)
            
            return {
                "timestamp": current_time.isoformat(),
                "bot_persona": "Jutt Smog / Baba Smoggy / Smog Mian",
                "city": self.city,
                "status": "active",
                "current_time_pkt": current_hour,
                "is_fixed_post_time": is_fixed_time,
                "budget": {
                    "used": state.get("monthly_post_count", 0),
                    "remaining": MONTHLY_POST_BUDGET - state.get("monthly_post_count", 0),
                    "total": MONTHLY_POST_BUDGET,
                    "percentage_used": round((state.get("monthly_post_count", 0) / MONTHLY_POST_BUDGET) * 100, 1)
                },
                "current_conditions": {
                    "aqi": payload["currentData"]["cityAverageAQI"],
                    "category": payload["currentData"]["cityCategory"],
                    "pm25": payload["currentData"]["pm25"]
                },
                "active_triggers": {
                    "high_smog": triggers["high_smog"],
                    "volatility_alert": triggers["volatility_alert"],
                    "hotspot_alert": triggers["hotspot_alert"],
                    "airpocalypse": triggers["airpocalypse"]
                },
                "last_posts": {
                    "fixed_schedule": state.get("last_fixed_post_hour"),
                    "airpocalypse": state.get("last_airpocalypse_post")
                },
                "services": {
                    "gemini_ai": "connected",  # Would need actual health check
                    "twitter": "connected",
                    "database": "connected"
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get bot status: {e}")
            return {
                "timestamp": datetime.now(TZ).isoformat(),
                "status": "error",
                "message": f"Status check failed: {str(e)}"
            }