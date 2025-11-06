"""
Trade Protection Module
Handles slippage validation and rate limiting
"""
import asyncio
import time
import logging
from functools import wraps
from typing import Callable, Dict, Optional
from collections import deque

logger = logging.getLogger(__name__)

class SlippageProtection:
    """
    Protects against excessive slippage on order execution
    
    Slippage = difference between expected price and actual execution price
    """
    
    # Default slippage limits
    MAX_SLIPPAGE_PERCENT = 0.5  # 0.5% maximum slippage
    WARNING_SLIPPAGE_PERCENT = 0.3  # 0.3% warning threshold
    
    @staticmethod
    def calculate_slippage(expected_price: float, actual_price: float, side: str = 'buy') -> Dict:
        """
        Calculate slippage between expected and actual price
        
        Args:
            expected_price: Expected execution price (limit price)
            actual_price: Actual execution price (fill price)
            side: 'buy' or 'sell'
        
        Returns:
            Dict with slippage details
        """
        try:
            if expected_price <= 0 or actual_price <= 0:
                return {
                    'valid': False,
                    'error': 'Invalid prices',
                    'slippage_percent': 0
                }
            
            # Calculate price difference
            price_diff = actual_price - expected_price
            
            # For buys: negative slippage = better price (bought cheaper)
            # For sells: positive slippage = better price (sold higher)
            if side == 'buy':
                slippage_percent = (price_diff / expected_price) * 100
                favorable = price_diff < 0
            else:  # sell
                slippage_percent = (-price_diff / expected_price) * 100
                favorable = price_diff > 0
            
            # Determine if within acceptable limits
            is_acceptable = abs(slippage_percent) <= SlippageProtection.MAX_SLIPPAGE_PERCENT
            is_warning = abs(slippage_percent) >= SlippageProtection.WARNING_SLIPPAGE_PERCENT
            
            result = {
                'valid': is_acceptable,
                'slippage_percent': round(slippage_percent, 3),
                'slippage_amount': round(abs(price_diff), 2),
                'expected_price': expected_price,
                'actual_price': actual_price,
                'favorable': favorable,
                'status': 'ACCEPTABLE' if is_acceptable else 'EXCESSIVE'
            }
            
            # Log results
            emoji = "✅" if is_acceptable else "⚠️"
            direction = "favorable" if favorable else "unfavorable"
            
            if is_acceptable:
                if is_warning:
                    logger.warning(
                        f"{emoji} Slippage: {slippage_percent:+.3f}% ({direction})\n"
                        f"   Expected: ${expected_price:.2f}, Got: ${actual_price:.2f}"
                    )
                else:
                    logger.info(
                        f"{emoji} Slippage: {slippage_percent:+.3f}% ({direction})"
                    )
            else:
                logger.error(
                    f"❌ EXCESSIVE SLIPPAGE: {slippage_percent:+.3f}% ({direction})\n"
                    f"   Expected: ${expected_price:.2f}, Got: ${actual_price:.2f}\n"
                    f"   Maximum allowed: ±{SlippageProtection.MAX_SLIPPAGE_PERCENT}%"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error calculating slippage: {e}")
            return {
                'valid': False,
                'error': str(e),
                'slippage_percent': 0
            }
    
    @staticmethod
    def validate_execution(
        expected_price: float,
        actual_price: float,
        side: str = 'buy',
        auto_reject: bool = True
    ) -> bool:
        """
        Validate if execution price is acceptable
        
        Args:
            expected_price: Expected price
            actual_price: Actual price
            side: Trade side
            auto_reject: Automatically reject excessive slippage
        
        Returns:
            True if acceptable, False otherwise
        """
        result = SlippageProtection.calculate_slippage(expected_price, actual_price, side)
        
        if not result['valid'] and auto_reject:
            logger.error(
                f"🚫 TRADE REJECTED due to excessive slippage\n"
                f"   Slippage: {result['slippage_percent']}%\n"
                f"   Threshold: {SlippageProtection.MAX_SLIPPAGE_PERCENT}%"
            )
            return False
        
        return result['valid']


class RateLimiter:
    """
    Rate limiting for API calls with exponential backoff
    
    Prevents hitting exchange API rate limits
    """
    
    def __init__(self, calls_per_second: float = 10, burst: int = 20):
        """
        Initialize rate limiter
        
        Args:
            calls_per_second: Maximum sustained calls per second
            burst: Maximum burst calls allowed
        """
        self.calls_per_second = calls_per_second
        self.burst = burst
        self.tokens = burst  # Start with full burst capacity
        self.last_update = time.time()
        self.call_history = deque(maxlen=1000)  # Track last 1000 calls
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire a token to make an API call"""
        async with self.lock:
            now = time.time()
            
            # Refill tokens based on time elapsed
            time_passed = now - self.last_update
            self.tokens = min(
                self.burst,
                self.tokens + time_passed * self.calls_per_second
            )
            self.last_update = now
            
            # Wait if no tokens available
            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.calls_per_second
                logger.warning(f"⏳ Rate limit: waiting {wait_time:.2f}s...")
                await asyncio.sleep(wait_time)
                self.tokens = 1
            
            # Consume one token
            self.tokens -= 1
            self.call_history.append(now)
    
    def get_stats(self) -> Dict:
        """Get rate limiting statistics"""
        now = time.time()
        recent_calls = [t for t in self.call_history if now - t < 60]  # Last minute
        
        return {
            'tokens_available': round(self.tokens, 2),
            'calls_last_minute': len(recent_calls),
            'calls_per_second_limit': self.calls_per_second,
            'burst_capacity': self.burst
        }


def with_retry(
    max_attempts: int = 3,
    backoff_base: float = 2,
    backoff_max: float = 60,
    retry_on: tuple = (Exception,)
):
    """
    Decorator to retry function with exponential backoff
    
    Args:
        max_attempts: Maximum retry attempts
        backoff_base: Base for exponential backoff (2 = double each time)
        backoff_max: Maximum wait time between retries
        retry_on: Tuple of exceptions to retry on
    
    Example:
        @with_retry(max_attempts=3)
        async def api_call():
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except retry_on as e:
                    last_exception = e
                    
                    # Check if it's a rate limit error
                    error_msg = str(e).lower()
                    is_rate_limit = any(keyword in error_msg for keyword in [
                        'rate limit', 'too many requests', '429', 'throttle'
                    ])
                    
                    if attempt >= max_attempts:
                        logger.error(
                            f"❌ {func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise
                    
                    # Calculate wait time with exponential backoff
                    if is_rate_limit:
                        wait_time = min(backoff_base ** attempt, backoff_max)
                    else:
                        wait_time = min(backoff_base ** (attempt - 1), backoff_max)
                    
                    logger.warning(
                        f"⚠️ {func.__name__} attempt {attempt}/{max_attempts} failed: {e}\n"
                        f"   Retrying in {wait_time:.1f}s..."
                    )
                    
                    await asyncio.sleep(wait_time)
            
            # Should never reach here, but just in case
            raise last_exception
        
        return wrapper
    return decorator


def with_rate_limit(limiter: RateLimiter):
    """
    Decorator to enforce rate limiting on function
    
    Args:
        limiter: RateLimiter instance
    
    Example:
        limiter = RateLimiter(calls_per_second=5)
        
        @with_rate_limit(limiter)
        async def api_call():
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            await limiter.acquire()
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# Global rate limiters for different exchanges
hyperliquid_limiter = RateLimiter(calls_per_second=10, burst=20)
bybit_limiter = RateLimiter(calls_per_second=5, burst=10)
