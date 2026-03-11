"""
Hawanama Bot API Router - endpoints for bot data compilation, testing, and automation
"""

import logging
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from fastapi.responses import JSONResponse
from typing import Dict, Any

from app.core.security import verify_tasks_token
from app.services.bot.data_compiler import LLMDataCompiler, MASTER_PERSONA_PROMPT, AIRPOCALYPSE_PROMPT
from app.services.bot.bot_engine import HawanamaBot
from app.services.bot.ai_client import GeminiAIService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/bot/llm-data/{city}",
    summary="Get compiled LLM data payload for bot",
    description="Compile the complete JSON payload required for all LLM API calls including current data, hotspots, and historical context"
)
async def get_llm_data(
    city: str = Path(
        ...,
        description="City name",
        example="Lahore",
        enum=[
            "Abbottabad", "Bahawalpur", "Bhopalwala", "Chak Jhumra", "Daska Kalan", 
            "Dera Ismail Khan", "Eminabad", "Faisalabad", "Gujranwala", "Haripur", 
            "Hundal", "Hyderabad", "Islamabad", "Jhang", "Jhelum", "Kahna Nau", 
            "Karachi", "Kasur", "Khairpur Mir's", "Kharan", "Khurrianwala", 
            "Kot Malik Barkhurdar", "Kotli Loharan", "Kotri", "Ladhewala Waraich", 
            "Lahore", "Lodhran", "Malam Jabba", "Malir Cantonment", "Mandi Bahauddin", 
            "Mirpur Khas", "Multan", "Murree", "Pasrur", "Pattoki", "Peshawar", 
            "Pindi Bhattian", "Qadirpur Ran", "Quetta", "Rahim Yar Khan", "Raiwind", 
            "Rawalpindi", "Rojhan", "Sambrial", "Sheikhupura", "Sialkot", "Skardu", "Sukkur"
        ]
    )
):
    """
    Get the complete LLM data payload for bot tweet generation.
    
    - **city**: City name (required)
    
    Returns the standardized JSON format required for all LLM API calls:
    - **currentData**: Current city average PM2.5, AQI, and category
    - **topHotspots**: Top 3 highest pollution stations with names and AQI
    - **historical24h**: 24 hours of city average data for context
    
    **Use Cases:**
    - Hawanama Bot tweet generation
    - LLM API calls for social media automation
    - Air quality context compilation
    - Trigger condition checking
    
    **Error responses:**
    - `400`: Invalid parameters
    - `404`: City not found or no data available
    - `500`: Internal server error
    """
    try:
        # Initialize compiler and get data
        compiler = LLMDataCompiler()
        payload = await compiler.compile_llm_payload(city=city)
        
        # Validate payload
        if not compiler.validate_payload(payload):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Invalid payload structure generated"
            )
        
        # Add trigger conditions analysis
        triggers = compiler.get_trigger_conditions(payload)
        
        # Add metadata
        response_data = {
            "city": city,
            "data": payload,
            "triggers": triggers,
            "validation": {
                "is_valid": True,
                "generated_at": payload["currentData"]["timestamp"]
            }
        }
        
        return JSONResponse(content=response_data)
        
    except Exception as e:
        logger.error(f"Failed to compile LLM data for {city}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compile LLM data: {str(e)}"
        )


@router.get(
    "/bot/prompt/{city}",
    summary="Get formatted LLM prompt with data",
    description="Get the complete LLM prompt with JSON data inserted, ready for API call"
)
async def get_llm_prompt(
    city: str = Path(
        ...,
        description="City name",
        example="Lahore"
    ),
    prompt_type: str = Query(
        "master",
        description="Prompt type to use",
        enum=["master", "airpocalypse"]
    )
):
    """
    Get the formatted LLM prompt with current data inserted.
    
    - **city**: City name (required)
    - **prompt_type**: Type of prompt - "master" for normal posts, "airpocalypse" for AQI > 500
    
    Returns the complete prompt string ready to send to LLM API, with JSON data embedded.
    
    **Use Cases:**
    - Testing LLM prompts with real data
    - Bot development and debugging
    - Prompt validation and optimization
    """
    try:
        # Get compiled data
        compiler = LLMDataCompiler()
        payload = await compiler.compile_llm_payload(city=city)
        
        # Format as JSON string for prompt
        json_data = json.dumps(payload, indent=2)
        
        # Select appropriate prompt
        if prompt_type == "airpocalypse":
            prompt_template = AIRPOCALYPSE_PROMPT
        else:
            prompt_template = MASTER_PERSONA_PROMPT
        
        # Insert data into prompt
        formatted_prompt = prompt_template.format(json_data=json_data)
        
        # Check trigger conditions
        triggers = compiler.get_trigger_conditions(payload)
        
        return {
            "city": city,
            "prompt_type": prompt_type,
            "prompt": formatted_prompt,
            "data_summary": {
                "current_aqi": payload["currentData"]["cityAverageAQI"],
                "current_category": payload["currentData"]["cityCategory"],
                "hotspots_count": len(payload["topHotspots"]),
                "historical_hours": len(payload["historical24h"])
            },
            "triggers": triggers
        }
        
    except Exception as e:
        logger.error(f"Failed to generate prompt for {city}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate prompt: {str(e)}"
        )


@router.get(
    "/bot/triggers/{city}",
    summary="Check trigger conditions for additional posts",
    description="Check if current conditions meet criteria for additional LLM-generated posts"
)
async def check_triggers(
    city: str = Path(
        ...,
        description="City name",
        example="Lahore"
    )
):
    """
    Check if current air quality conditions trigger additional bot posts.
    
    - **city**: City name (required)
    
    Returns analysis of trigger conditions:
    - **high_smog**: Very Unhealthy or Hazardous category
    - **volatility_alert**: >50 point AQI increase in 2 hours
    - **hotspot_alert**: Worst station >75 points higher than city average
    - **airpocalypse**: AQI > 500 (emergency mode)
    
    **Use Cases:**
    - Bot scheduling logic
    - Automated alert generation
    - Smart posting budget management
    """
    try:
        # Get compiled data and check triggers
        compiler = LLMDataCompiler()
        payload = await compiler.compile_llm_payload(city=city)
        triggers = compiler.get_trigger_conditions(payload)
        
        # Add detailed analysis
        current_data = payload["currentData"]
        hotspots = payload["topHotspots"]
        historical = payload["historical24h"]
        
        analysis = {
            "city": city,
            "timestamp": current_data["timestamp"],
            "current_conditions": {
                "aqi": current_data["cityAverageAQI"],
                "category": current_data["cityCategory"],
                "pm25": current_data["cityAveragePM25"]
            },
            "triggers": triggers,
            "details": {
                "worst_hotspot_aqi": hotspots[0]["aqi"] if hotspots else None,
                "aqi_vs_hotspot_diff": (hotspots[0]["aqi"] - current_data["cityAverageAQI"]) if hotspots and current_data["cityAverageAQI"] else None,
                "historical_hours_available": len(historical),
                "two_hour_change": None
            }
        }
        
        # Calculate 2-hour change if possible
        if len(historical) >= 3:
            current_aqi = current_data["cityAverageAQI"]
            two_hours_ago = historical[-3]["avg_aqi"]
            if current_aqi and two_hours_ago:
                analysis["details"]["two_hour_change"] = current_aqi - two_hours_ago
        
        return analysis
        
    except Exception as e:
        logger.error(f"Failed to check triggers for {city}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check triggers: {str(e)}"
        )


@router.post(
    "/bot/execute",
    summary="Execute Hawanama Bot with LLM and Twitter integration",
    description="Main endpoint for Terraform to call - handles complete LLM->Twitter pipeline"
)
async def execute_hawanama_bot(
    dry_run: bool = Query(
        False,
        description="If true, don't actually post tweets - just simulate"
    ),
    force_post: bool = Query(
        False,
        description="If true, bypass schedule checks and force a post"
    ),
    _auth=Depends(verify_tasks_token),
):
    """
    Main execution endpoint for Hawanama Bot.
    
    This is the primary endpoint that Terraform/cron should call hourly.
    It implements the Smart Budget Model with:
    
    **Base Schedule (~330 posts/month):**
    - 06:00, 09:00, 12:00, 18:00, 21:00, 00:00: Data-only posts
    - 08:00, 14:00, 20:00: LLM-generated posts with persona
    
    **Smart Triggers (~170 posts/month):**
    - Category change alerts (data-only)
    - High smog alerts (LLM)
    - Volatility alerts (LLM) 
    - Hotspot alerts (LLM)
    - Airpocalypse mode (LLM 2-tweet thread)
    
    **Process:**
    1. Compile current air quality data
    2. Check if conditions warrant posting
    3. Generate appropriate content (data-only or LLM)
    4. Post to Twitter with budget tracking
    
    **Parameters:**
    - **dry_run**: Simulate without posting
    - **force_post**: Bypass schedule (for testing)
    
    **Returns:**
    - Complete execution results
    - Budget status and usage
    - Content generated and posted
    - Any errors encountered
    """
    try:
        bot = HawanamaBot()
        
        if force_post:
            # Force post mode - generate and post LLM content regardless of schedule
            compiler = LLMDataCompiler()
            payload = await compiler.compile_llm_payload(city="Lahore")
            
            # Generate LLM content
            tweet_content = await bot.generate_llm_tweet(payload)
            
            # Post with force reasoning
            result = await bot.post_tweet_with_logging(
                tweet_content, 
                "forced_post", 
                "Manual force post via API",
                dry_run
            )
            
            return JSONResponse(content={
                "success": True,
                "execution_type": "forced_post",
                "result": result,
                "content_generated": tweet_content,
                "data_used": payload["currentData"],
                "triggers": compiler.get_trigger_conditions(payload)
            })
        else:
            # Normal cycle execution
            results = await bot.run_bot_cycle(dry_run=dry_run)
            
            return JSONResponse(content={
                "success": True,
                "execution_type": "normal_cycle",
                "cycle_results": results
            })
        
    except Exception as e:
        logger.error(f"Bot execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bot execution failed: {str(e)}"
        )


@router.post(
    "/bot/run-cycle",
    summary="Run complete Hawanama Bot cycle",
    description="Execute full bot cycle: check schedule, triggers, and post tweets if needed"
)
async def run_bot_cycle(
    dry_run: bool = Query(
        False,
        description="If true, don't actually post tweets - just simulate"
    ),
    _auth=Depends(verify_tasks_token),
):
    """
    Run the complete Hawanama Bot cycle.
    
    This endpoint executes the full bot logic:
    1. Check if it's a fixed schedule time (08:00, 14:00, 20:00 PKT)
    2. Check smart triggers (High Smog, Volatility, Hotspot alerts)
    3. Generate and post LLM tweets using persona prompts
    4. Handle emergency Airpocalypse mode (AQI > 500)
    
    - **dry_run**: If true, simulate posting without actually tweeting
    
    **Use Cases:**
    - Scheduled bot execution (cron jobs)
    - Manual bot triggering for testing
    - Emergency posting during high pollution events
    
    **Returns:**
    - Cycle results with actions taken
    - Posts made and budget usage
    - Any errors encountered
    """
    try:
        bot = HawanamaBot()
        results = await bot.run_bot_cycle(dry_run=dry_run)
        
        return JSONResponse(content={
            "success": True,
            "cycle_results": results
        })
        
    except Exception as e:
        logger.error(f"Bot cycle execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bot cycle failed: {str(e)}"
        )


@router.get(
    "/bot/status",
    summary="Get Hawanama Bot status",
    description="Get current bot status, budget usage, and trigger conditions"
)
async def get_bot_status():
    """
    Get comprehensive bot status information.
    
    Returns current status including:
    - Bot persona and configuration
    - Monthly posting budget usage
    - Current air quality conditions
    - Active trigger conditions
    - Service health status
    
    **Use Cases:**
    - Monitoring bot health
    - Budget tracking
    - Debugging bot behavior
    - Status dashboards
    """
    try:
        bot = HawanamaBot()
        status_info = await bot.get_bot_status()
        
        return JSONResponse(content=status_info)
        
    except Exception as e:
        logger.error(f"Failed to get bot status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Status check failed: {str(e)}"
        )


@router.post(
    "/bot/generate-tweet/{city}",
    summary="Generate LLM tweet for city",
    description="Generate a single tweet using Gemini AI with persona prompts"
)
async def generate_llm_tweet(
    city: str = Path(
        ...,
        description="City name",
        example="Lahore"
    ),
    prompt_type: str = Query(
        "master",
        description="Prompt type to use",
        enum=["master", "airpocalypse"]
    ),
    _auth=Depends(verify_tasks_token),
):
    """
    Generate a tweet using LLM with current air quality data.
    
    - **city**: City name for data compilation
    - **prompt_type**: "master" for normal persona, "airpocalypse" for emergency mode
    
    Uses the complete persona prompts to generate contextual, witty, or serious tweets
    based on current air quality conditions.
    
    **Returns:**
    - Generated tweet text(s)
    - Data used for generation
    - Prompt type and reasoning
    """
    try:
        # Get data and generate tweet
        compiler = LLMDataCompiler()
        gemini = GeminiAIService()
        
        payload = await compiler.compile_llm_payload(city=city)
        
        # Select prompt and generate
        if prompt_type == "airpocalypse":
            json_data = json.dumps(payload, indent=2)
            prompt = AIRPOCALYPSE_PROMPT.format(json_data=json_data)
            generated_content = await gemini.generate_airpocalypse_thread(prompt)
        else:
            json_data = json.dumps(payload, indent=2)
            prompt = MASTER_PERSONA_PROMPT.format(json_data=json_data)
            generated_content = await gemini.generate_tweet(prompt)
        
        return {
            "city": city,
            "prompt_type": prompt_type,
            "generated_content": generated_content,
            "is_thread": isinstance(generated_content, list),
            "data_used": {
                "current_aqi": payload["currentData"]["cityAverageAQI"],
                "current_category": payload["currentData"]["cityCategory"],
                "hotspots_count": len(payload["topHotspots"])
            },
            "triggers": compiler.get_trigger_conditions(payload)
        }
        
    except Exception as e:
        logger.error(f"Failed to generate LLM tweet for {city}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tweet generation failed: {str(e)}"
        )


@router.get(
    "/bot/test-gemini",
    summary="Test Gemini AI connection",
    description="Test connection to Google Gemini AI service"
)
async def test_gemini_connection():
    """
    Test the Gemini AI service connection.
    
    Validates that the Gemini API is properly configured and accessible.
    
    **Returns:**
    - Connection status
    - Test response from Gemini
    - Configuration validation
    """
    try:
        gemini = GeminiAIService()
        test_result = await gemini.test_connection()
        
        return JSONResponse(content=test_result)
        
    except Exception as e:
        logger.error(f"Gemini connection test failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "message": f"Connection test failed: {str(e)}",
                "connected": False
            }
        )


@router.post(
    "/bot/emergency-post/{city}",
    summary="Emergency Airpocalypse post",
    description="Force an emergency airpocalypse post for extreme conditions"
)
async def emergency_airpocalypse_post(
    city: str = Path(
        ...,
        description="City name",
        example="Lahore"
    ),
    dry_run: bool = Query(
        False,
        description="If true, don't actually post - just generate"
    ),
    _auth=Depends(verify_tasks_token),
):
    """
    Force an emergency airpocalypse post regardless of schedule.
    
    This endpoint bypasses normal scheduling for extreme air quality events.
    Should only be used when AQI > 500 or other emergency conditions.
    
    - **city**: City name for emergency posting
    - **dry_run**: If true, generate but don't post the emergency thread
    
    **Use Cases:**
    - Manual emergency response
    - Override normal bot scheduling
    - Testing emergency posting system
    
    **Returns:**
    - Emergency thread content
    - Posting status
    - Current conditions that triggered emergency
    """
    try:
        bot = HawanamaBot()
        compiler = LLMDataCompiler()
        
        # Get current data
        payload = await compiler.compile_llm_payload(city=city)
        current_aqi = payload["currentData"]["cityAverageAQI"]
        
        # Validate emergency conditions
        if current_aqi <= 500:
            return {
                "status": "warning",
                "message": f"AQI {current_aqi} does not meet emergency threshold (>500)",
                "current_aqi": current_aqi,
                "emergency_posted": False,
                "recommendation": "Use normal bot cycle for non-emergency conditions"
            }
        
        # Generate emergency content
        emergency_content = await bot.generate_llm_tweet(payload)
        
        if dry_run:
            return {
                "status": "dry_run",
                "message": "Emergency content generated (not posted)",
                "emergency_content": emergency_content,
                "current_conditions": payload["currentData"],
                "emergency_posted": False
            }
        
        # Post emergency thread
        result = await bot.post_tweet_with_logging(
            emergency_content, 
            "emergency_airpocalypse", 
            f"Manual emergency post for AQI {current_aqi}",
            dry_run=False
        )
        
        return {
            "status": "emergency_posted",
            "message": "Emergency airpocalypse thread posted",
            "post_result": result,
            "current_conditions": payload["currentData"],
            "emergency_posted": True
        }
        
    except Exception as e:
        logger.error(f"Emergency post failed for {city}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Emergency post failed: {str(e)}"
        )