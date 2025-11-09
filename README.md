# Deployment

## Local Deployment

### Frontend
- Run the React app locally with Vite.
```bash
cd frontend
cp .env.example .env                    # One-Time Setup
npm install                             # One-Time Setup
npm run dev
```

### Backend
- Start the FastAPI server with Uvicorn.
```bash
cd backend
cp .env.example .env                    # One-Time Setup
python3 -m venv .venv                   # One-Time Setup
source .venv/bin/activate
pip install -r bff/requirements.txt     # One-Time Setup
PYTHONPATH=.. uvicorn backend.bff.app:app --reload --port 8000
```

## Cloudflare Pages & AWS Deployment

### Prerequisites
- Create an Amazon S3 bucket "dev-agents-bff".
- Create an AWS Lambda function "dev-agents-bff" (Runtime: Python 3.12, Handler: backend.bff.app.handler, Architecture: arm64).
- Create an AWS Lambda function "dev-agents-runner" (Runtime: Python 3.12, Handler: backend.runner.handler.handler, Architecture: arm64).
- Add environment variables to both Lambdas: AGENTS_ARN (Lambda runner function ARN), BUCKET_NAME (S3 bucket name), and STAGE=prod.
- Create an IAM policy "DevAgentsS3JobsPolicy" granting s3:ListBucket, s3:GetObject, and s3:PutObject access to {S3_BUCKET_NAME}/jobs/*.
- Create an IAM policy "DevAgentsInvokeRunnerPolicy" granting lambda:InvokeFunction on the Lambda runner function.
- Create an IAM role "DevAgentsBffLambdaRole" with AWSLambdaBasicExecutionRole, DevAgentsS3JobsPolicy, and DevAgentsInvokeRunnerPolicy.
- Create an IAM role "DevAgentsRunnerLambdaRole" with AWSLambdaBasicExecutionRole, DevAgentsS3JobsPolicy, and DevAgentsInvokeRunnerPolicy.
- Attach DevAgentsBffLambdaRole to the Lambda bff function.
- Attach DevAgentsRunnerLambdaRole to the Lambda runner function.
- Amazon API Gateway HTTP API "dev-agents-bff" with POST /jobs and GET /jobs/{id} routes integrated to the Lambda bff function (CORS enabled, stage: prod).
- Deploy the frontend on Cloudflare Pages (dev-agents.pages.dev) connected to the GitHub repo kaitozaw/dev_agents.
- Add a Cloudflare Pages environment variable VITE_API_BASE_URL=https://{API_ID}.execute-api.{REGION}.amazonaws.com/{STAGE}.

### Frontend (Cloudflare Pages)
- Push the changes to the main branch for GitHub repo kaitozaw/dev_agents.
```bash
git add .
git commit -m "message"
git push origin main
```

### Backend (AWS)
- Create artefacts/bff/bff.zip and upload it to the Lambda bff function.
```bash
cd backend

rm -rf artefacts/bff && mkdir -p artefacts/bff/build/backend/bff

cp bff/app.py artefacts/bff/build/backend/bff
cp config.py artefacts/bff/build/backend/

docker run --rm \
  -v "$PWD":/var/task \
  --platform linux/arm64 \
  --entrypoint /bin/sh \
  public.ecr.aws/lambda/python:3.12-arm64 \
  -c "python -m pip install -r /var/task/bff/requirements.txt -t /var/task/artefacts/bff/build"

(
  cd artefacts/bff/build && \
  zip -r9 ../bff.zip . \
    -x '*.DS_Store' '.git/*' '.gitignore' '.venv/*' '__pycache__/*' 'tests/*' '.env' 'artefacts/*'
)
```

- Create artefacts/runner/runner.zip and upload it to the Lambda runner function.
```bash
cd backend

rm -rf artefacts/runner && mkdir -p artefacts/runner/build/backend/runner

cp -R runner/agents artefacts/runner/build/backend/runner/
cp -R runner/utils artefacts/runner/build/backend/runner/
cp runner/handler.py artefacts/runner/build/backend/runner/
cp config.py artefacts/runner/build/backend/

docker run --rm \
  -v "$PWD":/var/task \
  --platform linux/arm64 \
  --entrypoint /bin/sh \
  public.ecr.aws/lambda/python:3.12-arm64 \
  -c "python -m pip install -r /var/task/runner/requirements.txt -t /var/task/artefacts/runner/build"

(
  cd artefacts/runner/build && \
  zip -r9 ../runner.zip . \
    -x '*.DS_Store' '.git/*' '.gitignore' '.venv/*' '__pycache__/*' 'tests/*' '.env' 'artefacts/*' '_local_s3/*'
)
```