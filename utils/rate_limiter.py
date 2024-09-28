# rate_limiter.py

import threading
import time

class RateLimiter:
    def __init__(self, max_calls, period):
        self.lock = threading.Lock()
        self.calls = []
        self.max_calls = max_calls
        self.period = period

    def acquire(self):
        with self.lock:
            now = time.time()
            # Remove calls older than the period
            self.calls = [call for call in self.calls if now - call < self.period]
            if len(self.calls) >= self.max_calls:
                # Need to wait before making a new call
                sleep_time = self.period - (now - self.calls[0])
                time.sleep(sleep_time)
                now = time.time()
                # Clean up old calls again after sleeping
                self.calls = [call for call in self.calls if now - call < self.period]
            # Record the new call
            self.calls.append(now)
