from backend.runner.agents import dependency_analyst, planner, implementer, reviewer
from backend.runner.utils import job_io
from backend.config import LOCAL_AWS, AWS_REGION, AGENTS_ARN
from typing import Any, Dict
import boto3, json, logging, sys, threading

# --- Logging ---
log = logging.getLogger()
if not log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
log.setLevel(logging.INFO)

# --- Allowed stages & statuses ---
ALLOWED_STAGES = {"dependency_analyst", "planner", "implementer", "reviewer"}
ALLOWED_STATUSES = {"accepted", "running", "completed", "failed"}

# --- Handler ---
def handler(event: Dict[str, Any], context: Any):
    # --- Step 1: Validate minimal payload ---
    job_id = event.get("job_id")
    if not job_id:
        log.error({"event": "runner_invalid_event", "error": "missing job_id",})
        return {"ok": False, "error": "missing job_id"}

    # --- Step 2: Load job ---
    job = job_io.load(job_id, "job")
    if not job:
        log.error({"event": "runner_job_not_found", "job_id": job_id, "error": "job not found",})
        return {"ok": False, "error": "job not found"}

    repo_url = job.get("repo_url")
    branch = job.get("branch", "main")
    status = job.get("status")
    stage = job.get("stage")

    # --- Step 3: Validate job ---
    if not repo_url:
        job_io.update(job_id,  "job", {"status": "failed",})
        log.error({"event": "runner_stage_failed", "job_id": job_id, "stage": stage, "error": "repo_url is missing in job",})
        return {"ok": False, "error": "repo_url is missing in job"}

    if status not in ALLOWED_STATUSES:
        job_io.update(job_id, "job", {"status": "failed",})
        log.error({"event": "runner_stage_failed", "job_id": job_id, "stage": stage, "error": f"Unknown status '{status}'",})
        return {"ok": False, "error": f"Unknown status '{status}'"}

    if stage not in ALLOWED_STAGES:
        job_io.update(job_id, "job", {"status": "failed",})
        log.error({"event": "runner_stage_failed", "job_id": job_id, "stage": stage, "error": f"Unknown stage '{stage}'",})
        return {"ok": False, "error": f"Unknown stage '{stage}'"}

    # --- Step 4: Only proceed when accepted or running ---
    if status not in {"accepted", "running"}:
        return {"ok": True}

    # --- Step 5: Promote to running if currently accepted ---
    if status == "accepted":
        status = "running"
        job_io.update(job_id, "job", {"status": status,})
        
    # --- Step 6: Dispatch exactly one stage ---
    try:
        log.info({"event": "runner_stage_dispatch", "job_id": job_id, "status": status, "stage": stage,})

        if stage == "dependency_analyst":
            dependency_analyst.run(job_id, repo_url, branch)
        elif stage == "planner":
            planner.run(job_id, repo_url, branch)
        elif stage == "implementer":
            implementer.run(job_id, repo_url, branch)
        elif stage == "reviewer":
            reviewer.run(job_id, repo_url, branch)
        else:
            raise ValueError(f"Unknown stage '{stage}'")

        log.info({"event": "runner_stage_completed", "job_id": job_id, "status": status, "stage": stage,})
    except Exception as e:
        err_msg = str(e)
        job_io.update(job_id, "job", {"status": "failed",})
        log.error({"event": "runner_stage_failed", "job_id": job_id, "stage": stage, "error": err_msg,})
        return {"ok": False, "error": err_msg}

    # --- Step 7: Fire-and-forget self-reinvoke exactly once if the stage advanced ---
    next_job = job_io.load(job_id, "job") or {}
    next_status = next_job.get("status")
    next_stage = next_job.get("stage")

    should_continue = (
        next_status in {"accepted", "running"}
        and next_stage in ALLOWED_STAGES
        and next_stage != stage
    )

    if should_continue:
        _self_reinvoke(job_id)

    return {"ok": True}

def _self_reinvoke(job_id: str) -> None:
    if LOCAL_AWS:
        threading.Thread(target=lambda: handler({"job_id": job_id}, None), daemon=True).start()
    else:
        if not AGENTS_ARN:
            log.error({"event": "runner_reinvoke_missing_arn", "job_id": job_id, "error": "AGENTS_ARN not set",})
            return
        lambda_client = boto3.client("lambda", region_name=AWS_REGION)
        lambda_client.invoke(
            FunctionName=AGENTS_ARN,
            InvocationType="Event",
            Payload=json.dumps({"job_id": job_id}).encode("utf-8"),
        )