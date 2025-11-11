from backend.runner.utils import job_io
from pathlib import Path
from typing import Any, List, Dict
import json, os, requests, shutil, subprocess, tempfile

# --- Public API ---
def review_diff(job_id: str, repo_url: str, branch: str) -> Dict[str, Any]:
    diff = job_io.load(job_id, "implement.diff")
    candidate = diff.get("candidate")
    if not candidate:
        raise ValueError("implement.diff.json must include 'candidate'")

    rel_path = candidate.replace(".", "/") + ".py"
    tmpdir = tempfile.mkdtemp(prefix="reviewer-")
    repo_root = Path(tmpdir) / "repo"
    try:
        _shallow_clone(repo_url, (branch or "main"), repo_root)

        patch_text = diff.get("patch")
        if patch_text:
            _apply_patch(repo_root, patch_text)

        target = repo_root / rel_path
        if not target.exists():
            raise FileNotFoundError(f"Target file not found after patch: {rel_path}")

        lint_items = _run_ruff(repo_root, [rel_path])
        summary = _llm_summary(lint_items)

        return {
            "lint_issues": {"count": len(lint_items), "items": lint_items},
            "summary": summary,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# --- Internal helpers ---
def _shallow_clone(repo_url: str, branch: str, dest: Path) -> None:
    subprocess.check_call([
        "git","clone","--depth","1","--single-branch","--branch",branch,repo_url,str(dest)
    ])

def _apply_patch(repo_dir: Path, patch_text: str) -> None:
    try:
        subprocess.run(
            ["patch", "-p0"], input=patch_text.encode("utf-8"), cwd=repo_dir, check=False, capture_output=True
        )
    except Exception:
        pass

def _run_ruff(repo_dir: Path, files: List[str]) -> List[Dict[str, Any]]:
    if not files:
        return []
    targets = [str(repo_dir / f) for f in files if (repo_dir / f).exists()]
    if not targets:
        return []
    try:
        proc = subprocess.run(
            ["ruff", "check", "--format", "json"] + targets, capture_output=True, text=True, check=False
        )
        data = json.loads(proc.stdout or "[]")
    except Exception:
        return []

    items = []
    for entry in data:
        fname = entry.get("filename", "")
        for msg in entry.get("messages", []):
            items.append({
                "file": str(Path(fname).relative_to(repo_dir)) if fname else "",
                "line": msg.get("location", {}).get("row"),
                "code": msg.get("code"),
                "message": msg.get("message"),
            })
    return items

def _llm_summary(lint_items: List[Dict[str, Any]]) -> str:
    key = os.getenv("OPEN_API_KEY", "").strip()
    if not key:
        return "Review done: ruff executed (no LLM key)."

    sample = "\n".join(f"{i['file']}:{i.get('line')} {i.get('code')} {i.get('message')}" for i in lint_items[:5]) or "No lint issues found."

    prompt = (
        "Summarise these ruff findings in one concise sentence "
        "for a commit message.\n\n" + sample
    )

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are a Python reviewer."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 60,
            },
            timeout=15,
        )
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or "Review complete: no additional comments."
    except Exception:
        return "Review done: ruff executed (LLM failed)."