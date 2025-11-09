from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel, AnyUrl
import boto3, os, json, uuid, logging, sys, threading, traceback

# --- Load .env ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from backend.config import AGENTS_ARN, AWS_REGION, BUCKET_NAME, LOCAL_AWS, LOCAL_S3_ROOT

# --- Logging ---
log = logging.getLogger()
if not log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
log.setLevel(logging.INFO)

# --- AWS Clients ---
s3 = boto3.client("s3", region_name=AWS_REGION)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)

# --- Local stub helpers ---
def _local_s3_put(key: str, obj: dict):
    p = LOCAL_S3_ROOT / key
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")

def _local_s3_get(key: str) -> dict:
    p = LOCAL_S3_ROOT / key
    return json.loads(p.read_text(encoding="utf-8"))

# --- FastAPI App ---
app = FastAPI(title="Dev Agents BFF")

if LOCAL_AWS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type"],
        allow_credentials=True,
    )

class JobCreate(BaseModel):
    repo_url: AnyUrl
    branch: str = "main"

@app.post("/jobs", status_code=202)
def create_job(payload: JobCreate):
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    job = {
        "job_id": job_id,
        "created_at": now,
        "repo_url": str(payload.repo_url),
        "branch": payload.branch,
        "status": "accepted",
        "stage": "dependency_analyst",
    }
    key = f"jobs/{job_id}/job.json"

    # --- Step 1: Create job ---
    try:
        if LOCAL_AWS:
            _local_s3_put(key, job)
        else:
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key=key,
                Body=json.dumps(job, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
            )
        log.info({"event": "create_job", "job_id": job_id, "local": LOCAL_AWS, "bucket": BUCKET_NAME, "key": key })
    except Exception as e:
        err_msg = str(e)
        log.error({"event": "create_job_failed", "job_id": job_id, "error": err_msg, "traceback": traceback.format_exc(),})
        raise HTTPException(status_code=500, detail={"error": err_msg})

    # --- Step 2: Invoke Runner ---
    try:
        runner_payload = {"job_id": job_id}

        if LOCAL_AWS:
            from backend.runner.handler import handler as local_runner
            threading.Thread(target=lambda: local_runner(runner_payload, None), daemon=True).start()
        else:
            if not AGENTS_ARN:
                raise HTTPException(status_code=500, detail={"error": {"message": "AGENT_RUNNER_ARN is not set"}})
            lambda_client.invoke(
                FunctionName=AGENTS_ARN,
                InvocationType="Event",
                Payload=json.dumps(runner_payload),
            )
        log.info({"event": "invoke_runner", "job_id": job_id, "local": LOCAL_AWS,})
    except Exception as e:
        err_msg = str(e)
        log.error({"event": "invoke_runner_failed", "job_id": job_id, "error": err_msg, "traceback": traceback.format_exc(),})
        raise HTTPException(status_code=500, detail={"error": err_msg})

    return {"job_id": job_id}

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    key = f"jobs/{job_id}/job.json"
    try:
        if LOCAL_AWS:
            data = _local_s3_get(key)
        else:
            obj = s3.get_object(Bucket=BUCKET_NAME, Key=key)
            data = json.loads(obj["Body"].read().decode("utf-8"))
        return data
    except s3.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail={"error": {"message": "Job not found (s3)"}})
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": {"message": "Job not found (local)"}})
    except Exception as e:
        err_msg = str(e)
        log.error({"event": "read_job_failed", "job_id": job_id, "error": err_msg, "traceback": traceback.format_exc(),})
        raise HTTPException(status_code=500, detail={"error": err_msg})

# --- Lambda entrypoint ---
STAGE = os.getenv("STAGE", "")
BASE_PATH = f"/{STAGE}" if STAGE else None
handler = Mangum(app, api_gateway_base_path=BASE_PATH)