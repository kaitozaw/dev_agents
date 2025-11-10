import logging, sys, traceback
from backend.runner.utils import job_io

log = logging.getLogger()
if not log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
log.setLevel(logging.INFO)

def run(job_id: str, repo_url: str, branch: str):
    try:
        print("implement")
        job_io.update(job_id, "job", {"stage": "reviewer",})
    except Exception as e:
        err_msg = str(e)
        job_io.update(job_id, "job", { "status": "failed",})
        log.error({"event": "agent_stage_failed", "job_id": job_id, "stage": "implementer", "error": err_msg, "traceback": traceback.format_exc(),})