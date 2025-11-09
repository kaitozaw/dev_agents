# Deployment

## Local Deployment

### Frontend
```bash
cd frontend
cp .env.example .env                    # One-Time Setup
npm install                             # One-Time Setup
npm run dev
```

### Backend
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

### Frontend (Cloudflare Pages)

### Backend (AWS)




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