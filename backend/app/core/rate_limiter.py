"""
VIGIL-AI Defensive Rate Limiting & Security Headers Middleware.

Protects backend APIs against:
1. Denial of Service (DoS) and Brute-Force Attacks
2. API Key Scraping and Model Inversion Probing
3. Clickjacking and MIME-type sniffing (via strict security response headers)
"""

import time
from collections import defaultdict
import threading
from typing import Dict, List, Tuple
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.audit_logger import audit_logger
from app.core.config import settings


class InMemoryRateLimiter:
    """
    Sliding window in-memory rate limiter per IP address with auto-expiration.
    """

    def __init__(self, max_requests_per_minute: int = 120):
        self.limit = max_requests_per_minute
        self.window_seconds = 60.0
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, client_ip: str) -> Tuple[bool, int]:
        """
        Checks whether client IP is allowed.
        Returns:
            (allowed: bool, remaining_requests: int)
        """
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            # Purge timestamps outside sliding window
            timestamps = self.requests[client_ip]
            valid_timestamps = [t for t in timestamps if t > window_start]
            self.requests[client_ip] = valid_timestamps

            if len(valid_timestamps) >= self.limit:
                return False, 0

            valid_timestamps.append(now)
            remaining = self.limit - len(valid_timestamps)
            return True, remaining


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies defensive HTTP security headers to all responses and enforces rate limits.
    """

    def __init__(self, app, max_requests_per_minute: int = 120):
        super().__init__(app)
        self.limiter = InMemoryRateLimiter(max_requests_per_minute=max_requests_per_minute)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Determine client IP (support X-Forwarded-For if behind reverse proxy)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "127.0.0.1"

        # Rate Limit Check (exempt health checks and static files)
        path = request.url.path
        if not path.startswith("/static") and not path.endswith("/health"):
            allowed, remaining = self.limiter.is_allowed(client_ip)
            if not allowed:
                audit_logger.log_event(
                    event_type="RATE_LIMIT_BLOCKED",
                    actor="anonymous",
                    resource_id=path,
                    status="BLOCKED",
                    client_ip=client_ip,
                    details={"limit": self.limiter.limit, "window": "60s"},
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={"Retry-After": "60"},
                    content={
                        "type": "https://errors.vigilai.security/rate-limit-exceeded",
                        "title": "Too Many Requests",
                        "status": 429,
                        "detail": "Rate limit exceeded. Please retry after 60 seconds.",
                    },
                )

        # Process request
        response: Response = await call_next(request)

        # Inject Defense-in-Depth Security Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "microphone=(self)"

        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response
