"""
NEXUS IDE — Plugin Registry

Sistema de plugins baseado em hooks e descoberta dinâmica.
Permite que módulos externos registrem comandos, middlewares e hooks
de lifecycle sem modificar o core da aplicação.

Usage:
    from backend.plugins.registry import plugin_registry, hook

    @plugin_registry.register_command("/format")
    def format_code(ctx, source: str) -> str:
        ...

    @hook("pre_save")
    def my_pre_save_hook(file_path: str, content: str):
        ...
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
HookCallback = Callable[..., Any]
CommandHandler = Callable[..., Any]


class PluginProtocol(Protocol):
    """Protocolo que todo plugin deve implementar."""

    name: str
    version: str
    description: str

    def setup(self, registry: PluginRegistry) -> None:
        ...


@dataclass
class PluginMeta:
    """Metadados de um plugin carregado."""

    name: str
    version: str
    description: str
    module_path: str
    enabled: bool = True
    commands: List[str] = field(default_factory=list)
    hooks: List[str] = field(default_factory=list)


@dataclass
class RegisteredCommand:
    """Comando registado no sistema."""

    name: str
    handler: CommandHandler
    description: str = ""
    plugin: Optional[str] = None


@dataclass
class RegisteredHook:
    """Hook registado no sistema."""

    event: str
    callback: HookCallback
    priority: int = 0  # maior = executa primeiro
    plugin: Optional[str] = None


class PluginRegistry:
    """
    Registo central de plugins, comandos e hooks.

    É um singleton acessível via `plugin_registry` no módulo.
    """

    _instance: Optional["PluginRegistry"] = None

    def __new__(cls) -> "PluginRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._commands: Dict[str, RegisteredCommand] = {}
        self._hooks: Dict[str, List[RegisteredHook]] = {}
        self._plugins: Dict[str, PluginMeta] = {}
        self._middlewares: List[Callable] = []
        self._initialized = True

    # ── Comandos ──────────────────────────────────────────────

    def register_command(
        self,
        name: str,
        description: str = "",
        plugin: Optional[str] = None,
    ) -> Callable[[CommandHandler], CommandHandler]:
        """Decorador para registar um comando."""

        def decorator(handler: CommandHandler) -> CommandHandler:
            if name in self._commands:
                logger.warning("Command '%s' already registered; overwriting.", name)
            self._commands[name] = RegisteredCommand(
                name=name,
                handler=handler,
                description=description,
                plugin=plugin,
            )
            if plugin:
                self._plugins[plugin].commands.append(name)
            logger.info("Registered command: %s", name)
            return handler

        return decorator

    def execute_command(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Executa um comando registado."""
        cmd = self._commands.get(name)
        if not cmd:
            raise KeyError(f"Command '{name}' not found.")
        return cmd.handler(*args, **kwargs)

    def list_commands(self) -> List[RegisteredCommand]:
        """Lista todos os comandos registados."""
        return list(self._commands.values())

    # ── Hooks ─────────────────────────────────────────────────

    def register_hook(
        self,
        event: str,
        callback: HookCallback,
        priority: int = 0,
        plugin: Optional[str] = None,
    ) -> RegisteredHook:
        """Regista um hook para um evento."""
        hook = RegisteredHook(
            event=event,
            callback=callback,
            priority=priority,
            plugin=plugin,
        )
        self._hooks.setdefault(event, []).append(hook)
        self._hooks[event].sort(key=lambda h: h.priority, reverse=True)
        if plugin:
            self._plugins[plugin].hooks.append(event)
        logger.info("Registered hook '%s' for event '%s'", callback.__name__, event)
        return hook

    def trigger(self, event: str, *args: Any, **kwargs: Any) -> List[Any]:
        """
        Dispara todos os hooks de um evento.
        Retorna lista de resultados de cada hook.
        """
        results: List[Any] = []
        for hook in self._hooks.get(event, []):
            try:
                result = hook.callback(*args, **kwargs)
                results.append(result)
            except Exception as exc:
                logger.exception("Hook '%s' failed for event '%s'", hook.callback.__name__, event)
                results.append(exc)
        return results

    def trigger_first(self, event: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispara hooks até um retornar um valor truthy.
        Útil para middlewares de autorização/validação.
        """
        for hook in self._hooks.get(event, []):
            try:
                result = hook.callback(*args, **kwargs)
                if result:
                    return result
            except Exception:
                logger.exception("Hook '%s' failed for event '%s'", hook.callback.__name__, event)
        return None

    def list_hooks(self, event: Optional[str] = None) -> List[RegisteredHook]:
        """Lista hooks registados."""
        if event:
            return list(self._hooks.get(event, []))
        return [h for hooks in self._hooks.values() for h in hooks]

    # ── Middleware ────────────────────────────────────────────

    def add_middleware(self, mw: Callable) -> None:
        """Adiciona middleware ao pipeline."""
        self._middlewares.append(mw)

    def run_middlewares(self, context: Any) -> Any:
        """Executa pipeline de middlewares."""
        for mw in self._middlewares:
            context = mw(context)
        return context

    # ── Plugins ───────────────────────────────────────────────

    def load_plugin(self, module_path: str) -> PluginMeta:
        """
        Carrega um plugin a partir de um module path.
        O módulo deve expor `name`, `version`, `description` e `setup(registry)`.
        """
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            raise ImportError(f"Cannot import plugin '{module_path}': {exc}")

        name = getattr(module, "name", module_path)
        version = getattr(module, "version", "0.0.0")
        description = getattr(module, "description", "")
        setup_fn = getattr(module, "setup", None)

        meta = PluginMeta(
            name=name,
            version=version,
            description=description,
            module_path=module_path,
        )
        self._plugins[name] = meta

        if setup_fn and callable(setup_fn):
            setup_fn(self)

        logger.info("Loaded plugin: %s v%s", name, version)
        return meta

    def load_plugins_from_directory(self, directory: Path | str) -> List[PluginMeta]:
        """
        Descobre e carrega todos os plugins num diretório.
        Cada subdiretório ou ficheiro .py é tentado como plugin.
        """
        directory = Path(directory)
        loaded: List[PluginMeta] = []

        if not directory.exists():
            logger.warning("Plugin directory not found: %s", directory)
            return loaded

        for item in directory.iterdir():
            if item.is_dir() and (item / "__init__.py").exists():
                # package: backend.plugins.nome_do_plugin
                module_name = f"{directory.name}.{item.name}"
                try:
                    loaded.append(self.load_plugin(module_name))
                except Exception as exc:
                    logger.error("Failed to load plugin '%s': %s", module_name, exc)
            elif item.is_file() and item.suffix == ".py" and item.stem != "__init__":
                # single file module
                spec = importlib.util.spec_from_file_location(item.stem, item)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    name = getattr(module, "name", item.stem)
                    version = getattr(module, "version", "0.0.0")
                    description = getattr(module, "description", "")
                    setup_fn = getattr(module, "setup", None)
                    meta = PluginMeta(
                        name=name,
                        version=version,
                        description=description,
                        module_path=str(item),
                    )
                    self._plugins[name] = meta
                    if setup_fn and callable(setup_fn):
                        setup_fn(self)
                    loaded.append(meta)

        return loaded

    def list_plugins(self) -> List[PluginMeta]:
        """Lista todos os plugins carregados."""
        return list(self._plugins.values())

    def get_plugin(self, name: str) -> Optional[PluginMeta]:
        """Obtém metadados de um plugin."""
        return self._plugins.get(name)

    def disable_plugin(self, name: str) -> None:
        """Desativa um plugin (soft-disable)."""
        if name in self._plugins:
            self._plugins[name].enabled = False
            logger.info("Disabled plugin: %s", name)

    def enable_plugin(self, name: str) -> None:
        """Reativa um plugin."""
        if name in self._plugins:
            self._plugins[name].enabled = True
            logger.info("Enabled plugin: %s", name)

    # ── Health / Debug ────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        """Retorna estado do registry para health checks."""
        return {
            "plugins_loaded": len(self._plugins),
            "commands_registered": len(self._commands),
            "hooks_registered": sum(len(h) for h in self._hooks.values()),
            "events": list(self._hooks.keys()),
            "plugins": [
                {
                    "name": p.name,
                    "version": p.version,
                    "enabled": p.enabled,
                    "commands": p.commands,
                    "hooks": p.hooks,
                }
                for p in self._plugins.values()
            ],
        }


# Instância singleton global
plugin_registry = PluginRegistry()


# ── Helpers de conveniência ─────────────────────────────────

def hook(event: str, priority: int = 0) -> Callable[[HookCallback], HookCallback]:
    """
    Decorador simplificado para registar hooks na instância global.

    Usage:
        @hook("pre_save", priority=10)
        def validate_before_save(file_path: str, content: str):
            ...
    """

    def decorator(callback: HookCallback) -> HookCallback:
        plugin_registry.register_hook(event, callback, priority=priority)
        return callback

    return decorator


def command(
    name: str, description: str = ""
) -> Callable[[CommandHandler], CommandHandler]:
    """
    Decorador simplificado para registar comandos.

    Usage:
        @command("/lint", description="Run linter on code")
        def lint_code(ctx, source: str) -> str:
            ...
    """
    return plugin_registry.register_command(name, description=description)


# ── Exemplo de plugin inline ────────────────────────────────

if __name__ == "__main__":
    # Demo / smoke test
    @command("/hello", description="Say hello")
    def hello(name: str = "World") -> str:
        return f"Hello, {name}!"

    @hook("startup")
    def on_startup():
        print("Plugin system started!")

    plugin_registry.trigger("startup")
    print(plugin_registry.execute_command("/hello", "Nexus"))
    print(plugin_registry.health())
