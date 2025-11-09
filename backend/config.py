from pathlib import Path
import os

AGENTS_ARN = os.getenv("AGENTS_ARN", "")
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-2")
BUCKET_NAME = os.getenv("BUCKET_NAME", "dev-agents-bff")
LOCAL_AWS = os.getenv("LOCAL_AWS", "").lower() in ("1", "true", "yes", "stub")
LOCAL_S3_ROOT = Path("_local_s3")