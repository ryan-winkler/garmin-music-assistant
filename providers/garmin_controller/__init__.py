"""Garmin Connect IQ Controller Plugin Provider for Music Assistant."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .domain import (
    CONF_PREFERRED_PLAYER,
    CONF_SETTLE_TIMEOUT_MS,
    DEFAULT_SETTLE_TIMEOUT_MS,
    MAX_SETTLE_TIMEOUT_MS,
    MIN_SETTLE_TIMEOUT_MS,
)
from .routes import GarminApiHandler

try:
    from music_assistant.models.plugin import PluginProvider as _PluginProviderBase
    from music_assistant_models.config_entries import ConfigEntry
    from music_assistant_models.enums import ConfigEntryType
except ImportError:  # pragma: no cover - allows standalone unit testing without full MA server
    _PluginProviderBase = object
    ConfigEntry = Any
    ConfigEntryType = Any

if TYPE_CHECKING:
    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType
    from music_assistant_models.config_entries import ConfigValueType, ProviderConfig
    from music_assistant_models.provider import ProviderManifest

SUPPORTED_FEATURES: set[Any] = set()


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize Garmin Connect IQ Controller plugin instance."""
    return GarminControllerPlugin(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: MusicAssistant,  # noqa: ARG001
    instance_id: str | None = None,  # noqa: ARG001
    action: str | None = None,  # noqa: ARG001
    values: dict[str, ConfigValueType] | None = None,  # noqa: ARG001
) -> tuple[ConfigEntry, ...]:
    """Return configuration entries for the Garmin Connect IQ Controller plugin."""
    return (
        ConfigEntry(
            key=CONF_SETTLE_TIMEOUT_MS,
            type=ConfigEntryType.INTEGER,
            label="Action state settle timeout (ms)",
            default_value=DEFAULT_SETTLE_TIMEOUT_MS,
            range=(MIN_SETTLE_TIMEOUT_MS, MAX_SETTLE_TIMEOUT_MS),
            required=False,
        ),
        ConfigEntry(
            key=CONF_PREFERRED_PLAYER,
            type=ConfigEntryType.STRING,
            label="Preferred player (optional)",
            default_value="",
            required=False,
        ),
    )


class GarminControllerPlugin(_PluginProviderBase):
    """Music Assistant plugin exposing a compact, watch-safe REST API for Garmin Connect IQ."""

    logger: logging.Logger

    def __init__(
        self,
        mass: Any,
        manifest: Any,
        config: Any,
        supported_features: set[Any] | None = None,
    ) -> None:
        """Initialize the plugin provider."""
        if _PluginProviderBase is not object:
            super().__init__(mass, manifest, config, supported_features or SUPPORTED_FEATURES)
        else:
            self.mass = mass
            self.manifest = manifest
            self.config = config
            self.logger = getattr(mass, "logger", logging.getLogger(__name__))
        self._registered_routes: list[tuple[str, str]] = []
        self._api_handler: GarminApiHandler | None = None

    def _read_config_raw(self, key: str) -> Any:
        """Read a raw config value safely across plugin upgrades."""
        try:
            return (
                self.config.get_value(key)
                if hasattr(self.config, "get_value")
                else self.config.get(key)
            )
        except KeyError:
            return None

    def _read_config_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        """Read and clamp an integer config value safely."""
        raw = self._read_config_raw(key)
        if raw is None:
            return default
        try:
            return max(minimum, min(maximum, int(raw)))
        except (TypeError, ValueError):
            return default

    def _read_config_str(self, key: str, default: str = "") -> str:
        """Read a string config value safely."""
        raw = self._read_config_raw(key)
        return str(raw).strip() if raw is not None else default

    async def loaded_in_mass(self) -> None:
        """Register compact Garmin API routes transactionally on Music Assistant's webserver."""
        settle_ms = self._read_config_int(
            CONF_SETTLE_TIMEOUT_MS,
            DEFAULT_SETTLE_TIMEOUT_MS,
            MIN_SETTLE_TIMEOUT_MS,
            MAX_SETTLE_TIMEOUT_MS,
        )
        preferred = self._read_config_str(CONF_PREFERRED_PLAYER, "")
        self._api_handler = GarminApiHandler(
            self.mass,
            self.logger,
            settle_timeout_ms=settle_ms,
            preferred_player=preferred,
        )
        registered: list[tuple[str, str]] = []
        try:
            for method, path, handler in self._api_handler.route_definitions():
                self.mass.webserver.register_dynamic_route(path, handler, method)
                registered.append((path, method))
        except Exception:
            for path, method in reversed(registered):
                self.mass.webserver.unregister_dynamic_route(path, method)
            raise
        self._registered_routes = registered
        self.logger.info(
            "Registered %d Garmin Connect IQ API routes (settle_timeout_ms=%d)",
            len(self._registered_routes),
            settle_ms,
        )

    async def unload(self, is_removed: bool = False) -> None:  # noqa: FBT001,FBT002
        """Unregister all dynamic routes cleanly on plugin reload or removal."""
        for path, method in reversed(self._registered_routes):
            self.mass.webserver.unregister_dynamic_route(path, method)
        self._registered_routes.clear()
        self._api_handler = None
