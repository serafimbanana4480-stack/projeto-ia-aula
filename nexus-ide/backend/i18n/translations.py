"""
NEXUS IDE — Internationalization (i18n) System

Sistema de traduções com suporte para Português (PT), Inglês (EN) e Espanhol (ES).
Suporta interpolação de variáveis, pluralização e fallback para o idioma padrão.

Usage:
    from backend.i18n.translations import I18n, t

    i18n = I18n(locale="pt")
    message = i18n.t("welcome", name="Rodri")
    # → "Bem-vindo, Rodri!"

    # Ou usar o helper global (assume locale atual do request/context):
    t("errors.not_found")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Idiomas suportados ──────────────────────────────────────

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = {"pt", "en", "es"}


# ── Dicionário de traduções ─────────────────────────────────

_TRANSLATIONS: dict[str, dict[str, Any]] = {
    "en": {
        # Geral
        "welcome": "Welcome, {name}!",
        "hello": "Hello",
        "goodbye": "Goodbye",
        "save": "Save",
        "cancel": "Cancel",
        "delete": "Delete",
        "edit": "Edit",
        "create": "Create",
        "search": "Search",
        "loading": "Loading...",
        "success": "Success",
        "error": "Error",
        "warning": "Warning",
        "info": "Info",
        "close": "Close",
        "confirm": "Confirm",
        "back": "Back",
        "next": "Next",
        "done": "Done",
        # Dashboard
        "dashboard.title": "Dashboard",
        "dashboard.projects": "Projects",
        "dashboard.agents": "Agents",
        "dashboard.models": "Models",
        "dashboard.recent_activity": "Recent Activity",
        "dashboard.no_activity": "No recent activity",
        # Editor
        "editor.untitled": "Untitled",
        "editor.changes_saved": "Changes saved",
        "editor.discard_changes": "Discard changes?",
        "editor.find": "Find",
        "editor.replace": "Replace",
        "editor.go_to_line": "Go to line",
        "editor.format_document": "Format Document",
        # AI
        "ai.generating": "Generating...",
        "ai.suggestion_ready": "Suggestion ready",
        "ai.explain_code": "Explain Code",
        "ai.fix_code": "Fix Code",
        "ai.generate_tests": "Generate Tests",
        # Errors
        "errors.not_found": "Resource not found",
        "errors.unauthorized": "Unauthorized",
        "errors.forbidden": "Access denied",
        "errors.validation": "Validation error",
        "errors.server_error": "Internal server error",
        "errors.timeout": "Request timeout",
        "errors.connection_lost": "Connection lost",
        # Plugins
        "plugins.installed": "Installed Plugins",
        "plugins.no_plugins": "No plugins installed",
        "plugins.enable": "Enable",
        "plugins.disable": "Disable",
        "plugins.configure": "Configure",
        # Plural forms
        "files.count": "{count} file|{count} files",
        "projects.count": "{count} project|{count} projects",
        "agents.count": "{count} agent|{count} agents",
    },
    "pt": {
        # Geral
        "welcome": "Bem-vindo, {name}!",
        "hello": "Olá",
        "goodbye": "Adeus",
        "save": "Guardar",
        "cancel": "Cancelar",
        "delete": "Eliminar",
        "edit": "Editar",
        "create": "Criar",
        "search": "Pesquisar",
        "loading": "A carregar...",
        "success": "Sucesso",
        "error": "Erro",
        "warning": "Aviso",
        "info": "Informação",
        "close": "Fechar",
        "confirm": "Confirmar",
        "back": "Voltar",
        "next": "Seguinte",
        "done": "Concluído",
        # Dashboard
        "dashboard.title": "Painel",
        "dashboard.projects": "Projetos",
        "dashboard.agents": "Agentes",
        "dashboard.models": "Modelos",
        "dashboard.recent_activity": "Atividade Recente",
        "dashboard.no_activity": "Sem atividade recente",
        # Editor
        "editor.untitled": "Sem título",
        "editor.changes_saved": "Alterações guardadas",
        "editor.discard_changes": "Descartar alterações?",
        "editor.find": "Procurar",
        "editor.replace": "Substituir",
        "editor.go_to_line": "Ir para a linha",
        "editor.format_document": "Formatar Documento",
        # AI
        "ai.generating": "A gerar...",
        "ai.suggestion_ready": "Sugestão pronta",
        "ai.explain_code": "Explicar Código",
        "ai.fix_code": "Corrigir Código",
        "ai.generate_tests": "Gerar Testes",
        # Errors
        "errors.not_found": "Recurso não encontrado",
        "errors.unauthorized": "Não autorizado",
        "errors.forbidden": "Acesso negado",
        "errors.validation": "Erro de validação",
        "errors.server_error": "Erro interno do servidor",
        "errors.timeout": "Tempo de pedido esgotado",
        "errors.connection_lost": "Ligação perdida",
        # Plugins
        "plugins.installed": "Plugins Instalados",
        "plugins.no_plugins": "Nenhum plugin instalado",
        "plugins.enable": "Ativar",
        "plugins.disable": "Desativar",
        "plugins.configure": "Configurar",
        # Plural forms
        "files.count": "{count} ficheiro|{count} ficheiros",
        "projects.count": "{count} projeto|{count} projetos",
        "agents.count": "{count} agente|{count} agentes",
    },
    "es": {
        # Geral
        "welcome": "¡Bienvenido, {name}!",
        "hello": "Hola",
        "goodbye": "Adiós",
        "save": "Guardar",
        "cancel": "Cancelar",
        "delete": "Eliminar",
        "edit": "Editar",
        "create": "Crear",
        "search": "Buscar",
        "loading": "Cargando...",
        "success": "Éxito",
        "error": "Error",
        "warning": "Advertencia",
        "info": "Información",
        "close": "Cerrar",
        "confirm": "Confirmar",
        "back": "Atrás",
        "next": "Siguiente",
        "done": "Hecho",
        # Dashboard
        "dashboard.title": "Panel",
        "dashboard.projects": "Proyectos",
        "dashboard.agents": "Agentes",
        "dashboard.models": "Modelos",
        "dashboard.recent_activity": "Actividad Reciente",
        "dashboard.no_activity": "Sin actividad reciente",
        # Editor
        "editor.untitled": "Sin título",
        "editor.changes_saved": "Cambios guardados",
        "editor.discard_changes": "¿Descartar cambios?",
        "editor.find": "Buscar",
        "editor.replace": "Reemplazar",
        "editor.go_to_line": "Ir a la línea",
        "editor.format_document": "Formatear Documento",
        # AI
        "ai.generating": "Generando...",
        "ai.suggestion_ready": "Sugerencia lista",
        "ai.explain_code": "Explicar Código",
        "ai.fix_code": "Corregir Código",
        "ai.generate_tests": "Generar Tests",
        # Errors
        "errors.not_found": "Recurso no encontrado",
        "errors.unauthorized": "No autorizado",
        "errors.forbidden": "Acceso denegado",
        "errors.validation": "Error de validación",
        "errors.server_error": "Error interno del servidor",
        "errors.timeout": "Tiempo de solicitud agotado",
        "errors.connection_lost": "Conexión perdida",
        # Plugins
        "plugins.installed": "Plugins Instalados",
        "plugins.no_plugins": "Ningún plugin instalado",
        "plugins.enable": "Activar",
        "plugins.disable": "Desactivar",
        "plugins.configure": "Configurar",
        # Plural forms
        "files.count": "{count} archivo|{count} archivos",
        "projects.count": "{count} proyecto|{count} proyectos",
        "agents.count": "{count} agente|{count} agentes",
    },
}


# ── I18n Engine ─────────────────────────────────────────────


class I18n:
    """
    Motor de internacionalização com fallback e pluralização.
    """

    def __init__(
        self,
        locale: str = DEFAULT_LOCALE,
        fallback_locale: str = DEFAULT_LOCALE,
        custom_translations: dict[str, dict[str, Any]] | None = None,
    ):
        self.locale = locale.lower() if locale.lower() in SUPPORTED_LOCALES else fallback_locale
        self.fallback_locale = fallback_locale
        self._translations = {**_TRANSLATIONS}
        if custom_translations:
            for loc, msgs in custom_translations.items():
                self._translations.setdefault(loc, {}).update(msgs)

    def set_locale(self, locale: str) -> None:
        """Altera o locale atual."""
        if locale.lower() not in SUPPORTED_LOCALES:
            logger.warning("Locale '%s' not supported; keeping '%s'", locale, self.locale)
            return
        self.locale = locale.lower()

    def t(self, key: str, **kwargs: Any) -> str:
        """
        Traduz uma chave, com interpolação de variáveis e pluralização.

        Plural: use pipe-separated values na tradução:
            "files.count": "{count} file|{count} files"

        E passe `count` como kwarg:
            i18n.t("files.count", count=5)  # → "5 files"
        """
        message = self._resolve(key)

        # Plural handling
        if "count" in kwargs and "|" in message:
            singular, plural = message.split("|", 1)
            message = singular if kwargs["count"] == 1 else plural

        # Variable interpolation: {name}
        try:
            return message.format(**kwargs)
        except KeyError as exc:
            logger.warning("Missing translation variable %s for key '%s'", exc, key)
            return message
        except Exception:
            return message

    def _resolve(self, key: str) -> str:
        """Resolve chave procurando no locale atual e no fallback."""
        for loc in (self.locale, self.fallback_locale):
            if loc in self._translations and key in self._translations[loc]:
                return self._translations[loc][key]
        # Último fallback: retorna a própria chave
        logger.debug("Translation key not found: '%s'", key)
        return key

    def has(self, key: str) -> bool:
        """Verifica se uma chave existe no locale atual ou fallback."""
        for loc in (self.locale, self.fallback_locale):
            if loc in self._translations and key in self._translations[loc]:
                return True
        return False

    def add_translation(self, locale: str, key: str, value: str) -> None:
        """Adiciona uma tradução dinamicamente."""
        self._translations.setdefault(locale, {})[key] = value
        SUPPORTED_LOCALES.add(locale)

    def list_keys(self, locale: str | None = None) -> list[str]:
        """Lista todas as chaves disponíveis para um locale."""
        loc = locale or self.locale
        return list(self._translations.get(loc, {}).keys())

    def missing_keys(self, locale: str, reference_locale: str | None = None) -> list[str]:
        """Retorna chaves que existem no locale de referência mas não no target."""
        ref = reference_locale or self.fallback_locale
        ref_keys = set(self._translations.get(ref, {}).keys())
        loc_keys = set(self._translations.get(locale, {}).keys())
        return sorted(ref_keys - loc_keys)


# ── Context-local helper ────────────────────────────────────

# Usado para manter o locale atual num contexto (ex: FastAPI request)
_thread_local_locale: str = DEFAULT_LOCALE


def set_thread_locale(locale: str) -> None:
    """Define o locale para o contexto atual (thread-local)."""
    global _thread_local_locale
    _thread_local_locale = locale.lower() if locale.lower() in SUPPORTED_LOCALES else DEFAULT_LOCALE


def get_thread_locale() -> str:
    """Obtém o locale do contexto atual."""
    return _thread_local_locale


def t(key: str, **kwargs: Any) -> str:
    """
    Helper global que usa o locale do contexto atual.

    Usage:
        t("welcome", name="Rodri")
    """
    i18n = I18n(locale=_thread_local_locale)
    return i18n.t(key, **kwargs)


# ── FastAPI Integration (opcional) ──────────────────────────

try:
    from fastapi import APIRouter, Header, Request
    from fastapi.responses import JSONResponse

    i18n_router = APIRouter(prefix="/i18n", tags=["i18n"])

    @i18n_router.get("/translate/{key}")
    async def translate_key(
        key: str,
        accept_language: str | None = Header(default=None),
    ) -> dict[str, str]:
        locale = (accept_language or DEFAULT_LOCALE).split(",")[0].split("-")[0].lower()
        i18n = I18n(locale=locale)
        return {"key": key, "locale": i18n.locale, "translation": i18n.t(key)}

    @i18n_router.get("/locales")
    async def list_locales() -> dict[str, Any]:
        return {
            "supported": sorted(SUPPORTED_LOCALES),
            "default": DEFAULT_LOCALE,
        }

    @i18n_router.get("/keys")
    async def list_translation_keys(locale: str = DEFAULT_LOCALE) -> dict[str, Any]:
        i18n = I18n(locale=locale)
        return {"locale": i18n.locale, "keys": i18n.list_keys()}

except ImportError:
    i18n_router = None  # type: ignore


# ── Demo ────────────────────────────────────────────────────

if __name__ == "__main__":
    for loc in ("pt", "en", "es"):
        i18n = I18n(locale=loc)
        print(f"\n=== {loc.upper()} ===")
        print(i18n.t("welcome", name="Nexus"))
        print(i18n.t("dashboard.title"))
        print(i18n.t("files.count", count=1))
        print(i18n.t("files.count", count=5))
        print(i18n.t("errors.not_found"))
        print(i18n.t("ai.generating"))
