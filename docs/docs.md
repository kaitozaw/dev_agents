rm -rf build && mkdir -p build

docker run --rm \
  -v "$PWD":/var/task \
  --entrypoint /bin/sh \
  public.ecr.aws/lambda/python:3.12-arm64 \
  -c "python -m pip install -r /var/task/requirements.txt -t /var/task/build"

  cp app.py build/

(
  cd build && \
  zip -r9 ../lambda.zip . \
    -x '*.DS_Store' '.git/*' '.gitignore' '.venv/*' '__pycache__/*' 'tests/*' '.env'
)