import logging
from datetime import datetime
from typing import Any, Dict

from homeassistant.components.sensor import SensorEntity
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
    """Set up Timeflip sensor."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([TimeflipTrackingSensor(coordinator)])


class TimeflipTrackingSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing current tracking status."""

    def __init__(self, coordinator: TimeflipDataCoordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Timeflip Current Task"
        self._attr_unique_id = "timeflip_current_task"
        self._attr_icon = "mdi:cube-outline"

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        sync_data = self.coordinator.data.get("sync_data", {})
        intervals = sync_data.get("timeIntervals", [])
        tasks = self.coordinator.data.get("tasks", [])
        
        current_interval = next((i for i in intervals if i.get("duration", 0) == 0), None)
        
        if current_interval:
            task_id = current_interval.get("taskId")
            task = next((t for t in tasks if t.get("id") == task_id), None)
            if task:
                return task.get("name", "Unknown Task")
        
        return "Stopped"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional attributes."""
        sync_data = self.coordinator.data.get("sync_data", {})
        intervals = sync_data.get("timeIntervals", [])
        
        current_interval = next((i for i in intervals if i.get("duration", 0) == 0), None)
        
        if not current_interval:
            return {"status": "stopped"}
        
        started_at = current_interval.get("startedAt", "")
        duration_seconds = 0
        
        if started_at:
            try:
                started = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                duration_seconds = int((datetime.utcnow() - started).total_seconds())
            except:
                pass
        
        return {
            "status": "tracking",
            "task_id": current_interval.get("taskId"),
            "started_at": started_at,
            "duration_seconds": duration_seconds,
            "duration_formatted": f"{duration_seconds // 3600:02d}:{(duration_seconds % 3600) // 60:02d}:{duration_seconds % 60:02d}"
        }