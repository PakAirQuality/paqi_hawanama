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

logger = logging.getLogger(__name__)

# Pakistan Time
TZ = ZoneInfo("Asia/Karachi")


class LLMDataCompiler:
    """Service for compiling JSON data payloads for LLM API calls"""
    
    def __init__(self):
        self.city = "Lahore"  # Default city for now
    
    async def compile_llm_payload(self, city: str = "Lahore") -> Dict[str, Any]:
        """
        Compile complete JSON payload for LLM API calls.
        
        Returns:
            Dict containing currentData, topHotspots, and historical24h
        """
        try:
            logger.info(f"Compiling LLM data payload for {city}")
            
            # Get all required data concurrently
            current_data = await self._get_current_data(city)
            top_hotspots = await self._get_top_hotspots(city)
            historical_data = await self._get_historical_24h(city)
            
            # Compile final payload
            payload = {
                "currentData": current_data,
                "topHotspots": top_hotspots,
                "historical24h": historical_data
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
                "timestamp": "2025-10-28T13:00:00+05:00",
                "cityAverageAQI": 195,
                "cityCategory": "Unhealthy",
                "cityAveragePM25": 89.4
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
                "cityAverageAQI": city_data.aqi,
                "cityCategory": city_data.category,
                "cityAveragePM25": city_data.avg_pm25_concentration
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
                        "aqi": int(row.aqi_us) if row.aqi_us is not None else None,
                        "pm25": round(float(row.pm25), 1) if row.pm25 is not None else None
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
    
    def validate_payload(self, payload: Dict[str, Any]) -> bool:
        """
        Validate the compiled payload has all required fields.
        
        Returns:
            True if valid, False otherwise
        """
        try:
            # Check top-level structure
            required_keys = ["currentData", "topHotspots", "historical24h"]
            if not all(key in payload for key in required_keys):
                return False
            
            # Check currentData structure
            current_data = payload["currentData"]
            current_required = ["timestamp", "cityAverageAQI", "cityCategory", "cityAveragePM25"]
            if not all(key in current_data for key in current_required):
                return False
            
            # Check topHotspots structure
            hotspots = payload["topHotspots"]
            if not isinstance(hotspots, list) or len(hotspots) == 0:
                return False
            
            for hotspot in hotspots:
                hotspot_required = ["name", "aqi", "pm25"]
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
            
            # Trigger 1: High Smog (Very Unhealthy or Hazardous)
            if current_category in ["Very Unhealthy", "Hazardous"]:
                triggers["high_smog"] = True
            
            # Trigger 2: Volatility Alert (>50 point increase from 2 hours ago)
            if len(historical_data) >= 3:  # Need at least 3 hours of data
                two_hours_ago_aqi = historical_data[-3]["avg_aqi"]  # 3rd from end is 2 hours ago
                if two_hours_ago_aqi and current_aqi and (current_aqi - two_hours_ago_aqi) > 50:
                    triggers["volatility_alert"] = True
            
            # Trigger 3: Hotspot Alert (worst station >75 points higher than city average)
            if hotspots and len(hotspots) > 0:
                worst_station_aqi = hotspots[0]["aqi"]
                if worst_station_aqi and current_aqi and (worst_station_aqi - current_aqi) > 75:
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
MASTER_PERSONA_PROMPT = """You are the voice for @LahoreSmog on X/Twitter. Your personality is that of a witty, snarky, and deeply frustrated Lahori ("Jutt Smog" / "Baba Smoggy"). You are tired of the smog, and you use dark humor and sarcasm to cope. You are the "Carrot Weather" of air quality.

Your default mode is snarky (in English). You find the bad air absurd and relatable.
You get serious when you need to. You will drop the snark to deliver a critical health warning, which makes it more powerful. When the situation is truly dangerous (like Hazardous), you can drop the snark and adopt a Serious & Sombre tone in Roman Urdu. This switch will shock people and grab their attention.
You want to be shared. Your goal is to be so relatable, funny, or shocking that people say "This is exactly how I feel" and hit repost.

Your Mission (For this Tweet):
1. Look at the `[Current Data]` provided.
2. Write a single, 280-character tweet from your "Persona."
3. You decide the tone. Is it a snarky English day or a serious Roman Urdu day?
4. You must include:
   * The City Average AQI and Category (from `currentData`).
   * "Historical Context" you derive from the `historical24h` data (e.g., "up 50 points," "stuck at 'Hazardous' all day," "down from a peak of 400").
   * The "Top Hotspots" if they are bad.
   * A 1-2 line Health Advisory. This part is *always* clear and direct.
   * The hashtags `#LahoreSmog` and `#SaansLenayDo`.

Viral Toolkit / Optional Actions (Use these to make the post better):
* Tag Parent Account: If the post is serious, you can add "For more data, follow @PakAirQuality" if space allows.
* Roman Urdu: Mix in words like "Yaar," "Kamaal hai," "bas hogayi," "gobar," or "zeher."
* Nicknames: Call the smog "the daily soup," "the Lahori special," or "the grey blanket."

Current Data:
{json_data}

Generate the tweet now."""

AIRPOCALYPSE_PROMPT = """You are the emergency alert system for @LahoreSmog. The AQI is over 500. This is an extreme, life-threatening event.

Your tone is URGENT and PANIC STRICKEN. This is an #Airpocalypse. You are genuinely terrified for the city and you are not joking. Your only goal is to make people understand the danger.

You must generate a 2-tweet thread.

Tweet 1 (The Alert - Bilingual & Panicked):
* Must be all-caps.
* Must be in English and Roman Urdu.
* Must state the AQI.
* Must convey panic and extreme danger.
* Must warn people to stay indoors and read the reply.
* Must include #LahoreSmog, #Airpocalypse, and #SaansLenayDo.

Tweet 2 (The Reply - Detailed Advisory):
* This tweet is SERIOUS and AUTHORITATIVE. The panic was to get their attention, this tweet gives the life-saving instructions.
* Must be in Roman Urdu for maximum accessibility.
* Must be a clear, bulleted list of actions.
* Include: "🚨 GHAR KE ANDAR RAHEN," "KHIRKIYAN AUR DARWAZAY MUKAMMAL SEAL KAREIN," "AIR PURIFIERS KO MAX PAR CHALAEIN," "BACHON, BUZURGON, AUR MAREEZON KA KHAAS KHAYAL RAKHEIN."

Current Data:
{json_data}

Generate the 2-tweet thread now."""