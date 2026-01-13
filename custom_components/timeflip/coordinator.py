import logging
from datetime import timedelta
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TimeflipAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)  # Erhöht von 30 auf 60 Sekunden


class TimeflipDataCoordinator(DataUpdateCoordinator):
    """Coordinator to manage Timeflip data updates."""

    def __init__(self, hass: HomeAssistant, api: TimeflipAPI):
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.api = api
        self._consecutive_errors = 0

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API."""
        try:
            tasks = await self.api.get_tasks()
            sync_data = await self.api.get_sync_data()
            
            # Reset error counter on success
            if tasks is not None or sync_data is not None:
                self._consecutive_errors = 0

            return {
                "tasks": tasks or [],
                "sync_data": sync_data or {},
            }
        except Exception as err:
            self._consecutive_errors += 1
            _LOGGER.error(f"Error fetching Timeflip data (error #{self._consecutive_errors}): {err}")

            # Don't raise UpdateFailed immediately, return last known data
            if self._consecutive_errors < 3:
                return self.data if self.data else {"tasks": [], "sync_data": {}}

            raise UpdateFailed(f"Error fetching Timeflip data: {err}")