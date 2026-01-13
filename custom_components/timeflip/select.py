import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TimeflipDataCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Timeflip select."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    async_add_entities([TimeflipTaskSelect(coordinator, api)])


class TimeflipTaskSelect(CoordinatorEntity, SelectEntity):
    """Select entity to choose and start tasks."""

    def __init__(self, coordinator: TimeflipDataCoordinator, api):
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._api = api
        self._attr_name = "Timeflip Task Selector"
        self._attr_unique_id = "timeflip_task_selector"
        self._attr_icon = "mdi:cube"

    @property
    def options(self) -> list[str]:
        """Return available options."""
        tasks = self.coordinator.data.get("tasks", [])
        options = ["Stop Tracking"]
        sorted_tasks = sorted(tasks, key=lambda t: t.get("sideIndex", 999))
        options.extend([
            f"{task.get('name', 'Unknown')} (Seite {task.get('sideIndex', '?')})" 
            for task in sorted_tasks
        ])
        return options

    @property
    def current_option(self) -> str:
        """Return current selected option."""
        sync_data = self.coordinator.data.get("sync_data", {})
        intervals = sync_data.get("timeIntervals", [])
        tasks = self.coordinator.data.get("tasks", [])
        
        current_interval = next((i for i in intervals if i.get("duration", 0) == 0), None)
        
        if current_interval:
            task_id = current_interval.get("taskId")
            task = next((t for t in tasks if t.get("id") == task_id), None)
            if task:
                return f"{task.get('name', 'Unknown')} (Seite {task.get('sideIndex', '?')})"
        
        return "Stop Tracking"

    async def async_select_option(self, option: str) -> None:
        """Handle option selection."""
        if option == "Stop Tracking":
            sync_data = self.coordinator.data.get("sync_data", {})
            intervals = sync_data.get("timeIntervals", [])
            current = next((i for i in intervals if i.get("duration", 0) == 0), None)
            if current:
                await self._api.stop_tracking(current)
        else:
            tasks = self.coordinator.data.get("tasks", [])
            task_name = option.rsplit(" (Seite", 1)[0]
            for task in tasks:
                if task.get("name") == task_name:
                    await self._api.start_task(task.get("id"))
                    break
        
        await self.coordinator.async_request_refresh()