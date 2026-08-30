"""Small stateless helpers used by the chat endpoint."""

import logging
import time
from django.core.cache import cache

logger = logging.getLogger(__name__)


def retry_groq_call(fn, max_retries=3, base_delay=1):
    """Retry transient Groq request setup failures with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning("groq_retry", extra={"attempt": attempt + 1, "delay": delay})
            time.sleep(delay)


def claim_request(request_id, ttl=300):
    """Atomically claim an idempotency key until its request completes."""
    return cache.add(f"jarvis-request:{request_id}", True, timeout=ttl)
