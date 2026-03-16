"""
Rate Limiter for LLM API Calls

Implements strict RPM (requests per minute) and RPD (requests per day) tracking
with configurable warning thresholds and blocking behavior.
"""

import time
import logging
import threading
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when rate limit is exceeded"""
    pass


class RateLimiter:
    """
    Rate limiter for LLM API calls with STRICT RPD and RPM enforcement.

    Tracks API requests and enforces per-minute and per-day limits.
    When limits are exceeded, acquire() raises RateLimitError.
    """

    def __init__(
        self,
        rpm_limit: int,
        rpd_limit: int,
        warning_threshold: float = 0.8,
        name: Optional[str] = None
    ):
        """
        Initialize rate limiter.

        Args:
            rpm_limit: Maximum requests per minute
            rpd_limit: Maximum requests per day
            warning_threshold: Warning level (0.0-1.0) of limit (default: 0.8)
            name: Optional name for this rate limiter (for logging)
        """
        self.rpm_limit = rpm_limit
        self.rpd_limit = rpd_limit
        self.warning_threshold = warning_threshold
        self.name = name or "RateLimiter"
        self.requests = []  # List of timestamps
        self._lock = threading.Lock()  # Thread-safe lock

        logger.info(
            f"Initialized {self.name}: RPM={rpm_limit}, RPD={rpd_limit}, "
            f"warning_threshold={warning_threshold}"
        )

    def _clean_old_requests(self, now: float, day_ago: float):
        """Remove requests older than one day"""
        self.requests = [t for t in self.requests if t > day_ago]

    def _get_usage_stats(self, now: float) -> dict:
        """Get current usage statistics"""
        minute_ago = now - 60
        day_ago = now - 86400

        recent_minute = sum(1 for t in self.requests if t > minute_ago)
        recent_day = len(self.requests)

        return {
            "rpm_current": recent_minute,
            "rpm_limit": self.rpm_limit,
            "rpm_usage": recent_minute / self.rpm_limit if self.rpm_limit > 0 else 0,
            "rpd_current": recent_day,
            "rpd_limit": self.rpd_limit,
            "rpd_usage": recent_day / self.rpd_limit if self.rpd_limit > 0 else 0,
        }

    def _check_warnings(self, stats: dict):
        """Log warnings if approaching limits"""
        if stats["rpm_usage"] >= self.warning_threshold:
            logger.warning(
                f"{self.name}: Approaching RPM limit - "
                f"{stats['rpm_current']}/{stats['rpm_limit']} "
                f"({stats['rpm_usage']:.1%} used)"
            )

        if stats["rpd_usage"] >= self.warning_threshold:
            logger.warning(
                f"{self.name}: Approaching RPD limit - "
                f"{stats['rpd_current']}/{stats['rpd_limit']} "
                f"({stats['rpd_usage']:.1%} used)"
            )

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Attempt to acquire a request slot under rate limits (thread-safe).

        Args:
            timeout: Maximum time to wait for a slot (None = no waiting)

        Returns:
            True if request is allowed

        Raises:
            RateLimitError: If rate limit is exceeded (and timeout is None or wait times out)
        """
        with self._lock:
            now = time.time()
            minute_ago = now - 60
            day_ago = now - 86400

            # Clean old requests
            self._clean_old_requests(now, day_ago)

            # Get current usage
            stats = self._get_usage_stats(now)

            # Log warnings if approaching limits
            self._check_warnings(stats)

            # Check limits
            if stats["rpm_current"] >= self.rpm_limit:
                if timeout is not None:
                    # Release lock before waiting
                    pass  # Will handle in _wait_until_available
                else:
                    raise RateLimitError(
                        f"{self.name}: RPM limit exceeded - "
                        f"{stats['rpm_current']}/{stats['rpm_limit']} requests in last minute"
                    )

            if stats["rpd_current"] >= self.rpd_limit:
                if timeout is not None:
                    # Release lock before waiting
                    pass  # Will handle in _wait_until_available
                else:
                    raise RateLimitError(
                        f"{self.name}: RPD limit exceeded - "
                        f"{stats['rpd_current']}/{stats['rpd_limit']} requests in last day"
                    )

            # Request allowed
            self.requests.append(now)
            logger.debug(
                f"{self.name}: Request allowed (RPM: {stats['rpm_current']+1}/{self.rpm_limit}, "
                f"RPD: {stats['rpd_current']+1}/{self.rpd_limit})"
            )
            return True

    def _wait_until_available(self, timeout: float) -> bool:
        """
        Wait until a request slot is available.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if slot became available, False if timeout
        """
        start = time.time()
        logger.info(f"{self.name}: Waiting for rate limit slot (timeout: {timeout}s)...")

        while time.time() - start < timeout:
            try:
                now = time.time()
                minute_ago = now - 60
                day_ago = now - 86400

                # Clean old requests
                self._clean_old_requests(now, day_ago)

                # Get current usage
                stats = self._get_usage_stats(now)

                # Check if we can proceed
                if stats["rpm_current"] < self.rpm_limit and stats["rpd_current"] < self.rpd_limit:
                    logger.info(f"{self.name}: Rate limit slot available after {time.time() - start:.1f}s")
                    self.requests.append(now)
                    return True

                # Wait a bit before checking again
                time.sleep(1)

            except RateLimitError:
                # Continue waiting
                pass

        logger.warning(f"{self.name}: Timeout waiting for rate limit slot")
        return False

    def get_status(self) -> dict:
        """
        Get current rate limiter status (thread-safe).

        Returns:
            Dictionary with current usage statistics
        """
        with self._lock:
            now = time.time()
            day_ago = now - 86400
            self._clean_old_requests(now, day_ago)
            return self._get_usage_stats(now)

    def reset(self):
        """Reset all rate limit tracking (useful for testing)"""
        with self._lock:
            self.requests.clear()
            logger.info(f"{self.name}: Rate limiter reset")


class TokenTracker:
    """
    Tracks token usage per user and operation type.
    Thread-safe for concurrent operations.
    """

    def __init__(self):
        """Initialize token tracker."""
        self.usage = {}  # {username: {operation: {prompt: X, response: Y, total: Z}}}
        self._lock = threading.Lock()
        logger.info("TokenTracker initialized")

    def track(self, username: str, operation: str, prompt_tokens: int, response_tokens: int):
        """
        Track token usage for a user and operation.

        Args:
            username: Username or identifier
            operation: Operation type (e.g., "blog_generation", "recommendation")
            prompt_tokens: Number of prompt tokens used
            response_tokens: Number of response/completion tokens used
        """
        with self._lock:
            if username not in self.usage:
                self.usage[username] = {}

            if operation not in self.usage[username]:
                self.usage[username][operation] = {
                    "prompt": 0,
                    "response": 0,
                    "total": 0,
                    "count": 0
                }

            self.usage[username][operation]["prompt"] += prompt_tokens
            self.usage[username][operation]["response"] += response_tokens
            self.usage[username][operation]["total"] += (prompt_tokens + response_tokens)
            self.usage[username][operation]["count"] += 1

    def get_usage(self, username: Optional[str] = None) -> dict:
        """
        Get token usage statistics.

        Args:
            username: Specific user (None = all users)

        Returns:
            Dictionary with usage statistics
        """
        with self._lock:
            if username:
                return self.usage.get(username, {})
            return self.usage.copy()

    def log_summary(self, username: str):
        """
        Log token usage summary for a user.

        Args:
            username: Username to log summary for
        """
        with self._lock:
            if username not in self.usage:
                logger.info(f"[{username}] No token usage recorded")
                return

            user_usage = self.usage[username]
            total_tokens = sum(op["total"] for op in user_usage.values())

            logger.info(f"[{username}] Token Usage Summary:")
            for operation, stats in user_usage.items():
                avg_prompt = stats["prompt"] / stats["count"] if stats["count"] > 0 else 0
                avg_response = stats["response"] / stats["count"] if stats["count"] > 0 else 0
                logger.info(
                    f"  [{operation}] Count: {stats['count']}, "
                    f"Prompt: {stats['prompt']} (avg: {avg_prompt:.0f}), "
                    f"Response: {stats['response']} (avg: {avg_response:.0f}), "
                    f"Total: {stats['total']}"
                )
            logger.info(f"  [TOTAL] All operations: {total_tokens} tokens")

    def reset(self):
        """Reset all tracking data"""
        with self._lock:
            self.usage.clear()
            logger.info("TokenTracker reset")


class ModelRateLimiter:
    """
    Manages rate limiting for multiple models with different limits.

    Each model can have its own RPM/RPD limits.
    """

    def __init__(self, model_configs: dict):
        """
        Initialize model rate limiters from configuration.

        Args:
            model_configs: Dictionary of model configurations with rate_limits

        Example:
            model_configs = {
                "blog_generation": {
                    "rate_limits": {"rpm": 15, "rpd": 1500, "warning_threshold": 0.8}
                },
                "recommendation": {
                    "rate_limits": {"rpm": 10, "rpd": 1000, "warning_threshold": 0.8}
                }
            }
        """
        self.limiters = {}
        for model_name, config in model_configs.items():
            rate_limits = config.get("rate_limits", {})
            if rate_limits:
                self.limiters[model_name] = RateLimiter(
                    rpm_limit=rate_limits.get("rpm", 0),
                    rpd_limit=rate_limits.get("rpd", 0),
                    warning_threshold=rate_limits.get("warning_threshold", 0.8),
                    name=model_name
                )
                logger.info(f"Created rate limiter for model: {model_name}")

    def get_limiter(self, model_name: str) -> Optional[RateLimiter]:
        """Get rate limiter for a specific model"""
        return self.limiters.get(model_name)

    def acquire(self, model_name: str, timeout: Optional[float] = None) -> bool:
        """
        Acquire a request slot for a specific model.

        Args:
            model_name: Name of the model (e.g., "blog_generation", "recommendation")
            timeout: Maximum time to wait for a slot

        Returns:
            True if request is allowed

        Raises:
            RateLimitError: If model has rate limits and limit is exceeded
        """
        limiter = self.get_limiter(model_name)
        if limiter:
            return limiter.acquire(timeout=timeout)
        # No rate limiting configured for this model
        return True

    def get_all_status(self) -> dict:
        """Get status of all rate limiters"""
        return {
            model_name: limiter.get_status()
            for model_name, limiter in self.limiters.items()
        }
