from pathlib import Path
from typing import Any, Dict, List, Set
import ast, json, subprocess, shutil, tempfile

# --- Public API ---
def analyse_repo(repo_url: str, branch: str) -> Dict[str, Any]:
    tmpdir = tempfile.mkdtemp(prefix="dep-analyst-")
    repo_root = Path(tmpdir) / "repo"
    try:
        _shallow_clone(repo_url, branch or "main", repo_root)
        py_files = _collect_python_files(repo_root)
        graph, imports_map = _build_dependency_graph(repo_root, py_files)
        topo_order, residual = _topo_sort_and_cycles(graph)
        unused_ast = _detect_unused(imports_map)
        unused_ruff = _try_ruff_f401(repo_root)
        unused = _merge_unused(unused_ast, unused_ruff)

        nodes = sorted(graph.keys())
        edges = sorted([(s, d) for s, dsts in graph.items() for d in dsts])
        impacted = sorted(unused.keys(), key=lambda m: (-len(unused[m]), m))
        return {
            "nodes": nodes,
            "edges": edges,
            "impacted": impacted,
            "topo_order": topo_order,
            "warnings": {"circular_imports": residual} if residual else {},
            "unused_imports": unused,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# --- Internal helpers ---
class _ImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports: Dict[str, Set[str]] = {}
        self.importfrom_details: Dict[str, List[tuple]] = {}
        self.used_names: Set[str] = set()
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod = alias.name
            name = alias.asname or mod.split(".")[0]
            self.imports.setdefault(mod, set()).add(name)
        self.generic_visit(node)
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        dots = "." * (node.level or 0)
        mod = f"{dots}{base}"
        for alias in node.names:
            if alias.name != "*":
                name = alias.asname or alias.name
                self.imports.setdefault(mod, set()).add(name)
            self.importfrom_details.setdefault(mod, []).append((alias.name, alias.asname))
        self.generic_visit(node)
    def visit_Name(self, node: ast.Name) -> None:
        self.used_names.add(node.id)
    def visit_Attribute(self, node: ast.Attribute) -> None:
        curr = node
        while isinstance(curr, ast.Attribute):
            curr = curr.value
        if isinstance(curr, ast.Name):
            self.used_names.add(curr.id)
        self.generic_visit(node)

def _shallow_clone(repo_url: str, branch: str, dest: Path) -> None:
    subprocess.check_call([
        "git","clone","--depth","1","--single-branch","--branch",branch,repo_url,str(dest)
    ])

def _collect_python_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]

def _build_dependency_graph(repo_root: Path, py_files: List[Path]):
    modules = {_file_to_module(repo_root, p) for p in py_files}
    graph: Dict[str, Set[str]] = {m: set() for m in modules}
    imports_map: Dict[str, Dict[str, Set[str]]] = {}

    for p in py_files:
        mod = _file_to_module(repo_root, p)
        src = p.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src, filename=str(p))
        v = _ImportVisitor()
        v.visit(tree)

        imports_map[mod] = {"used": v.used_names, "imports": {}}
        for key, names in v.imports.items():
            clean_names = {n for n in names if n != "*"}
            if clean_names:
                imports_map[mod]["imports"][key] = clean_names

        for base, pairs in getattr(v, "importfrom_details", {}).items():
            for orig_name, _asname in pairs:
                if orig_name == "*":
                    for t in _resolve_import_to_modules(base, mod, modules):
                        if t and t != mod:
                            graph[mod].add(t)
                    continue
                full = f"{base}.{orig_name}".strip(".")
                resolved_any = False
                for t in _resolve_import_to_modules(full, mod, modules):
                    if t and t != mod:
                        graph[mod].add(t)
                        resolved_any = True
                if not resolved_any:
                    for t in _resolve_import_to_modules(base, mod, modules):
                        if t and t != mod:
                            graph[mod].add(t)

        for key, _names in v.imports.items():
            for t in _resolve_import_to_modules(key, mod, modules):
                if t and t != mod:
                    graph[mod].add(t)

    return graph, imports_map

def _file_to_module(repo_root: Path, py_path: Path) -> str:
    rel = py_path.relative_to(repo_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)

def _resolve_import_to_modules(key: str, current: str, all_mods: Set[str]) -> Set[str]:
    resolved: Set[str] = set()
    if key.startswith("."):
        level = len(key) - len(key.lstrip("."))
        base = key[level:]
        curr_parts = current.split(".")
        if level <= len(curr_parts):
            prefix = ".".join(curr_parts[:len(curr_parts)-level])
            cand = f"{prefix}.{base}" if base else prefix
            cand = cand.strip(".")
            if cand in all_mods:
                resolved.add(cand)
    else:
        parts = key.split(".")
        while parts:
            cand = ".".join(parts)
            if cand in all_mods:
                resolved.add(cand); break
            parts.pop()
    return resolved

def _topo_sort_and_cycles(graph: Dict[str, Set[str]]):
    indeg = {n: 0 for n in graph}
    for _, dsts in graph.items():
        for d in dsts:
            indeg[d] = indeg.get(d, 0) + 1
    q = [n for n, d in indeg.items() if d == 0]
    order, local = [], {n: set(d) for n, d in graph.items()}
    while q:
        n = q.pop(); order.append(n)
        for d in list(local.get(n, set())):
            local[n].remove(d)
            indeg[d] -= 1
            if indeg[d] == 0:
                q.append(d)
    residual = [n for n, ds in local.items() if ds]
    return order, residual

def _detect_unused(imports_map: Dict[str, Dict[str, Set[str]]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for mod, data in imports_map.items():
        used = data["used"]
        unused = []
        for key, names in data["imports"].items():
            for n in names:
                if n not in used:
                    unused.append(f"{key}::{n}")
        if unused:
            out[mod] = sorted(unused)
    return out

def _try_ruff_f401(repo_root: Path) -> Dict[str, List[str]]:
    if shutil.which("ruff") is None:
        return {}
    try:
        out = subprocess.check_output(
            ["ruff","check","--select","F401","--output-format","json",str(repo_root)],
            stderr=subprocess.STDOUT, text=True
        )
        records = json.loads(out) if out.strip() else []
        result: Dict[str, List[str]] = {}
        for rec in records:
            mod = _file_to_module(repo_root, Path(rec.get("filename","")))
            msg = rec.get("message","")
            name = ""
            if "`" in msg:
                parts = msg.split("`")
                if len(parts) >= 2:
                    name = parts[1]
            entry = f"ruff::{name}" if name else f"ruff::{msg}"
            result.setdefault(mod, []).append(entry)
        return result
    except Exception:
        return {}

def _merge_unused(a: Dict[str, List[str]], b: Dict[str, List[str]]) -> Dict[str, List[str]]:
    keys = set(a) | set(b)
    out: Dict[str, List[str]] = {}
    for k in keys:
        merged = set(a.get(k, [])) | set(b.get(k, []))
        if merged:
            out[k] = sorted(merged)
    return out