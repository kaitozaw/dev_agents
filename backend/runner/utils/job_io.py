from backend.config import AWS_REGION, BUCKET_NAME, LOCAL_AWS, LOCAL_S3_ROOT
from typing import Dict, Any, Optional, Tuple
import boto3, json

_s3 = boto3.client("s3", region_name=AWS_REGION)

def load(job_id: str, file_name: str) -> Optional[Dict[str, Any]]:
    key = f"jobs/{job_id}/{file_name}.json"
    return read(key)

def read(key: str) -> Optional[Dict[str, Any]]:
    if LOCAL_AWS:
        p = LOCAL_S3_ROOT / key
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    try:
        obj = _s3.get_object(Bucket=BUCKET_NAME, Key=key)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except _s3.exceptions.NoSuchKey:
        return None

def update(job_id: str, file_name: str, patch: Dict[str, Any]) -> None:
    key = f"jobs/{job_id}/{file_name}.json"
    job = read(key) or {}
    job.update(patch)
    write(key, job)

def write(key: str, data: Dict[str, Any]) -> None:
    if LOCAL_AWS:
        p = LOCAL_S3_ROOT / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    else:
        _s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )