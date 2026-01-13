import logging
from datetime import timedelta
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TimeflipAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


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

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API."""
        try:
            tasks = await self.api.get_tasks()
            sync_data = await self.api.get_sync_data()
            
            return {
                "tasks": tasks or [],
                "sync_data": sync_data or {},
            }
        except Exception as err:
            raise UpdateFailed(f"Error fetching Timeflip data: {err}")