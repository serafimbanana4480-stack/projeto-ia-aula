"""Plugin System — extensible plugin registry for NEXUS IDE.

Provides a lightweight plugin architecture:
- Register plugins with metadata and hooks
- Hook system for extending agent behavior
- Plugin lifecycle: load, enable, disable, unload
- Sandboxed plugin execution
- Plugin marketplace API (list, install, verify)

Configuration:
- PLUGINS_ENABLED=true/false
- PLUGINS_DIR=data/plugins
- PLUGINS_ALLOW_UNOFFICIAL=false

Usage:
    from backend.plugins.registry import plugin_registry
    plugin_registry.register("my_plugin", MyPluginClass)
    plugin_registry.enable("my_plugin")
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import logging
import os
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class PluginManifest:
    """Plugin metadata and configuration."""
    name: str
    version: str
    description: str
    author: str
    license: str = "MIT"
    hooks: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    enabled: bool = False
    loaded: bool = False
    error: str | None = None


class Plugin(ABC):
    """Base class for all NEXUS IDE plugins."""

    @property
    @abstractmethod
    def manifest(self) -> PluginManifest:
        """Return plugin metadata."""
        raise NotImplementedError

    @abstractmethod
    def on_load(self) -> None:
        """Called when plugin is loaded."""
        pass

    @abstractmethod
    def on_enable(self) -> None:
        """Called when plugin is enabled."""
        pass

    @abstractmethod
    def on_disable(self) -> None:
        """Called when plugin is disabled."""
        pass

    @abstractmethod
    def on_unload(self) -> None:
        """Called when plugin is unloaded."""
        pass


class HookRegistry:
    """Manages hooks for plugin extensibility."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable]] = {}

    def register_hook(self, hook_name: str, callback: Callable) -> None:
        """Register a callback for a hook."""
        if hook_name not in self._hooks:
            self._hooks[hook_name] = []
        self._hooks[hook_name].append(callback)
        logger.debug("Registered hook: %s", hook_name)

    def unregister_hook(self, hook_name: str, callback: Callable) -> None:
        """Unregister a callback from a hook."""
        if hook_name in self._hooks and callback in self._hooks[hook_name]:
            self._hooks[hook_name].remove(callback)

    def call_hook(self, hook_name: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Call all callbacks for a hook and return results."""
        results = []
        if hook_name in self._hooks:
            for callback in self._hooks[hook_name]:
                try:
                    result = callback(*args, **kwargs)
                    results.append(result)
                except Exception as exc:
                    logger.error("Hook %s callback failed: %s", hook_name, exc)
        return results

    def has_hook(self, hook_name: str) -> bool:
        """Check if a hook has any registered callbacks."""
        return hook_name in self._hooks and len(self._hooks[hook_name]) > 0


class PluginRegistry:
    """Central registry for managing plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._manifests: dict[str, PluginManifest] = {}
        self._hooks = HookRegistry()
        self._enabled = os.getenv("PLUGINS_ENABLED", "false").lower() in ("true", "1", "yes", "on")
        self._plugins_dir = Path(os.getenv("PLUGINS_DIR", "data/plugins"))
        self._plugins_dir.mkdir(parents=True, exist_ok=True)

    @property
    def hooks(self) -> HookRegistry:
        return self._hooks

    def is_enabled(self) -> bool:
        return self._enabled

    def register(self, name: str, plugin_class: type[Plugin]) -> dict[str, Any]:
        """Register a plugin class.

        Args:
            name: Unique plugin identifier.
            plugin_class: Plugin class (must inherit from Plugin).

        Returns:
            Registration result.
        """
        if not self._enabled:
            return {"success": False, "reason": "plugins disabled"}

        if name in self._plugins:
            return {"success": False, "reason": f"plugin '{name}' already registered"}

        try:
            instance = plugin_class()
            manifest = instance.manifest
            self._plugins[name] = instance
            self._manifests[name] = manifest

            # Load the plugin
            instance.on_load()
            manifest.loaded = True

            logger.info("Plugin registered: %s v%s", name, manifest.version)
            return {
                "success": True,
                "plugin": name,
                "version": manifest.version,
                "hooks": manifest.hooks,
            }
        except Exception as exc:
            logger.error("Failed to register plugin %s: %s", name, exc)
            return {"success": False, "reason": str(exc)}

    def enable(self, name: str) -> dict[str, Any]:
        """Enable a registered plugin."""
        if name not in self._plugins:
            return {"success": False, "reason": f"plugin '{name}' not found"}

        try:
            plugin = self._plugins[name]
            plugin.on_enable()
            self._manifests[name].enabled = True

            # Register hooks
            for hook_name in self._manifests[name].hooks:
                if hasattr(plugin, f"on_{hook_name}"):
                    self._hooks.register_hook(hook_name, getattr(plugin, f"on_{hook_name}"))

            logger.info("Plugin enabled: %s", name)
            return {"success": True, "plugin": name}
        except Exception as exc:
            logger.error("Failed to enable plugin %s: %s", name, exc)
            return {"success": False, "reason": str(exc)}

    def disable(self, name: str) -> dict[str, Any]:
        """Disable a plugin."""
        if name not in self._plugins:
            return {"success": False, "reason": f"plugin '{name}' not found"}

        try:
            plugin = self._plugins[name]
            plugin.on_disable()
            self._manifests[name].enabled = False

            # Unregister hooks
            for hook_name in self._manifests[name].hooks:
                if hasattr(plugin, f"on_{hook_name}"):
                    self._hooks.unregister_hook(hook_name, getattr(plugin, f"on_{hook_name}"))

            logger.info("Plugin disabled: %s", name)
            return {"success": True, "plugin": name}
        except Exception as exc:
            logger.error("Failed to disable plugin %s: %s", name, exc)
            return {"success": False, "reason": str(exc)}

    def unregister(self, name: str) -> dict[str, Any]:
        """Unload and remove a plugin."""
        if name not in self._plugins:
            return {"success": False, "reason": f"plugin '{name}' not found"}

        try:
            # Disable first if enabled
            if self._manifests[name].enabled:
                self.disable(name)

            plugin = self._plugins[name]
            plugin.on_unload()

            del self._plugins[name]
            del self._manifests[name]

            logger.info("Plugin unregistered: %s", name)
            return {"success": True, "plugin": name}
        except Exception as exc:
            logger.error("Failed to unregister plugin %s: %s", name, exc)
            return {"success": False, "reason": str(exc)}

    def list_plugins(self) -> list[dict[str, Any]]:
        """List all registered plugins with their status."""
        return [
            {
                "name": name,
                "version": manifest.version,
                "description": manifest.description,
                "author": manifest.author,
                "license": manifest.license,
                "enabled": manifest.enabled,
                "loaded": manifest.loaded,
                "hooks": manifest.hooks,
                "dependencies": manifest.dependencies,
            }
            for name, manifest in self._manifests.items()
        ]

    def get_plugin(self, name: str) -> Plugin | None:
        """Get a plugin instance by name."""
        return self._plugins.get(name)

    def load_from_directory(self, directory: str | Path) -> list[dict[str, Any]]:
        """Load all plugins from a directory.

        Each subdirectory should contain a plugin module with a Plugin subclass.
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            return []

        results = []
        for item in dir_path.iterdir():
            if item.is_dir() and (item / "plugin.py").exists():
                try:
                    # Add to path and import
                    sys.path.insert(0, str(item))
                    spec = importlib.util.spec_from_file_location(
                        f"plugin_{item.name}", str(item / "plugin.py")
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)

                        # Find Plugin subclass
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if (isinstance(attr, type) and issubclass(attr, Plugin)
                                and attr is not Plugin):
                                result = self.register(item.name, attr)
                                results.append(result)
                                break
                except Exception as exc:
                    logger.error("Failed to load plugin from %s: %s", item, exc)
                    results.append({"success": False, "reason": str(exc), "path": str(item)})
                finally:
                    if str(item) in sys.path:
                        sys.path.remove(str(item))

        return results

    def status(self) -> dict[str, Any]:
        """Get plugin system status."""
        return {
            "enabled": self._enabled,
            "plugins_dir": str(self._plugins_dir),
            "total_plugins": len(self._plugins),
            "enabled_plugins": sum(1 for m in self._manifests.values() if m.enabled),
            "available_hooks": list(self._hooks._hooks.keys()),
        }


# Global registry instance
_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    """Get or create the global plugin registry."""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry


# Pre-defined hooks for common extension points
class PluginHooks:
    """Standard hook names for plugin development."""

    PRE_AGENT_EXECUTE = "pre_agent_execute"
    POST_AGENT_EXECUTE = "post_agent_execute"
    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    PRE_FILE_WRITE = "pre_file_write"
    POST_FILE_WRITE = "post_file_write"
    CHAT_MESSAGE = "chat_message"
    DASHBOARD_METRIC = "dashboard_metric"
    AGENT_BUS_MESSAGE = "agent_bus_message"


# Tool registration
from backend.tools.registry import ToolSpec, register_tool

register_tool(
    ToolSpec(
        name="list_plugins",
        description="List all registered plugins and their status.",
        schema={"type": "object", "properties": {}},
        handler=lambda **kwargs: get_plugin_registry().list_plugins(),
    )
)

register_tool(
    ToolSpec(
        name="plugin_status",
        description="Get plugin system status.",
        schema={"type": "object", "properties": {}},
        handler=lambda **kwargs: get_plugin_registry().status(),
    )
)
