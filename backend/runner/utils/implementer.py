from backend.runner.utils import job_io
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import ast, difflib, re, shutil, subprocess, tempfile

# --- Public API ---
def implement_diff(job_id: str, repo_url: str, branch: str) -> Dict[str, Any]:
    plan = job_io.load(job_id, "plan")
    if not isinstance(plan, dict):
        raise ValueError("plan.json is missing or not a JSON object")

    candidate = plan.get("candidate")
    unused_imports: List[str] = list(plan.get("unused_imports") or [])
    if not candidate or not unused_imports:
        raise ValueError("plan.json must include 'candidate' and non-empty 'unused_imports'")

    rel_path = candidate.replace(".", "/") + ".py"
    tmpdir = tempfile.mkdtemp(prefix="implementer-")
    repo_root = Path(tmpdir) / "repo"
    try:
        _shallow_clone(repo_url, branch or "main", repo_root)

        target = repo_root / rel_path
        if not target.exists():
            raise FileNotFoundError(f"Target file not found: {rel_path}")

        original = target.read_text(encoding="utf-8", errors="ignore")
        from_targets, import_targets = _parse_unused_targets(unused_imports)
        modified = _transform_source(original, from_targets, import_targets)
        if modified == original:
            raise ValueError("No changes produced; nothing to diff")

        ast.parse(modified)

        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile=rel_path, tofile=rel_path, lineterm=""
        ))
        patch = "".join(diff_lines)
        removed = sum(1 for s in diff_lines if s.startswith("-") and not s.startswith("---"))
        added = sum(1 for s in diff_lines if s.startswith("+") and not s.startswith("+++"))

        return {
            "candidate": candidate,
            "unused_imports": unused_imports,
            "lines_removed": removed,
            "lines_added": added,
            "patch": patch,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# --- Internal helpers ---
def _shallow_clone(repo_url: str, branch: str, dest: Path) -> None:
    subprocess.check_call([
        "git","clone","--depth","1","--single-branch","--branch",branch,repo_url,str(dest)
    ])

def _parse_unused_targets(unused_list: List[str]) -> Tuple[Dict[str, Set[str]], Set[str]]:
    from_targets: Dict[str, Set[str]] = {}
    import_targets: Set[str] = set()
    for item in unused_list:
        if "::" not in item:
            continue
        lib, name = item.split("::", 1)
        lib, name = lib.strip(), name.strip()
        if lib == name:
            import_targets.add(lib)
        else:
            from_targets.setdefault(lib, set()).add(name)
    return from_targets, import_targets

def _transform_source(source: str, from_targets: Dict[str, Set[str]], import_targets: Set[str]) -> str:
    def base_name(s: str) -> str:
        parts = s.split()
        if len(parts) >= 3 and parts[-2] == "as":
            return " ".join(parts[:-2])
        return s.strip()

    out_lines: List[str] = []
    for line in source.splitlines(keepends=False):
        stripped = line.strip()

        # Case 1: from X import ...
        if stripped.startswith("from ") and " import " in stripped:
            m = re.match(r"^from\s+([A-Za-z0-9_.]+)\s+import\s+(.+)$", stripped)
            if m:
                lib = m.group(1)
                names = [p.strip() for p in m.group(2).split(",")]
                before = len(names)
                if lib in from_targets:
                    names = [n for n in names if base_name(n) not in from_targets[lib]]
                if before != len(names):
                    if len(names) == 0:
                        continue
                    indent = line[: len(line) - len(line.lstrip())]
                    out_lines.append(f"{indent}from {lib} import {', '.join(names)}")
                    continue

        # Case 2: import A, B, ...
        if stripped.startswith("import "):
            rest = stripped[len("import "):]
            mods = [p.strip() for p in rest.split(",")]
            before = len(mods)
            mods = [m for m in mods if base_name(m) not in import_targets]
            if before != len(mods):
                if len(mods) == 0:
                    continue
                indent = line[: len(line) - len(line.lstrip())]
                out_lines.append(f"{indent}import {', '.join(mods)}")
                continue

        out_lines.append(line)

    return "\n".join(out_lines) + ("\n" if source.endswith("\n") else "")