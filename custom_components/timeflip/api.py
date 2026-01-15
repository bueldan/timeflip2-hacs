"""Timeflip API Client - Improved Version."""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import asyncio

import aiohttp
import async_timeout

_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://newapi.timeflip.io"


class TimeflipAuthenticationError(Exception):
    """Authentication failed."""
    pass


class TimeflipAPI:
    """Timeflip API Client with improved authentication."""

    def __init__(self, email: str, password: str, session: aiohttp.ClientSession):
        """Initialize the API client."""
        self.email = email
        self.password = password
        self.session = session
        self.token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self._auth_lock = asyncio.Lock()  # Verhindert parallele Auth-Versuche
        self._last_auth_attempt: Optional[datetime] = None

    def _is_token_valid(self) -> bool:
        """Check if current token is still valid."""
        if not self.token:
            return False

        if not self.token_expiry:
            # Wenn kein Ablaufdatum bekannt, nehmen wir an, Token ist 10 Minuten gültig
            # und prüfen ob er in den letzten 9 Minuten erhalten wurde
            if self._last_auth_attempt:
                age = datetime.now() - self._last_auth_attempt
                return age < timedelta(minutes=9)
            return False

        # Token abgelaufen?
        return datetime.now() < self.token_expiry

    async def authenticate(self, force: bool = False) -> bool:
        """Authenticate with Timeflip API.

        Args:
            force: Force new authentication even if token seems valid
        """
        # Wenn Token noch gültig und kein Force
        if not force and self._is_token_valid():
            _LOGGER.debug("Using existing valid token")
            return True

        async with self._auth_lock:
            # Double-check nach Lock-Erhalt
            if not force and self._is_token_valid():
                return True

            # Verhindere zu schnelle Auth-Versuche (Rate Limiting)
            if self._last_auth_attempt:
                time_since_last = datetime.now() - self._last_auth_attempt
                if time_since_last < timedelta(seconds=2):
                    wait_time = 2 - time_since_last.total_seconds()
                    _LOGGER.debug(f"Rate limiting: waiting {wait_time:.1f}s before auth")
                    await asyncio.sleep(wait_time)

            try:
                _LOGGER.info("Authenticating with Timeflip API...")
                self._last_auth_attempt = datetime.now()

                async with async_timeout.timeout(15):
                    response = await self.session.post(
                        f"{API_BASE_URL}/api/auth/email/sign-in",
                        json={
                            "email": self.email,
                            "password": self.password
                        },
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json"
                        }
                    )

                    response_text = await response.text()
                    _LOGGER.debug(f"Auth response status: {response.status}")

                    if response.status == 200:
                        try:
                            data = await response.json()
                            self.token = data.get("token")

                            if not self.token:
                                _LOGGER.error("No token in successful auth response")
                                return False

                            # Token-Ablauf berechnen (falls in Response, sonst 10 Min)
                            expires_in = data.get("expiresIn", 600)  # Default 10 Min
                            self.token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)

                            _LOGGER.info(f"✓ Authentication successful (token valid for ~{expires_in//60} min)")
                            _LOGGER.debug(f"Token: {self.token[:20]}...")
                            return True

                        except Exception as e:
                            _LOGGER.error(f"Error parsing auth response: {e}")
                            _LOGGER.debug(f"Response body: {response_text}")
                            return False
                    else:
                        _LOGGER.error(f"✗ Authentication failed: {response.status}")
                        _LOGGER.debug(f"Response: {response_text}")

                        # Bei 401/403 sind Credentials wahrscheinlich falsch
                        if response.status in [401, 403]:
                            raise TimeflipAuthenticationError(
                                f"Invalid credentials (status {response.status})"
                            )
                        return False

            except asyncio.TimeoutError:
                _LOGGER.error("✗ Authentication timeout")
                return False
            except TimeflipAuthenticationError:
                raise
            except Exception as e:
                _LOGGER.error(f"✗ Authentication exception: {e}")
                return False

    async def _request(
        self,
        method: str,
        endpoint: str,
        retry_on_401: bool = True,
        **kwargs
    ) -> Optional[Dict]:
        """Make authenticated API request."""

        # Authentifizieren falls nötig
        if not self._is_token_valid():
            _LOGGER.debug("Token invalid/expired, authenticating...")
            if not await self.authenticate():
                _LOGGER.error("Cannot make request: authentication failed")
                return None

        headers = kwargs.pop("headers", {})
        headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

        try:
            async with async_timeout.timeout(20):
                _LOGGER.debug(f"{method} {endpoint}")

                response = await self.session.request(
                    method,
                    f"{API_BASE_URL}{endpoint}",
                    headers=headers,
                    **kwargs
                )

                _LOGGER.debug(f"Response: {response.status}")

                # Token abgelaufen/ungültig
                if response.status in [401, 403]:
                    try:
                        error_data = await response.json()
                        error_code = error_data.get("code")
                        error_msg = error_data.get("message", "").lower()

                        # Token-Fehler erkennen
                        is_token_error = (
                            error_code == 401001 or
                            "jwt" in error_msg or
                            "token" in error_msg or
                            "expired" in error_msg
                        )

                        if is_token_error and retry_on_401:
                            _LOGGER.warning(f"Token error detected: {error_msg}")
                            _LOGGER.info("Forcing re-authentication...")

                            # Token explizit löschen
                            self.token = None
                            self.token_expiry = None

                            # Neu authentifizieren (mit force)
                            if await self.authenticate(force=True):
                                # Ein Retry, nicht rekursiv
                                _LOGGER.info("Re-authentication successful, retrying request...")
                                return await self._request(
                                    method, endpoint,
                                    retry_on_401=False,  # Kein weiterer Retry
                                    **kwargs
                                )
                            else:
                                _LOGGER.error("Re-authentication failed")
                                return None

                        _LOGGER.error(f"API error {response.status}: {error_data}")
                        return None

                    except Exception as e:
                        error_text = await response.text()
                        _LOGGER.error(f"Error parsing {response.status} response: {e}")
                        _LOGGER.debug(f"Response body: {error_text}")
                        return None

                # Erfolg
                if response.status in [200, 201]:
                    try:
                        return await response.json()
                    except:
                        # Leere Antwort ist OK
                        return {}

                # Andere Fehler
                error_text = await response.text()
                _LOGGER.error(f"API request failed with {response.status}: {error_text}")
                return None

        except asyncio.TimeoutError:
            _LOGGER.error(f"Request timeout for {endpoint}")
            return None
        except Exception as e:
            _LOGGER.error(f"Request exception for {endpoint}: {e}")
            return None

    async def get_tasks(self) -> Optional[List[Dict]]:
        """Get all tasks."""
        result = await self._request("GET", "/api/tasks/byUser")
        if result and isinstance(result, list):
            active_tasks = [task for task in result if not task.get("deletedAt")]
            _LOGGER.info(f"Loaded {len(active_tasks)} active tasks")
            return active_tasks
        elif result is None:
            _LOGGER.warning("Failed to load tasks, returning empty list")
            return []
        return []

    async def get_sync_data(self) -> Optional[Dict]:
        """Get sync data."""
        result = await self._request("GET", "/api/sync")
        if result:
            return result

        _LOGGER.debug("Main sync endpoint returned nothing, trying /api/sync/all")
        result = await self._request("GET", "/api/sync/all")
        if result:
            return result

        _LOGGER.warning("Could not fetch sync data, returning empty structure")
        return {"tasks": [], "timeIntervals": []}

    async def get_weekly_report(self, start_date: str, end_date: str, task_ids: List[int] = None) -> Optional[Dict]:
        """Get weekly report."""
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

        # Get current sync data
        sync_data = await self.get_sync_data()
        if sync_data is None:
            _LOGGER.error("Cannot start task: failed to get sync data")
            return False

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
            _LOGGER.info(f"✓ Successfully started task {task_id}")
            return True
        else:
            _LOGGER.error(f"✗ Failed to start task {task_id}")
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
            if sync_data is None:
                _LOGGER.error("Cannot stop tracking: failed to get sync data")
                return False

            request_data = {
                "tasks": sync_data.get("tasks", []),
                "timeIntervals": [updated_interval]
            }

            _LOGGER.info(f"Stopping tracking (duration: {duration}s)")
            result = await self._request("POST", "/api/sync", json=request_data)

            if result is not None:
                _LOGGER.info("✓ Successfully stopped tracking")
                return True
            else:
                _LOGGER.error("✗ Failed to stop tracking")
                return False

        except Exception as e:
            _LOGGER.error(f"✗ Error stopping tracking: {e}")
            return False