from typing import Any, Dict, Tuple
from backend.runner.utils import job_io

# --- Public API ---
def plan_single_file(job_id: str) -> Dict[str, Any]:
    deps = job_io.load(job_id, "dependency")
    if not isinstance(deps, dict):
        raise ValueError("dependency.json is missing or not a JSON object")

    candidate, reason = _pick_candidate(deps)
    unused_imports = list((deps.get("unused_imports") or {}).get(candidate, []))
    if not unused_imports:
        raise ValueError(f"No unused imports found for candidate module '{candidate}'")

    return {
        "candidate": candidate,
        "unused_imports": unused_imports,
        "reason": reason,
    }

# --- Internal helpers ---
def _pick_candidate(deps: Dict[str, Any]) -> Tuple[str, str]:
    unused = deps.get("unused_imports") or {}
    if not unused:
        raise ValueError("No modules have unused imports; nothing to plan.")
    candidates = set(unused.keys())

    deg: Dict[str, int] = {}
    for a, b in deps.get("edges", []):
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1

    topo_pos = {m: i for i, m in enumerate(deps.get("topo_order", []))}

    ordered = sorted(
        candidates,
        key=lambda m: (deg.get(m, 0), topo_pos.get(m, 10**9), m)
    )
    candidate = ordered[0]

    reason = (
        f"Selected '{candidate}' because it contains unused imports "
        f"and appears low-impact (dependency degree={deg.get(candidate, 0)}). "
        + ("Topo order was considered for tie-breaking. " if candidate in topo_pos else "")
    )

    return candidate, reason