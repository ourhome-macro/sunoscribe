from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from app.models.score_revision import ScoreRevision
from app.modules.agents import AgentRevisionContext, ArtifactReference
from app.utils.errors import ValidationAppError


@dataclass(frozen=True, slots=True)
class PluginContext:
    """Read-only context for post-ScoreRevision plugins."""

    revision: ScoreRevision | None = None
    agent_context: AgentRevisionContext | None = None
    artifacts: tuple[ArtifactReference, ...] = field(default_factory=tuple)
    json_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PluginResult:
    plugin_name: str
    status: str
    payload: Any = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


class SunoScribePlugin(Protocol):
    name: str
    kind: str

    def run(self, context: PluginContext) -> PluginResult:
        ...


class CallablePlugin:
    def __init__(self, *, name: str, kind: str, handler: Callable[[PluginContext], Any]) -> None:
        self.name = _normalize_name(name)
        self.kind = str(kind or "plugin").strip() or "plugin"
        self._handler = handler

    def run(self, context: PluginContext) -> PluginResult:
        payload = self._handler(context)
        if isinstance(payload, PluginResult):
            return payload
        return PluginResult(
            plugin_name=self.name,
            status="ok",
            payload=payload,
            warnings=tuple(context.warnings),
        )


class PluginRegistry:
    """Lightweight in-process registry for built-in post-revision plugins."""

    def __init__(self, plugins: list[SunoScribePlugin] | tuple[SunoScribePlugin, ...] | None = None) -> None:
        self._plugins: dict[str, SunoScribePlugin] = {}
        for plugin in plugins or ():
            self.register(plugin)

    def register(self, plugin: SunoScribePlugin) -> None:
        name = _normalize_name(getattr(plugin, "name", ""))
        if not name:
            raise ValidationAppError("plugin name is required")
        if name in self._plugins:
            raise ValidationAppError(f"plugin is already registered: {name}")
        self._plugins[name] = plugin

    def get(self, name: str) -> SunoScribePlugin:
        normalized = _normalize_name(name)
        plugin = self._plugins.get(normalized)
        if plugin is None:
            raise ValidationAppError(f"plugin is not registered: {normalized}")
        return plugin

    def run(self, name: str, context: PluginContext) -> PluginResult:
        return self.get(name).run(context)

    def names(self) -> list[str]:
        return sorted(self._plugins)


def _normalize_name(name: str) -> str:
    return str(name or "").strip().lower().replace("-", "_")
