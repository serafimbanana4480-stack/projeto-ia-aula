"""Tools exposed to agents via ReAct actions. See ARCHITECTURE.md §5.2."""

from backend.tools import code_executor as _code_executor  # noqa: F401
from backend.tools import file_ops as _file_ops  # noqa: F401
from backend.tools import web_search as _web_search  # noqa: F401
