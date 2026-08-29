"""
Gemini AI Service for Hawanama Bot

Handles LLM API calls to Google Gemini for generating bot tweets.
"""

import logging
import json
from typing import Dict, List, Optional, Any
import google.generativeai as genai

from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiAIService:
    """Service for generating bot tweets using Google Gemini AI"""
    
    def __init__(self):
        self.model = None
        self._init_gemini_client()
    
    def _init_gemini_client(self) -> None:
        """Initialize Gemini AI client using configuration settings."""
        if not settings.GEMINI_API_KEY:
            raise ValueError("Missing GEMINI_API_KEY in configuration")
        
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
            logger.info("Gemini AI client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini AI client: {e}")
            raise RuntimeError(f"Gemini AI initialization failed: {e}")
    
    async def generate_tweet(self, prompt: str, max_retries: int = 3) -> str:
        """
        Generate a tweet using Gemini AI.
        
        Args:
            prompt: The complete prompt with data inserted
            max_retries: Maximum number of retry attempts
            
        Returns:
            Generated tweet text
        """
        if not self.model:
            raise RuntimeError("Gemini AI client not initialized")
        
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Generating tweet with Gemini AI (attempt {attempt}/{max_retries})")
                
                # Generate content using Gemini
                response = self.model.generate_content(prompt)
                
                if not response.text:
                    raise ValueError("Empty response from Gemini AI")
                
                tweet_text = response.text.strip()
                
                # Basic validation
                if len(tweet_text) > 280:
                    logger.warning(f"Generated tweet too long ({len(tweet_text)} chars), truncating")
                    tweet_text = tweet_text[:277] + "..."
                
                logger.info(f"Successfully generated tweet: {tweet_text}")
                return tweet_text
                
            except Exception as e:
                last_error = e
                logger.warning(f"Tweet generation attempt {attempt} failed: {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(2 * attempt)  # Exponential backoff
                    continue
        
        logger.error(f"Failed to generate tweet after {max_retries} attempts: {last_error}")
        raise RuntimeError(f"Tweet generation failed after {max_retries} attempts: {last_error}")
    
    async def generate_airpocalypse_thread(self, prompt: str, max_retries: int = 3) -> List[str]:
        """
        Generate a 2-tweet thread for airpocalypse situations (AQI > 500).
        
        Args:
            prompt: The airpocalypse prompt with data inserted
            max_retries: Maximum number of retry attempts
            
        Returns:
            List of 2 tweet texts [alert_tweet, advisory_tweet]
        """
        if not self.model:
            raise RuntimeError("Gemini AI client not initialized")
        
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Generating airpocalypse thread with Gemini AI (attempt {attempt}/{max_retries})")
                
                # Generate content using Gemini
                response = self.model.generate_content(prompt)
                
                if not response.text:
                    raise ValueError("Empty response from Gemini AI")
                
                response_text = response.text.strip()
                
                # Parse the response to extract two tweets
                tweets = self._parse_tweet_thread(response_text)
                
                if len(tweets) != 2:
                    raise ValueError(f"Expected 2 tweets, got {len(tweets)}")
                
                # Validate tweet lengths
                for i, tweet in enumerate(tweets):
                    if len(tweet) > 280:
                        logger.warning(f"Tweet {i+1} too long ({len(tweet)} chars), truncating")
                        tweets[i] = tweet[:277] + "..."
                
                logger.info(f"Successfully generated airpocalypse thread: {len(tweets)} tweets")
                return tweets
                
            except Exception as e:
                last_error = e
                logger.warning(f"Airpocalypse thread generation attempt {attempt} failed: {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(2 * attempt)  # Exponential backoff
                    continue
        
        logger.error(f"Failed to generate airpocalypse thread after {max_retries} attempts: {last_error}")
        raise RuntimeError(f"Airpocalypse thread generation failed after {max_retries} attempts: {last_error}")
    
    def _parse_tweet_thread(self, response_text: str) -> List[str]:
        """
        Parse the AI response to extract individual tweets from a thread.
        
        Args:
            response_text: Raw AI response text
            
        Returns:
            List of individual tweet texts
        """
        # Common patterns for tweet separation
        separators = [
            "Tweet 1:",
            "Tweet 2:",
            "1.",
            "2.",
            "**Tweet 1:**",
            "**Tweet 2:**",
            "---",
            "\n\n"
        ]
        
        # Try to split by common separators
        tweets = []
        text = response_text.strip()
        
        # First try numbered patterns
        import re
        
        # Pattern: Tweet 1: ... Tweet 2: ...
        pattern1 = r"Tweet\s*1[:\-]\s*(.*?)\s*Tweet\s*2[:\-]\s*(.*)"
        match1 = re.search(pattern1, text, re.DOTALL | re.IGNORECASE)
        if match1:
            tweets = [match1.group(1).strip(), match1.group(2).strip()]
            return tweets
        
        # Pattern: 1. ... 2. ...
        pattern2 = r"1\.\s*(.*?)\s*2\.\s*(.*)"
        match2 = re.search(pattern2, text, re.DOTALL)
        if match2:
            tweets = [match2.group(1).strip(), match2.group(2).strip()]
            return tweets
        
        # Try splitting by double newlines
        parts = text.split('\n\n')
        if len(parts) >= 2:
            tweets = [part.strip() for part in parts[:2] if part.strip()]
            return tweets
        
        # Fallback: split by single newlines and take first two substantial parts
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if len(lines) >= 2:
            tweets = lines[:2]
            return tweets
        
        # Last resort: return the whole text as one tweet
        return [text]
    
    async def test_connection(self) -> Dict[str, Any]:
        """
        Test Gemini AI connection and return status.
        
        Returns:
            Dict with connection status and details
        """
        try:
            if not self.model:
                return {
                    "status": "error",
                    "message": "Gemini AI client not initialized",
                    "connected": False
                }
            
            # Test with a simple prompt
            test_prompt = "Generate a very short test message (max 10 words)."
            response = self.model.generate_content(test_prompt)
            
            return {
                "status": "success",
                "message": "Gemini AI connection successful",
                "connected": True,
                "test_response": response.text.strip() if response.text else "No response"
            }
            
        except Exception as e:
            logger.error(f"Gemini AI connection test failed: {e}")
            return {
                "status": "error",
                "message": f"Connection test failed: {str(e)}",
                "connected": False
            }