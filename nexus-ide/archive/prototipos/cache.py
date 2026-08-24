import time
import threading

class TTLCache:
    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._store = {}
        self._lock = threading.RLock()

    def set(self, key: str, value):
        expire = time.time() + self.ttl
        with self._lock:
            self._store[key] = (value, expire)

    def get(self, key: str):
        with self._lock:
            entry = self._store.get(key)
            if entry:
                value, expire = entry
                if time.time() < expire:
                    return value
                else:
                    del self._store[key]
            return None

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def clear(self):
        with self._lock:
            self._store.clear()