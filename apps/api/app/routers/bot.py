"""
Hawanama Bot API Router - endpoints for bot data compilation and testing
"""

import logging
import json
from fastapi import APIRouter, HTTPException, Query, Path, status
from fastapi.responses import JSONResponse
from typing import Dict, Any

from app.services.llm_data_compiler import LLMDataCompiler, MASTER_PERSONA_PROMPT, AIRPOCALYPSE_PROMPT

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