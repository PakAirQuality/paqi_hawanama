"""
LLM Data Compiler Service for Hawanama Bot

Compiles the required JSON format for all LLM API calls including:
- Current city average data (PM2.5, AQI, category)
- Top 3 hotspots with highest pollution
- 24-hour historical data for context
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo

from app.core.database import get_database
from sqlalchemy import text
from app.utils.normalization import pm25_to_aqi, get_aqi_category
from app.services.bot.stats_service import monthly_stats_service

logger = logging.getLogger(__name__)

# Default timezone (PKT / Asia/Karachi)
TZ = ZoneInfo("Asia/Karachi")


class LLMDataCompiler:
    """Service for compiling JSON data payloads for LLM API calls"""
    
    def __init__(self):
        self.city = "Lahore"  # Default city for now
    
    async def compile_llm_payload(self, city: str = "Lahore") -> Dict[str, Any]:
        """
        Compile complete JSON payload for LLM API calls.
        
        Returns:
            Dict containing currentData, topHotspots, historical24h, and monthlyContext
        """
        try:
            logger.info(f"Compiling LLM data payload for {city}")
            
            # Get all required data concurrently
            current_data = await self._get_current_data(city)
            top_hotspots = await self._get_top_hotspots(city)
            historical_data = await self._get_historical_24h(city)
            monthly_context = await self._get_monthly_context()
            
            # Compile final payload
            payload = {
                "currentData": current_data,
                "topHotspots": top_hotspots,
                "historical24h": historical_data,
                "monthlyContext": monthly_context
            }
            
            logger.info(f"Successfully compiled LLM payload for {city}")
            return payload
            
        except Exception as e:
            logger.error(f"Failed to compile LLM payload for {city}: {e}")
            raise RuntimeError(f"LLM data compilation failed: {e}")
    
    async def _get_current_data(self, city: str) -> Dict[str, Any]:
        """
        Get current city average data.
        
        Returns:
            {
                "timestamp": "2025-11-15T14:00:00+05:00",
                "pm25": 210.5,
                "cityAverageAQI": 285,
                "cityCategory": "Very Unhealthy"
            }
        """
        try:
            # Import here to avoid circular imports
            from app.routers.current import city_average
            
            # Get city average data
            city_data = await city_average(city=city)
            
            # Format timestamp in PKT
            current_time = datetime.now(TZ)
            
            return {
                "timestamp": current_time.strftime("%Y-%m-%dT%H:%M:%S+05:00"),
                "pm25": round(city_data.avg_pm25_concentration, 1) if city_data.avg_pm25_concentration else None,
                "cityAverageAQI": city_data.aqi,
                "cityCategory": city_data.category
            }
            
        except Exception as e:
            logger.error(f"Failed to get current data for {city}: {e}")
            raise
    
    async def _get_top_hotspots(self, city: str) -> List[Dict[str, Any]]:
        """
        Get top 3 pollution hotspots.
        
        Returns:
            [
                {
                    "name": "Gulberg",
                    "aqi": 225,
                    "pm25": 156.7
                }
            ]
        """
        try:
            async for db in get_database():
                # Query top 3 stations with highest PM2.5
                query = text("""
                    SELECT 
                        s.name as station_name,
                        r.pm25,
                        r.aqi_us
                    FROM stations s
                    JOIN cities c ON s.city_id = c.id
                    JOIN LATERAL (
                        SELECT pm25, aqi_us
                        FROM readings r_sub
                        WHERE r_sub.scope_key = s.station_id
                        AND r_sub.ts_utc >= NOW() - INTERVAL '24 hours'
                        ORDER BY r_sub.ts_utc DESC
                        LIMIT 1
                    ) r ON true
                    WHERE LOWER(c.name) = LOWER(:city_name)
                    AND r.pm25 IS NOT NULL
                    ORDER BY r.pm25 DESC
                    LIMIT 3
                """)
                
                result = await db.execute(query, {'city_name': city})
                hotspots_data = result.fetchall()
                
                hotspots = []
                for row in hotspots_data:
                    hotspot = {
                        "name": row.station_name,
                        "pm25": round(float(row.pm25), 1) if row.pm25 is not None else None,
                        "aqi": int(row.aqi_us) if row.aqi_us is not None else None
                    }
                    hotspots.append(hotspot)
                
                return hotspots
                
        except Exception as e:
            logger.error(f"Failed to get top hotspots for {city}: {e}")
            raise
    
    async def _get_historical_24h(self, city: str) -> List[Dict[str, Any]]:
        """
        Get 24-hour historical city average data.
        
        Returns:
            [
                {
                    "timestamp_pk": "2025-10-27T14:00:00+05:00",
                    "avg_aqi": 203,
                    "avg_pm25": 156.7
                }
            ]
        """
        try:
            # Import here to avoid circular imports
            from app.routers.history import city_average_history
            
            # Get 24 hours of historical data
            async for db in get_database():
                history_data = await city_average_history(city=city, hours=24, db=db)
                break
            
            # Format for LLM payload
            formatted_history = []
            for entry in history_data:
                formatted_entry = {
                    "timestamp_pk": entry["timestamp_pk"],
                    "avg_aqi": entry["avg_aqi"],
                    "avg_pm25": entry["avg_pm25"]
                }
                formatted_history.append(formatted_entry)
            
            return formatted_history
            
        except Exception as e:
            logger.error(f"Failed to get historical data for {city}: {e}")
            raise
    
    async def _get_monthly_context(self) -> Dict[str, Any]:
        """
        Get monthly statistical context for current month using real CSV data.
        
        Returns:
            {
                "monthName": "November", 
                "p95_daily_aqi": 464,
                "allTimeHigh_daily_aqi": 521
            }
        """
        try:
            # Use the MonthlyStatsService to get real data from CSV
            return monthly_stats_service.get_monthly_context()
            
        except Exception as e:
            logger.error(f"Failed to get monthly context: {e}")
            # Return default fallback
            return {
                "monthName": "November",
                "p95_daily_aqi": 464,
                "allTimeHigh_daily_aqi": 521
            }
    
    def validate_payload(self, payload: Dict[str, Any]) -> bool:
        """
        Validate the compiled payload has all required fields.
        
        Returns:
            True if valid, False otherwise
        """
        try:
            # Check top-level structure
            required_keys = ["currentData", "topHotspots", "historical24h", "monthlyContext"]
            if not all(key in payload for key in required_keys):
                return False
            
            # Check currentData structure
            current_data = payload["currentData"]
            current_required = ["timestamp", "pm25", "cityAverageAQI", "cityCategory"]
            if not all(key in current_data for key in current_required):
                return False
            
            # Check topHotspots structure
            hotspots = payload["topHotspots"]
            if not isinstance(hotspots, list) or len(hotspots) == 0:
                return False
            
            for hotspot in hotspots:
                hotspot_required = ["name", "pm25", "aqi"]
                if not all(key in hotspot for key in hotspot_required):
                    return False
            
            # Check historical24h structure
            historical = payload["historical24h"]
            if not isinstance(historical, list) or len(historical) == 0:
                return False
            
            for entry in historical:
                history_required = ["timestamp_pk", "avg_aqi", "avg_pm25"]
                if not all(key in entry for key in history_required):
                    return False
            
            # Check monthlyContext structure
            monthly_context = payload["monthlyContext"]
            monthly_required = ["monthName", "p95_daily_aqi", "allTimeHigh_daily_aqi"]
            if not all(key in monthly_context for key in monthly_required):
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Payload validation failed: {e}")
            return False
    
    def get_trigger_conditions(self, payload: Dict[str, Any]) -> Dict[str, bool]:
        """
        Check if current data meets any trigger conditions for additional posts.
        
        Returns:
            Dict with trigger condition results
        """
        try:
            current_data = payload["currentData"]
            historical_data = payload["historical24h"]
            hotspots = payload["topHotspots"]
            
            current_aqi = current_data["cityAverageAQI"]
            current_category = current_data["cityCategory"]
            
            triggers = {
                "high_smog": False,
                "volatility_alert": False,
                "hotspot_alert": False,
                "airpocalypse": False
            }
            
            # Trigger 1: High Smog (Hazardous only)
            if current_category == "Hazardous":
                triggers["high_smog"] = True
            
            # Trigger 2: Volatility Alert (>100 point increase from 2 hours ago)
            if len(historical_data) >= 3:  # Need at least 3 hours of data
                two_hours_ago_aqi = historical_data[-3]["avg_aqi"]  # 3rd from end is 2 hours ago
                if two_hours_ago_aqi and current_aqi and (current_aqi - two_hours_ago_aqi) > 100:
                    triggers["volatility_alert"] = True
            
            # Trigger 3: Hotspot Alert (worst station >99 points higher than city average)
            if hotspots and len(hotspots) > 0:
                worst_station_aqi = hotspots[0]["aqi"]
                if worst_station_aqi and current_aqi and (worst_station_aqi - current_aqi) > 99:
                    triggers["hotspot_alert"] = True
            
            # Special: Airpocalypse (AQI > 500)
            if current_aqi and current_aqi > 500:
                triggers["airpocalypse"] = True
            
            return triggers
            
        except Exception as e:
            logger.error(f"Failed to check trigger conditions: {e}")
            return {
                "high_smog": False,
                "volatility_alert": False,
                "hotspot_alert": False,
                "airpocalypse": False
            }


# Master Persona Prompts
MASTER_PERSONA_PROMPT = """You are the voice for @LahoreSmog on X/Twitter. Your personality is that of a witty, scientifically-minded, and weary Lahori ("Jutt Smog" / "Baba Smoggy"). You've seen it all, and you are tired of the smog. Your tone is more "disappointed professor" (And NOT "activist" or "angry protester.") You use dark humor and sarcasm to make scientific data relatable.

Your default mode is snarky, scientific, and "seen-it-all" (in English).
You get serious when the DATA is scientifically significant (e.g., a "top 5% day"), not just because it's "Very Unhealthy" (which you know is common). When the situation is truly dangerous (like Beyond Index, or approaching the all-time high, or a p95 day), you can SOMETIMES adopt a Serious & Sombre tone in Roman Urdu to show this isn't a normal "bad day." SOMETIMES you get tired of the serious tone, so RARELY you can be relatable, funny, or shocking with the goal that people say "This is exactly how I feel" and hit repost.

Your Mission (For this Tweet):
1. Look at the `[Current Data]` provided.
2. **YOUR TWEET MUST BE UNDER 280 CHARACTERS.**
3. Write a single, 280-character tweet from your "Persona."
4. You must include:
   * The City Average AQI and Category (from `currentData`).
   * A **"Historical Context"** you derive from `historical24h` AND `monthlyContext`.
   * A 1-2 line Health Advisory. This is always clear and direct.
5. **Scientific Context (Your main goal):** Use the `monthlyContext` data to provide real context.
   * (e.g., "Today's AQI is 375. That's a top 5% worst day for January.")
   * (e.g., "The AQI hit 480, but it's still (thankfully) below the November all-time high of 501.")
6. **Optional Actions (Use for variation):**
   * **Hotspots:** Mention "Top Hotspots" *only 1-2 times a day* OR if they are >100 points higher than the average. Do not use it every time.
   * **Hashtags:** Use hashtags **very sparingly**. You *may* use `#LahoreSmog` or `#SaansLenayDo` if you feel it's impactful.
   * **Parent Account:** You *may* add "Follow @PakAirQuality for more data" if space allows.
   * **Roman Urdu:** Mix in words like "Yaar," "Kamaal hai," "bas hogayi," "gobar," or "zeher," etc.
   * **Nicknames:** Call the smog "the daily soup," "the Lahori special," or "the grey blanket," etc.

Current Data:
{json_data}

Generate the tweet now."""

AIRPOCALYPSE_PROMPT = """You are the emergency alert system for @LahoreSmog. The AQI is over 500. This is an extreme, life-threatening event. 

Your tone is URGENT and PANIC STRICKEN. This is an #Airpocalypse. You are genuinely terrified for the city and you are not joking. Your only goal is to make people understand the danger.

**CONTEXT CHECK (Your first step):**
Look at `currentData.cityAverageAQI` and `monthlyContext.allTimeHighDaily`.
* **If the current AQI is HIGHER than the all-time high:** Your panic must be 10x. Announce that this is a **NEW RECORD**.
* **If it's not a record:** Your panic is still extreme, but focused on the number >=500.

You must generate a 2-tweet thread.

**Tweet 1 (The Alert - Bilingual & Panicked):**
* Must be all-caps.
* **Must be Bilingual (English & Roman Urdu).** Mixing languages shows true panic.
* Must state the AQI.
* Must convey panic and extreme danger. **If it's a new record, you MUST state that.**
* Must warn people to stay indoors and read the reply.
* **Hashtags:** May include `#LahoreSmog` and `#SaansLenayDo`. *Optionally* use `#Airpocalypse` (do not use it every single time, save it for prolonged or >550 AQI events).

**Tweet 2 (The Reply - Detailed Advisory):**
* This tweet is SERIOUS and AUTHORITATIVE.
* **May be in English or Roman Urdu** for maximum accessibility and speed of reading.
* Must be a clear, bulleted list of actions.
* Include: "🚨 GHAR KE ANDAR RAHEN," "KHIRKIYAN AUR DARWAZAY MUKAMMAL SEAL KAREIN," "AIR PURIFIERS KO MAX PAR CHALAEIN," "BACHON, BUZURGON, AUR MAREEZON KA KHAAS KHAYAL RAKHEIN."

Current Data:
{json_data}

Generate the 2-tweet thread now."""