import logging
from datetime import datetime, timedelta
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
        self._auth_lock = False  # Verhindert mehrfache gleichzeitige Auth-Versuche

    async def authenticate(self) -> bool:
        """Authenticate with Timeflip API."""
        if self._auth_lock:
            _LOGGER.debug("Authentication already in progress, waiting...")
            return False

        self._auth_lock = True
        try:
            async with async_timeout.timeout(10):
                _LOGGER.info("Attempting authentication with Timeflip API...")
                response = await self.session.post(
                    f"{API_BASE_URL}/api/auth/email/sign-in",
                    json={"email": self.email, "password": self.password},
                    headers={"Content-Type": "application/json"}
                )

                if response.status == 200:
                    data = await response.json()
                    self.token = data.get("token")
                    if self.token:
                        _LOGGER.info("✓ Successfully authenticated with Timeflip API")
                        _LOGGER.debug(f"Token starts with: {self.token[:20]}...")
                        return True
                    else:
                        _LOGGER.error("✗ No token received from API")
                        return False
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"✗ Authentication failed with status {response.status}: {error_text}")
                    return False
        except Exception as e:
            _LOGGER.error(f"✗ Authentication exception: {e}")
            return False
        finally:
            self._auth_lock = False

    async def _request(self, method: str, endpoint: str, retry_count: int = 0, **kwargs) -> Optional[Dict]:
        """Make authenticated API request with retry logic."""
        max_retries = 1  # Nur einmal neu authentifizieren

        # Wenn kein Token, erst authentifizieren
        if not self.token:
            _LOGGER.debug("No token available, authenticating first...")
            if not await self.authenticate():
                _LOGGER.error("Cannot make request: initial authentication failed")
                return None

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.token}"
        headers["Content-Type"] = "application/json"

        try:
            async with async_timeout.timeout(15):
                _LOGGER.debug(f"Making request: {method} {endpoint}")
                response = await self.session.request(
                    method,
                    f"{API_BASE_URL}{endpoint}",
                    headers=headers,
                    **kwargs
                )

                _LOGGER.debug(f"Response status: {response.status} for {method} {endpoint}")

                # Check for token expiration
                if response.status in [401, 403]:
                    try:
                        error_data = await response.json()
                        if error_data.get("code") == 401001 or "jwt token" in error_data.get("message", "").lower():
                            _LOGGER.warning("Token expired or invalid, re-authenticating...")
                            self.token = None
                            if await self.authenticate():
                                return await self._request(method, endpoint, **kwargs)
                            _LOGGER.error("Re-authentication failed")
                            return None
                    except:
                        pass

                    error_text = await response.text()
                    _LOGGER.error(f"API request forbidden ({response.status}) for {endpoint}: {error_text}")
                    return None

                if response.status in [200, 201]:
                    try:
                        return await response.json()
                    except:
                        return {}

                error_text = await response.text()
                _LOGGER.error(f"API request failed with status {response.status} for {endpoint}: {error_text}")
                return None

        except Exception as e:
            _LOGGER.error(f"API request error for {endpoint}: {e}")
            return None

    async def get_tasks(self) -> Optional[List[Dict]]:
        """Get all tasks."""
        result = await self._request("GET", "/api/tasks/byUser")
        if result and isinstance(result, list):
            active_tasks = [task for task in result if not task.get("deletedAt")]
            _LOGGER.info(f"Loaded {len(active_tasks)} active tasks")
            return active_tasks
        return []

    async def get_sync_data(self) -> Optional[Dict]:
        """Get sync data."""
        result = await self._request("GET", "/api/sync")
        if result:
            return result

        _LOGGER.warning("Main sync endpoint failed, trying /api/sync/all")
        result = await self._request("GET", "/api/sync/all")
        if result:
            return result

        _LOGGER.warning("Could not fetch sync data, returning empty structure")
        return {"tasks": [], "timeIntervals": []}

    async def get_weekly_report(self, start_date: str, end_date: str, task_ids: List[int] = None) -> Optional[Dict]:
        """Get weekly report.

        Args:
            start_date: Start date in format YYYY-MM-DD
            end_date: End date in format YYYY-MM-DD
            task_ids: Optional list of task IDs to filter
        """
        body = {
            "beginDateStr": start_date,
            "endDateStr": end_date
        }

        if task_ids:
            body["taskIds"] = task_ids

        result = await self._request("POST", "/report/weekly", json=body)
        return result

    async def get_daily_report(self, start_date: str, end_date: str, task_ids: List[int] = None) -> Optional[Dict]:
        """Get daily report."""
        body = {
            "beginDateStr": start_date,
            "endDateStr": end_date
        }

        if task_ids:
            body["taskIds"] = task_ids

        result = await self._request("POST", "/report/daily", json=body)
        return result

    async def get_tasks_by_period(self, start_date: str, end_date: str) -> Optional[List[Dict]]:
        """Get tasks with time entries for a period."""
        params = {
            "beginDateStr": start_date,
            "endDateStr": end_date
        }

        result = await self._request("GET", "/api/tasks/byPeriod", params=params)
        return result if isinstance(result, list) else []

    async def start_task(self, task_id: int) -> bool:
        """Start tracking a task."""
        now = datetime.utcnow()
        sync_data = await self.get_sync_data()

        interval = {
            "startedAt": now.strftime("%Y-%m-%d %H:%M:%S"),
            "duration": 0,
            "taskId": task_id,
        }

        request_data = {
            "tasks": sync_data.get("tasks", []),
            "timeIntervals": [interval]
        }

        _LOGGER.info(f"Starting task {task_id}")
        result = await self._request("POST", "/api/sync", json=request_data)

        if result is not None:
            _LOGGER.info(f"Successfully started task {task_id}")
            return True
        else:
            _LOGGER.error(f"Failed to start task {task_id}")
            return False

    async def stop_tracking(self, current_interval: Dict) -> bool:
        """Stop current tracking."""
        if not current_interval:
            _LOGGER.warning("No interval provided to stop")
            return False

        try:
            started_at = datetime.strptime(
                current_interval["startedAt"],
                "%Y-%m-%d %H:%M:%S"
            )
            duration = int((datetime.utcnow() - started_at).total_seconds())

            updated_interval = current_interval.copy()
            updated_interval["duration"] = duration

            sync_data = await self.get_sync_data()

            request_data = {
                "tasks": sync_data.get("tasks", []),
                "timeIntervals": [updated_interval]
            }

            _LOGGER.info(f"Stopping tracking (duration: {duration}s)")
            result = await self._request("POST", "/api/sync", json=request_data)

            if result is not None:
                _LOGGER.info("Successfully stopped tracking")
                return True
            else:
                _LOGGER.error("Failed to stop tracking")
                return False

        except Exception as e:
            _LOGGER.error(f"Error stopping tracking: {e}")
            return False