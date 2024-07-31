import asyncio
from collections import deque
from ..utils.config import load_config
from ..utils.logging_config import logger

config = load_config()

class RequestQueue:
    def __init__(self):
        self.queue = deque()
        self.current_request = None
        self.lock = asyncio.Lock()

    async def add_request(self, request):
        async with self.lock:
            self.queue.append(request)
            return len(self.queue)

    async def get_next_request(self):
        async with self.lock:
            if self.queue:
                self.current_request = self.queue.popleft()
                return self.current_request
            return None

    async def complete_current_request(self):
        async with self.lock:
            self.current_request = None

    async def get_queue_position(self, request_id):
        async with self.lock:
            for i, request in enumerate(self.queue):
                if request['id'] == request_id:
                    return i + 1
            return None

    async def get_request_by_id(self, request_id):
        async with self.lock:
            for request in self.queue:
                if request['id'] == request_id:
                    return request
            return None

    def estimate_wait_time(self, position):
        return position * config['queue']['estimated_generation_time']

request_queue = RequestQueue()
