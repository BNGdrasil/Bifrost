# 개발

로컬 개발 환경 구성과 테스트 실행, 린트, Docker 빌드 방법을 설명합니다.

## 로컬 개발

의존성 설치와 개발 서버 실행은 다음과 같습니다.

```bash
uv sync
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

환경 변수는 `env.example`을 복사해서 `.env`로 만든 뒤 채웁니다. 각 변수의 의미는 [설정](configuration.md) 문서에 정리되어 있습니다.

## 테스트

SQLite를 사용하는 테스트는 별도 인프라 없이 바로 실행할 수 있습니다.

```bash
DATABASE_URL=sqlite:///:memory:  \
SECRET_KEY=local-test-secret-key \
ENVIRONMENT=test \
uv run pytest
```

PostgreSQL을 대상으로 하는 테스트는 `docker-compose.test.yml`로 준비된 컨테이너를 사용합니다. 이 컴포즈 파일이 띄우는 테스트 데이터베이스 이름은 `bngdrasil_test`입니다.

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from bifrost-test
```

CI(`.github/workflows/ci.yml`)도 같은 스키마(`tests/fixtures/init_test_db.sql`)를 PostgreSQL과 SQLite 양쪽에 적용해서 두 백엔드 모두에서 테스트를 돌립니다.

## 포매팅과 린트

```bash
uv run black --check .
uv run isort --check-only .
uv run flake8 src tests
uv run mypy src
```

## Docker 빌드

Docker 이미지는 멀티스테이지로 빌드되며, 최종 런타임 이미지는 non-root 사용자(`bifrost`, uid 10001)로 `python -m src.main`을 실행합니다. 이 진입점은 `HOST`와 `PORT`, `FORWARDED_ALLOW_IPS`를 애플리케이션이 사용하는 것과 같은 `Settings` 객체에서 읽으므로, 컨테이너 명령과 애플리케이션 설정이 서로 어긋날 일이 없습니다. 또한 서비스 등록부가 프로세스 메모리 안의 스냅숏이라는 제약 때문에 워커 수는 항상 1로 고정되어 있습니다.

```bash
docker build -t bifrost .
docker run -p 8000:8000 --env-file .env bifrost
```
