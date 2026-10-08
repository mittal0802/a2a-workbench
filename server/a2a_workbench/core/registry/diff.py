"""Structural differences between two agent cards."""

from typing import Any

_KEYED_LISTS = {"skills": "id", "extensions": "uri", "supportedInterfaces": "url"}
_IGNORED = {"signatures"}


def _walk(path: str, key: str, a: Any, b: Any, out: list[dict[str, Any]]) -> None:
    if a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if k in _IGNORED:
                continue
            child = f"{path}.{k}" if path else k
            if k not in b:
                out.append({"path": child, "change": "removed", "public": a[k], "extended": None})
            elif k not in a:
                out.append({"path": child, "change": "added", "public": None, "extended": b[k]})
            else:
                _walk(child, k, a[k], b[k], out)
        return
    if isinstance(a, list) and isinstance(b, list):
        id_key = _KEYED_LISTS.get(key)
        if id_key and all(isinstance(x, dict) and id_key in x for x in a + b):
            left = {x[id_key]: x for x in a}
            right = {x[id_key]: x for x in b}
            for ident in list(left) + [i for i in right if i not in left]:
                child = f"{path}[{ident}]"
                if ident not in right:
                    out.append(
                        {
                            "path": child,
                            "change": "removed",
                            "public": left[ident],
                            "extended": None,
                        }
                    )
                elif ident not in left:
                    out.append(
                        {"path": child, "change": "added", "public": None, "extended": right[ident]}
                    )
                else:
                    _walk(child, "", left[ident], right[ident], out)
            return
        for i in range(max(len(a), len(b))):
            child = f"{path}[{i}]"
            if i >= len(b):
                out.append({"path": child, "change": "removed", "public": a[i], "extended": None})
            elif i >= len(a):
                out.append({"path": child, "change": "added", "public": None, "extended": b[i]})
            else:
                _walk(child, "", a[i], b[i], out)
        return
    out.append({"path": path, "change": "changed", "public": a, "extended": b})


def card_diff(public: dict[str, Any], extended: dict[str, Any]) -> list[dict[str, Any]]:
    """List what the extended card adds, removes or changes relative to the public card.

    Skills, extensions and interfaces are matched by ``id``, ``uri`` and
    ``url``; other lists by position. Signatures are ignored. Each entry is
    ``{"path", "change", "public", "extended"}``.
    """
    out: list[dict[str, Any]] = []
    _walk("", "", public, extended, out)
    return out
