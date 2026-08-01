"""Optional `jedi` integration for cross-file / semantic questions.

`jedi` is an optional dependency. Every helper here returns ``None`` (or an
empty list) when it is missing or fails, so tools degrade to pure-``ast``
behaviour instead of erroring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["available", "infer_at", "references", "version"]

try:  # pragma: no cover - import shape depends on environment
    import jedi as _jedi
except Exception:  # pragma: no cover
    _jedi = None  # type: ignore[assignment]


def available() -> bool:
    return _jedi is not None


def version() -> str | None:
    return getattr(_jedi, "__version__", None) if _jedi else None


_PROJECTS: dict[str, Any] = {}


def _project(path: str) -> Any | None:
    """Project rooted at the repo, not at the file's own directory.

    ``jedi.get_default_project`` walks up for ``.git`` / ``setup.py`` /
    ``requirements.txt`` and skips ``__init__.py`` package dirs, so references
    resolve across sibling packages instead of only within one folder.
    Cached per root - building a Project indexes sys.path and is not cheap.
    """
    if _jedi is None:
        return None
    try:
        project = _jedi.get_default_project(str(Path(path).parent))
    except Exception:
        return None
    root = str(project._path)
    return _PROJECTS.setdefault(root, project)


def _script(path: str, source: str) -> Any | None:
    if _jedi is None:
        return None
    try:
        return _jedi.Script(code=source, path=path, project=_project(path))
    except Exception:
        return None


def infer_at(path: str, source: str, line: int, column: int) -> list[str]:
    """Human-readable inferred definitions at a cursor position."""
    script = _script(path, source)
    if script is None:
        return []
    out: list[str] = []
    try:
        for name in script.infer(line=line, column=column):
            where = ""
            if name.module_path:
                where = f" [{Path(str(name.module_path)).name}:{name.line}]"
            out.append(f"{name.type} {name.full_name or name.name}{where}")
        for name in script.goto(line=line, column=column, follow_imports=True):
            if name.module_path and str(name.module_path) != str(path):
                out.append(
                    f"defined in {Path(str(name.module_path)).name}:{name.line} "
                    f"as {name.type} {name.name}"
                )
    except Exception:
        return out
    seen: set[str] = set()
    return [x for x in out if not (x in seen or seen.add(x))]


def references(path: str, source: str, line: int, column: int) -> list[str]:
    """Project-wide references, formatted ``file:line:col``."""
    script = _script(path, source)
    if script is None:
        return []
    try:
        refs = script.get_references(line=line, column=column, include_builtins=False)
    except Exception:
        return []
    out: list[str] = []
    for r in refs:
        mod = str(r.module_path) if r.module_path else "<unknown>"
        if mod == str(path):
            continue
        out.append(f"{Path(mod).name}:{r.line}:{r.column}  {r.description.strip()}")
    return out
