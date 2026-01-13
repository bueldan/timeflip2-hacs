import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .coordinator import TimeflipDataCoordinator
from .api import TimeflipAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Timeflip from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    session = async_get_clientsession(hass)
    api = TimeflipAPI(email, password, session)

    # Test authentication
    if not await api.authenticate():
        _LOGGER.error("Failed to authenticate with Timeflip API")
        return False

    coordinator = TimeflipDataCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_start_task(call):
        """Handle start task service."""
        task_id = call.data.get("task_id")
        if task_id:
            await api.start_task(task_id)
            await coordinator.async_request_refresh()

    async def handle_stop_tracking(call):
        """Handle stop tracking service."""
        sync_data = coordinator.data.get("sync_data", {})
        intervals = sync_data.get("timeIntervals", [])
        current = next((i for i in intervals if i.get("duration", 0) == 0), None)
        if current:
            await api.stop_tracking(current)
            await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "start_task", handle_start_task)
    hass.services.async_register(DOMAIN, "stop_tracking", handle_stop_tracking)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok