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
            success = await api.start_task(task_id)
            if success:
                _LOGGER.info(f"Started task {task_id}")
                await coordinator.async_request_refresh()
            else:
                _LOGGER.error(f"Failed to start task {task_id}")

    async def handle_stop_tracking(call):
        """Handle stop tracking service."""
        sync_data = coordinator.data.get("sync_data", {})
        intervals = sync_data.get("timeIntervals", [])
        current = next((i for i in intervals if i.get("duration", 0) == 0), None)
        if current:
            success = await api.stop_tracking(current)
            if success:
                _LOGGER.info("Stopped tracking")
                await coordinator.async_request_refresh()
            else:
                _LOGGER.error("Failed to stop tracking")
        else:
            _LOGGER.warning("No active tracking to stop")

    async def handle_list_tasks(call):
        """Handle list tasks service - logs all tasks."""
        tasks = coordinator.data.get("tasks", [])
        _LOGGER.info(f"Available tasks ({len(tasks)}):")
        for task in sorted(tasks, key=lambda t: t.get("sideIndex", 999)):
            _LOGGER.info(
                f"  ID: {task.get('id')} | "
                f"Name: {task.get('name')} | "
                f"Seite: {task.get('sideIndex')} | "
                f"Tag: {task.get('tag', 'N/A')}"
            )

        # Show as persistent notification
        task_list = "\n".join([
            f"• {task.get('name')} (ID: {task.get('id')}, Seite: {task.get('sideIndex')})"
            for task in sorted(tasks, key=lambda t: t.get("sideIndex", 999))
        ])

        hass.components.persistent_notification.create(
            f"**Verfügbare Timeflip Tasks:**\n\n{task_list}",
            title="Timeflip Tasks",
            notification_id="timeflip_tasks_list"
        )

    async def handle_debug_api(call):
        """Debug API - test authentication and basic endpoints."""
        _LOGGER.info("=== Timeflip API Debug ===")

        # Test authentication
        auth_ok = await api.authenticate()
        _LOGGER.info(f"Authentication: {'OK' if auth_ok else 'FAILED'}")
        if api.token:
            _LOGGER.info(f"Token: {api.token[:20]}...")
        else:
            _LOGGER.info("No token")

        # Test tasks endpoint
        tasks = await api.get_tasks()
        _LOGGER.info(f"Tasks loaded: {len(tasks) if tasks else 0}")

        # Test sync endpoint
        sync_data = await api.get_sync_data()
        _LOGGER.info(f"Sync data: {sync_data is not None}")

        # Show in notification
        hass.components.persistent_notification.create(
            f"**Debug Results:**\n\n"
            f"Auth: {'✓' if auth_ok else '✗'}\n"
            f"Token: {'✓' if api.token else '✗'}\n"
            f"Tasks: {len(tasks) if tasks else 0}\n"
            f"Sync: {'✓' if sync_data else '✗'}",
            title="Timeflip API Debug",
            notification_id="timeflip_debug"
        )

    async def handle_test_auth(call):
        """Test authentication with current credentials."""
        _LOGGER.info("=== Testing Authentication ===")
        _LOGGER.info(f"Email: {email}")

        # Force new authentication
        api.token = None
        auth_ok = await api.authenticate()

        if auth_ok:
            _LOGGER.info("✓ Authentication successful")
            if api.token:
                _LOGGER.info(f"Token (first 30 chars): {api.token[:30]}...")

            # Now test a simple API call
            tasks = await api.get_tasks()
            if tasks is not None:
                _LOGGER.info(f"✓ API call successful - {len(tasks)} tasks loaded")
            else:
                _LOGGER.error("✗ API call failed even with valid token")
        else:
            _LOGGER.error("✗ Authentication failed - check email/password")

        hass.components.persistent_notification.create(
            f"**Auth Test:**\n\n"
            f"Email: {email}\n"
            f"Auth: {'✓ Success' if auth_ok else '✗ Failed'}\n"
            f"Token: {'✓ Valid' if api.token else '✗ None'}\n"
            f"Tasks: {len(tasks) if tasks else '✗ Failed'}",
            title="Timeflip Auth Test",
            notification_id="timeflip_auth_test"
        )

    # Register all services
    hass.services.async_register(DOMAIN, "start_task", handle_start_task)
    hass.services.async_register(DOMAIN, "stop_tracking", handle_stop_tracking)
    hass.services.async_register(DOMAIN, "list_tasks", handle_list_tasks)
    hass.services.async_register(DOMAIN, "debug_api", handle_debug_api)
    hass.services.async_register(DOMAIN, "test_auth", handle_test_auth)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok