from datetime import datetime, timezone
from botocore.stub import Stubber, ANY
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, AnyUrl
from mangum import Mangum
import boto3, json, logging, os, pathlib, uuid

# Load .env on local run
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

log = logging.getLogger()
log.setLevel(logging.INFO)

AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-2")
BUCKET_NAME = os.getenv("BUCKET_NAME", "dev-agents-bff-state")
STATE_MACHINE_ARN = os.getenv("STATE_MACHINE_ARN", "")
LOCAL_AWS = os.getenv("LOCAL_AWS", "").lower() in ("1", "true", "yes", "stub")

# Create clients
s3 = boto3.client("s3", region_name=AWS_REGION)
sfn = boto3.client("stepfunctions", region_name=AWS_REGION)

# When LOCAL, stub out AWS calls so we can run without real AWS
if LOCAL_AWS:
    s3_stubber = Stubber(s3)
    sfn_stubber = Stubber(sfn)

    # Accept any put_object to .../jobs/<uuid>/state.json
    s3_stubber.add_response(
        "put_object",
        expected_params={"Bucket": BUCKET_NAME, "Key": ANY, "Body": ANY, "ContentType": "application/json"},
        service_response={},  # empty success
    )
    s3_stubber.activate()

    # Accept any start_execution to given state machine
    sfn_stubber.add_response(
        "start_execution",
        expected_params={"stateMachineArn": STATE_MACHINE_ARN or ANY, "input": ANY},
        service_response={"executionArn": "arn:aws:states:local:000000000000:execution/dev:dummy", "startDate": datetime.now(timezone.utc)},
    )
    sfn_stubber.activate()

app = FastAPI(title="Dev Agents BFF")

class JobCreate(BaseModel):
    repo_url: AnyUrl
    branch: str = "main"

@app.post("/jobs", status_code=202)
def create_job(payload: JobCreate):
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    state = {
        "job_id": job_id,
        "repo_url": str(payload.repo_url),
        "branch": payload.branch,
        "status": "accepted",
        "created_at": now,
    }

    key = f"jobs/{job_id}/state.json"

    # 1) Save to S3 (stubbed on local)
    try:
        # Real (or stubbed) AWS call
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        log.info({"event": "s3_put_object", "bucket": BUCKET_NAME, "key": key, "job_id": job_id})

        # Optional: on LOCAL also write a visible local copy for easy inspection
        if LOCAL_AWS:
            local_copy = pathlib.Path("_local_s3") / key
            local_copy.parent.mkdir(parents=True, exist_ok=True)
            local_copy.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        log.exception("Failed to save job state to S3")
        raise HTTPException(status_code=500, detail={"error":{"code":"INTERNAL_ERROR","message":"S3 save failed"}})

    # 2) Start Step Functions (stubbed on local)
    try:
        sfn.start_execution(
            stateMachineArn=STATE_MACHINE_ARN or "arn:aws:states:local:000000000000:stateMachine/dev",
            input=json.dumps({"job_id": job_id, "repo_url": state["repo_url"], "branch": state["branch"]}),
        )
        log.info({"event": "sfn_start_execution", "stateMachineArn": STATE_MACHINE_ARN or "local", "job_id": job_id})
    except Exception:
        log.exception("Failed to start Step Functions")
        raise HTTPException(status_code=500, detail={"error":{"code":"INTERNAL_ERROR","message":"SFN start failed"}})

    return {"job_id": job_id, "status": "accepted"}

# Lambda entrypoint (ignored on local uvicorn run)
STAGE = os.getenv("STAGE", "")
BASE_PATH = f"/{STAGE}" if STAGE else None
handler = Mangum(app, api_gateway_base_path=BASE_PATH)