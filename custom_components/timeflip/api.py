import logging
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp
import async_timeout

_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://newapi.timeflip.io"


class TimeflipAPI:
    """Timeflip API Client."""

    def __init__(self, email: str, password: str, session: aiohttp.ClientSession):
        """Initialize the API client."""
        self.email = email
        self.password = password
        self.session = session
        self.token: Optional[str] = None

    async def authenticate(self) -> bool:
        """Authenticate with Timeflip API."""
        try:
            async with async_timeout.timeout(10):
                response = await self.session.post(
                    f"{API_BASE_URL}/api/auth/email/sign-in",
                    json={"email": self.email, "password": self.password}
                )
                if response.status == 200:
                    data = await response.json()
                    self.token = data.get("token")
                    _LOGGER.info("Successfully authenticated with Timeflip API")
                    return True
                _LOGGER.error(f"Authentication failed with status: {response.status}")
                return False
        except Exception as e:
            _LOGGER.error(f"Authentication error: {e}")
            return False

    async def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        """Make authenticated API request."""
        if not self.token:
            if not await self.authenticate():
                return None

        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            async with async_timeout.timeout(10):
                response = await self.session.request(
                    method,
                    f"{API_BASE_URL}{endpoint}",
                    headers=headers,
                    **kwargs
                )
                if response.status == 401:
                    if await self.authenticate():
                        return await self._request(method, endpoint, **kwargs)
                    return None
                
                if response.status in [200, 201]:
                    return await response.json()
                
                _LOGGER.error(f"API request failed: {response.status}")
                return None
        except Exception as e:
            _LOGGER.error(f"API request error: {e}")
            return None

    async def get_tasks(self) -> Optional[List[Dict]]:
        """Get all tasks."""
        result = await self._request("GET", "/api/tasks/byUser")
        if result and isinstance(result, list):
            return [task for task in result if not task.get("deletedAt")]
        return None

    async def get_sync_data(self) -> Optional[Dict]:
        """Get sync data."""
        return await self._request("GET", "/api/sync")

    async def start_task(self, task_id: int) -> bool:
        """Start tracking a task."""
        now = datetime.utcnow()
        interval = {
            "startedAt": now.strftime("%Y-%m-%d %H:%M:%S"),
            "duration": 0,
            "taskId": task_id,
        }
        sync_data = {"tasks": [], "timeIntervals": [interval]}
        result = await self._request("POST", "/api/sync", json=sync_data)
        return result is not None

    async def stop_tracking(self, current_interval: Dict) -> bool:
        """Stop current tracking."""
        if not current_interval:
            return False
        started_at = datetime.strptime(current_interval["startedAt"], "%Y-%m-%d %H:%M:%S")
        duration = int((datetime.utcnow() - started_at).total_seconds())
        updated_interval = current_interval.copy()
        updated_interval["duration"] = duration
        sync_data = {"tasks": [], "timeIntervals": [updated_interval]}
        result = await self._request("POST", "/api/sync", json=sync_data)
        return result is not None