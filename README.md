# Bifrost

Bifrost는 BNGdrasil 인프라에서 마이크로서비스 앞단에 놓이는 API 게이트웨이다. 등록된 서비스 목록을 PostgreSQL에 저장해 두고, 그 목록을 기준으로 요청을 프록시하며, 관리 작업을 위한 REST API를 함께 제공한다.

Bifrost 자신은 사용자 권한을 판단하지 않는다. 관리자 API에 도착한 모든 요청은 Bearer 토큰을 그대로 들고 Bidar 인증 서버의 `POST /rbac/verify-permission`을 호출하고, 그 응답에 따라서만 허용 여부를 결정한다. 사용자 계정 정보 자체도 Bifrost가 저장하지 않고 Bidar가 소유하므로, 사용자 관리 API는 대부분 Bidar로 보내는 프록시로 구현되어 있다.

서비스 등록부는 프로세스 메모리에 올라간 스냅숏이며, 이 스냅숏은 워커 하나에만 존재한다. 그래서 `python -m src.main`은 uvicorn을 항상 `workers=1`로 실행한다. 처리량을 늘려야 한다면 워커 수를 올리는 대신 리버스 프록시 뒤에 이 프로세스를 여러 개 복제해서 두어야 하는데, 현재 코드는 그 복제본들 사이에서 등록부를 동기화하는 기능을 제공하지 않으므로 인스턴스마다 서로 다른 시점의 스냅숏을 가질 수 있다는 점을 감안해야 한다.

## 요청 경로

### 게이트웨이 API (`/api/v1`, 인증 불필요)

| 경로 | 메서드 | 설명 |
| --- | --- | --- |
| `/api/v1/services` | GET | 등록된 서비스 목록을 반환한다. 공개 엔드포인트이므로 업스트림 URL, 타임아웃, rate limit, metadata 같은 내부 정보는 응답에 포함하지 않고 이름·표시 이름·설명·마지막 health 상태만 내려준다. |
| `/api/v1/services/{name}/health` | GET | 해당 서비스에 대해 마지막으로 기록된 health 상태를 그대로 읽어서 반환한다. 이 호출 자체가 업스트림에 실제 요청을 보내지는 않으므로, 인증되지 않은 사용자가 이 엔드포인트를 내부망에 대한 무제한 probe로 악용할 수 없다. 실시간으로 확인하려면 관리자 API의 health-check-all을 사용해야 한다. |
| `/api/v1/{service}/{path}` | GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS | 등록된 서비스로 요청을 그대로 전달하는 프록시 경로다. |
| `/health` | GET | liveness 프로브다. 프로세스가 요청을 처리할 수 있는 상태이기만 하면 항상 200을 반환하며, DB나 등록부 상태는 확인하지 않는다. |
| `/ready` | GET | readiness 프로브다. DB 연결 확인과 서비스 등록부의 준비 상태를 함께 검사해서, 둘 중 하나라도 실패하면 503을 반환한다. |
| `/metrics` | GET | Prometheus exposition 형식의 지표를 반환한다. |

프록시 경로는 요청 본문과 응답 본문을 전부 메모리에 올려서 전달하는 buffered 방식이며, 진짜 스트리밍이나 서버 전송 이벤트는 지원 범위 밖에 있다. 요청 본문 크기는 `MAX_REQUEST_BODY_BYTES`로 제한되어 있고, 이를 초과하면 `Content-Length` 헤더만으로도, 혹은 실제 본문 길이로도 413을 반환한다. 응답을 만들 때는 다음과 같은 규칙을 지킨다.

- 등록되지 않은 서비스로 향하는 요청은 404를 반환한다.
- 업스트림 연결 자체가 실패하면 502, 업스트림이 타임아웃되면 504를 반환해서 두 실패를 구분한다.
- `Connection`, `Transfer-Encoding` 같은 hop-by-hop 헤더와, `Connection` 헤더가 직접 지목한 헤더는 요청과 응답 양쪽에서 제거한다.
- 요청 경로에 이미 서버가 한 번 디코딩한 뒤에도 `%2e`, `%2f`, `%5c` 같은 인코딩이나 `.`/`..` 세그먼트가 남아 있으면 그 요청은 400으로 거절한다. 이렇게 해야 인코딩을 다시 해석하는 과정에서 등록된 base path를 벗어나는 경로 조작을 막을 수 있다.
- 잘못된 `Content-Length` 값은 400으로 거절한다.
- 업스트림으로 보내는 요청에는 `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Request-ID` 헤더를 채워서 붙인다. `X-Request-ID`는 클라이언트가 이미 보낸 값이 있으면 그 값을 그대로 이어서 쓰고, 없으면 새로 발급한다.

## 관리자 API (`/admin/api`)

관리자 API의 모든 엔드포인트는 `Authorization: Bearer <access-token>` 헤더를 요구하며, 이 토큰은 Bidar가 발급한 access 토큰이어야 한다. 각 엔드포인트는 자신에게 필요한 최소 역할을 먼저 명시하고, 실제 판정은 Bidar의 `/rbac/verify-permission` 응답에 맡긴다.

### 서비스 관리 (`/admin/api/services`, admin 이상)

서비스의 생성·조회·수정·삭제는 모두 데이터베이스에 반영된 다음 등록부를 바로 다시 불러오는 방식으로 동작하므로, 관리자 API를 통한 변경이 이 요청-응답 안에서 게이트웨이의 라우팅 표에 곧바로 반영된다. `POST /admin/api/services/reload`는 이 재적재를 수동으로 다시 실행하고, `POST /admin/api/services/health-check-all`은 등록된 모든 서비스에 실제로 health check 요청을 보내서 그 결과를 데이터베이스에 기록한다. 서비스를 등록할 때 넘기는 URL과 health check 경로는 목적지 정책 검사를 통과해야 하며, 그 내용은 아래 "등록부와 목적지 정책" 절에서 설명한다.

### 사용자 관리 (`/admin/api/users`, Bidar 프록시)

사용자 레코드는 Bifrost가 아니라 Bidar가 소유한다. 그래서 이 경로 아래의 요청은 자신의 역할 검사를 통과한 다음 호출자의 `Authorization` 헤더를 그대로 들고 Bidar로 넘어가며, Bidar가 내려준 상태 코드와 오류 메시지를 그대로 되돌려준다. 조회(목록, 단건)는 admin 이상이면 되지만, 생성·수정·삭제처럼 계정을 바꾸는 요청은 super_admin만 호출할 수 있다. `POST /admin/api/users/{id}/reset-password`는 아직 구현되어 있지 않으며 항상 501을 반환하므로, 비밀번호 재설정은 Bidar 쪽 플로우를 직접 사용해야 한다.

### 시스템 설정 (`/admin/api/settings`, 읽기 전용)

`GET /admin/api/settings`는 현재 실행 중인 프로세스의 유효 설정 값을 admin 권한으로 읽을 수 있게 해 주지만, 이 값들은 실행 중에 바꿀 수 없다. `PUT /admin/api/settings`는 super_admin에게도 501을 반환하며, 설정을 바꾸려면 배포 환경의 환경 변수를 수정하고 프로세스를 재시작해야 한다.

### 로그 (`/admin/api/logs`, 미구현)

Bifrost는 로그 인덱스를 직접 갖고 있지 않으므로 `GET /admin/api/logs`와 `GET /admin/api/logs/audit`는 admin 권한이 있어도 항상 501을 반환한다. 로그는 구조화된 형태로 표준 출력에 기록되고 있으며, 실제 조회는 Loki에 적재된 로그를 Grafana로 확인하는 방식을 사용해야 한다.

### 통계 (`/admin/api/services/stats`, `/admin/api/settings/stats/overview`, admin 이상)

이 두 엔드포인트는 Bifrost가 실제로 계산할 수 있는 값만 채워서 돌려준다. 서비스 수, 활성 서비스 수, health 상태별 집계, 등록부의 준비 상태 같은 값은 실제 값이 들어가지만, 사용자 통계나 API 요청량처럼 Bifrost가 별도로 적재해 두지 않은 값은 임의의 숫자를 만들어내지 않고 `null`로 내려준다. 응답에서 `null`이 보인다면 그것은 값이 0이라는 뜻이 아니라 그 항목을 아직 계산할 수단이 없다는 뜻으로 읽어야 한다.

## 등록부와 목적지 정책

서비스 등록부의 원본은 항상 PostgreSQL의 `services` 테이블이며, 프로세스 메모리에 있는 스냅숏은 그 테이블을 읽어서 만든 사본일 뿐이다. 스냅숏을 다시 불러올 때는 완성된 사본을 통째로 만든 다음 한 번에 교체하므로, 재적재 도중에 일부만 반영된 상태가 요청에 노출되는 일은 없다. 재적재가 실패하면 마지막으로 성공했던 스냅숏을 그대로 유지하면서 등록부를 degraded 상태로 표시하고, 이 상태에서는 `/ready`가 503을 반환한다.

서비스를 등록하거나 수정할 때 URL은 `src/core/urlpolicy.py`의 검사를 통과해야 한다. 허용되는 것은 `http`와 `https` 스킴, 그리고 사용자 정보를 포함하지 않은 호스트다. 반면 loopback 주소, link-local 주소, 클라우드 메타데이터 호스트(`metadata.google.internal` 등), 그리고 그런 주소를 가리키는 10진수·8진수·16진수 형태의 축약된 주소 리터럴은 등록 자체가 거절된다. `SERVICE_URL_ALLOWED_HOSTS`를 채워 두면 그 목록에 없는 호스트는 전부 거절되고, `SERVICE_URL_DENIED_HOSTS`에 있는 호스트는 allowlist 설정과 무관하게 항상 거절된다. 다만 이 검사는 등록하는 시점에 문자열로 적힌 값만 보고 판단하므로, 등록 이후에 그 호스트 이름이 DNS 상에서 다른 주소로 바뀌는 경우(DNS rebinding)까지는 막지 못한다. 이런 경우를 막으려면 네트워크 계층에서 별도의 egress 제어가 필요하다.

## 설정

Bifrost는 환경 변수로 설정을 받는다. `env.example`을 복사해서 `.env`로 만들고 값을 채우면 된다. `ALLOWED_HOSTS`나 `RATE_LIMIT_EXEMPT_PATHS`, `SERVICE_URL_ALLOWED_HOSTS`처럼 목록 형태인 값은 쉼표로 구분한 문자열(`a,b,c`)과 JSON 배열(`["a", "b"]`) 표기를 모두 받아들인다.

`ENVIRONMENT=production`일 때는 다음 값이 반드시 채워져 있어야 하며, 없으면 프로세스가 시작하지 않는다.

| 변수 | 요구 사항 |
| --- | --- |
| `SECRET_KEY` | 32자 이상이어야 하고, `env.example`에 들어 있는 예시 값과 같은 값이면 안 된다. |
| `DATABASE_URL` | 비어 있으면 안 된다. |
| `ALLOWED_HOSTS` | 비어 있으면 안 된다. 값이 없으면 호스트 헤더 검사 자체가 비활성화되는데, production에서는 그 상태를 선택 사항으로 두지 않는다. |

주요 환경 변수는 다음과 같다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `SECRET_KEY` | (development에서는 프로세스마다 무작위 생성) | 서명 등에 쓰이는 비밀 값. |
| `ENVIRONMENT` | `development` | `development`/`production`/`test` 중 하나. |
| `DATABASE_URL` | `postgresql://bnbong:password@postgres:5432/bngdrasil` | 서비스 등록부가 저장되는 PostgreSQL 접속 문자열. |
| `ALLOWED_HOSTS` | `["*"]` | `TrustedHostMiddleware`가 허용하는 호스트 헤더 목록. |
| `BACKEND_CORS_ORIGINS` | `["*"]` | CORS 미들웨어가 허용하는 origin 목록. `CLIENT_ORIGIN`에 값이 있으면 이 목록에 추가된다. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | uvicorn이 `X-Forwarded-*` 헤더를 신뢰할 리버스 프록시의 주소. |
| `RATE_LIMIT_PER_MINUTE` | `60` | 클라이언트 하나당 분당 허용 요청 수. |
| `RATE_LIMIT_EXEMPT_PATHS` | `/health,/ready,/metrics` | rate limit 대상에서 제외되는 경로. |
| `MAX_REQUEST_BODY_BYTES` | `10485760` | 프록시 요청 본문의 최대 크기. |
| `PROXY_TIMEOUT_SECONDS` | `30` | 업스트림 요청의 기본 타임아웃. |
| `PROXY_MAX_CONNECTIONS` | `100` | 업스트림으로 나가는 커넥션 풀의 최대 연결 수. |
| `SERVICE_URL_ALLOWED_HOSTS` | (비어 있음) | 값이 있으면 이 목록에 있는 호스트만 서비스로 등록할 수 있다. |
| `SERVICE_URL_DENIED_HOSTS` | (비어 있음) | 이 목록에 있는 호스트는 항상 등록이 거절된다. |
| `AUTH_SERVER_URL` | `http://auth-server:8001` | Bidar 인증 서버의 base URL. |
| `AUTH_SERVER_USERS_PATH` | `/users` | Bidar의 사용자 관리 API 경로. 사용자 관리 프록시는 `AUTH_SERVER_URL` + 이 값으로 요청을 보낸다. |

## 관측 (Observability)

`/metrics`는 다음 지표를 노출한다.

- `http_requests_total{method, service, status_class}`: 게이트웨이가 처리한 HTTP 요청 수. `service` 레이블은 프록시된 요청이면 등록된 서비스 이름, 그 외의 게이트웨이 자체 엔드포인트는 `gateway`가 된다. `method`는 표준 HTTP 메서드 집합으로만 값이 제한되며, 그 밖의 값은 `OTHER`로 뭉뚱그려진다. `status_class`는 `2xx`, `4xx`처럼 앞자리 하나로 묶은 값이다.
- `http_request_duration_seconds{method, service}`: 같은 레이블 조합으로 측정한 요청 처리 시간 히스토그램.

경로 자체를 레이블로 쓰지 않는 이유는, 등록된 서비스 수만큼만 카디널리티가 늘어나게 하기 위해서다. 계측 미들웨어는 `/health`, `/ready`, `/metrics`를 포함한 모든 요청에 대해 동작하므로, 이 경로들도 `service=gateway`로 집계된다.

Rate limiter는 각 프로세스 내부의 메모리에만 상태를 들고 있는 고정 윈도우 방식이다. 그래서 게이트웨이를 여러 인스턴스로 복제하면 그 제한은 인스턴스별로 독립적으로 적용되며, 인스턴스 사이에 공유되지 않는다.

로그는 `structlog`로 구조화된 JSON 형태로 표준 출력에 남는다.

## 로컬 개발과 테스트

의존성 설치와 개발 서버 실행은 다음과 같다.

```bash
uv sync
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

SQLite를 사용하는 테스트는 별도 인프라 없이 바로 실행할 수 있다.

```bash
DATABASE_URL=sqlite:///:memory:  \
SECRET_KEY=local-test-secret-key \
ENVIRONMENT=test \
uv run pytest
```

PostgreSQL을 대상으로 하는 테스트는 `docker-compose.test.yml`로 준비된 컨테이너를 사용한다. 이 컴포즈 파일이 띄우는 테스트 데이터베이스 이름은 `bngdrasil_test`다.

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from bifrost-test
```

CI(`.github/workflows/ci.yml`)도 같은 스키마(`tests/fixtures/init_test_db.sql`)를 PostgreSQL과 SQLite 양쪽에 적용해서 두 백엔드 모두에서 테스트를 돌린다.

포매팅과 린트는 다음 명령으로 확인한다.

```bash
uv run black --check .
uv run isort --check-only .
uv run flake8 src tests
uv run mypy src
```

Docker 이미지는 멀티스테이지로 빌드되며, 최종 런타임 이미지는 non-root 사용자(`bifrost`, uid 10001)로 `python -m src.main`을 실행한다. 이 진입점은 `HOST`, `PORT`, `FORWARDED_ALLOW_IPS`를 애플리케이션이 사용하는 것과 같은 `Settings` 객체에서 읽으므로, 컨테이너 명령과 애플리케이션 설정이 서로 어긋날 일이 없다. 또한 서비스 등록부가 프로세스 메모리 안의 스냅숏이라는 제약 때문에 워커 수는 항상 1로 고정되어 있다.

```bash
docker build -t bifrost .
docker run -p 8000:8000 --env-file .env bifrost
```

## 운영 배포 (GitHub Actions)

`main` 브랜치에 커밋이 반영되면 먼저 `.github/workflows/ci.yml`이 실행되고, 그 실행이 성공으로 끝났을 때에만 `.github/workflows/release.yml`이 이어서 실행되어 컨테이너 이미지를 빌드하고 운영 VM2의 gateway 컨테이너를 교체한다. release 워크플로는 더 이상 자체 테스트 job을 가지고 있지 않으며, 전체 테스트 행렬과 린트, 보안 점검은 모두 `ci.yml`이 담당한다.

### 트리거와 CI 연동

`ci.yml`은 `main`과 `dev` 브랜치 push, 그리고 `main`을 대상으로 하는 pull request에서 실행된다. release는 이 가운데 `main` push에서 시작된 CI 실행을 `workflow_run` 이벤트로 넘겨받는다.

```
main 브랜치에 push
        │
        ▼
  CI (ci.yml)
  ├─ test      : Python 3.12 / 3.13 행렬에서 PostgreSQL과 SQLite를 대상으로 pytest 실행
  ├─ lint      : black, isort, flake8, mypy 실행
  └─ security  : bandit, pip-audit 실행
        │
        ├─ 세 job 가운데 하나라도 실패하면 실행 결론이 failure가 된다.
        │      └─ Release의 plan job이 건너뛰어지고, build와 deploy도 실행되지 않는다.
        │
        └─ 세 job이 모두 성공하면 실행 결론이 success가 된다.
               │
               ▼
        Release (release.yml)
        plan ──→ build ──→ deploy (production 환경)
```

GitHub는 실행에 포함된 모든 job이 성공했을 때에만 워크플로 실행의 결론을 `success`로 기록한다. `ci.yml`의 세 job은 별도의 조건 없이 항상 실행되므로, 결론이 `success`라는 사실은 곧 test와 lint, security가 같은 커밋에서 모두 통과했다는 뜻이다. 따라서 결과를 한 번 더 모으는 집계 job을 `ci.yml`에 추가하지 않았다. 다만 앞으로 `ci.yml`에 `if` 조건이나 `continue-on-error`가 붙은 job을 추가한다면 이 전제가 깨지므로, 그런 변경을 할 때에는 집계 job을 두는 방안을 함께 검토해야 한다.

release가 다루는 커밋은 언제나 `github.event.workflow_run.head_sha`이다. `workflow_run` 이벤트에서 `github.sha`는 이벤트가 전달된 시점의 기본 브랜치 최신 커밋을 가리키기 때문에, CI가 실제로 검증한 커밋과 어긋날 수 있다. 소스 checkout과 `sha-<짧은 커밋 해시>` 이미지 태그, 이미지 라벨의 revision 값은 모두 이 `head_sha`를 기준으로 삼는다.

`workflow_run`으로 시작된 실행은 기본 브랜치에 정의된 내용을 따라 동작하며, 이때 secrets와 쓰기 권한이 있는 토큰을 사용할 수 있다. CI를 유발한 쪽이 fork의 pull request였더라도 이 점은 달라지지 않는다. 게다가 `branches: [ main ]` 필터는 CI 실행의 head 브랜치 이름만 비교하므로, fork 쪽 브랜치 이름이 `main`이면 이 필터를 그대로 통과한다. 그래서 `plan` job의 `if` 조건에서 `workflow_run.event == 'push'`와 `workflow_run.head_repository.full_name == github.repository`를 함께 확인하여, 이 저장소의 `main` push에서 시작된 실행만 배포까지 이어지도록 막아 두었다.

### 워크플로 구성

워크플로는 다음 세 개의 job으로 이루어져 있다.

| job | 실행 환경 | 하는 일 |
| --- | --- | --- |
| `plan` | `ubuntu-latest` | 배포 대상 커밋을 확정하고, 새 이미지를 빌드할지 아니면 이미 올라가 있는 태그를 그대로 배포할지 결정한다. 수동 실행으로 새 코드를 빌드하는 경우에는 같은 커밋의 CI 성공 여부도 이 job에서 확인한다. |
| `build` | `ubuntu-24.04-arm` | `ghcr.io/bngdrasil/bifrost` 이미지를 `linux/arm64`로 빌드하여 push한다. 태그는 `sha-<짧은 커밋 해시>`와 `main` 두 가지이고, 이후 단계에는 digest로 고정된 참조를 넘긴다. |
| `deploy` | `ubuntu-latest` | `production` 환경에서 VM2에 SSH로 접속하여 `sudo /opt/bnbong/deploy-image.sh gateway <이미지 참조>`를 실행하고, 그 뒤에 공개 엔드포인트로 smoke 확인을 한 번 수행한다. |

`deploy` job에는 `concurrency: vm2-deploy` 그룹이 걸려 있다. VM2에는 compose 프로젝트가 하나뿐이므로, 두 개의 배포가 동시에 컨테이너를 교체하지 않도록 뒤에 들어온 실행을 취소하지 않고 대기시킨다.

배포 이후의 smoke 확인은 `curl -fsS https://api.bnbong.com/health`를 한 번 호출하는 방식이다. VM1 Nginx의 `api.bnbong.com` 서버 블록에서 `location /`이 gateway upstream으로 향하므로, 이 요청 하나로 Cloudflare와 Nginx, Bifrost까지 이어지는 경로 전체를 확인할 수 있다. 컨테이너 자체의 `/health`와 `/ready` 확인은 그 앞 단계에서 `deploy-image.sh`가 이미 수행한다.

실제 컨테이너 교체는 Baedalus 저장소가 제공하는 `deploy-image.sh`가 담당한다. 이 스크립트는 이미지를 pull하고, 직전 이미지를 `rollback/<컨테이너>:<UTC 시각>`으로 태그해 두고, `/opt/bnbong/.env`의 `GATEWAY_IMAGE` 값을 갱신한 뒤 `docker compose up -d --no-deps gateway`를 실행하며, health 확인에 실패하면 직전 이미지로 스스로 되돌리고 0이 아닌 코드로 종료한다. 워크플로는 이 종료 코드만 신뢰하며, 배포 절차 자체를 다시 구현하지 않는다.

### 수동 실행(`workflow_dispatch`)의 두 가지 경로

수동 실행은 목적에 따라 서로 다른 규칙을 적용받는다.

1. `image_tag`를 입력한 경우에는 롤백 전용 예외 경로로 동작한다. 이미 GHCR에 올라가 있는 이미지를 그대로 다시 배포할 뿐이고, 새로 빌드하지 않는다. 그 이미지는 과거에 CI 게이트를 통과한 커밋에서 만들어진 산출물이므로, CI 결과를 다시 조회하지 않는다. 장애가 발생했을 때 곧바로 이전 버전으로 되돌릴 수 있도록 남겨 둔 예외이다.
2. `image_tag`를 비워 둔 채 수동으로 실행한 경우에는 새 코드를 빌드하는 경로이므로, `workflow_run` 경로와 같은 기준을 적용한다. `plan` job이 GitHub Actions API에 `repos/<owner>/<repo>/actions/workflows/ci.yml/runs?head_sha=<대상 커밋>`을 조회하여, 바로 그 커밋에 대한 CI 실행이 존재하고 모두 완료되었으며 전부 `success`로 끝났는지 확인한다. 아직 끝나지 않은 실행이 있거나, 실패나 취소로 끝난 실행이 하나라도 있거나, 성공 기록이 아예 없으면 어떤 조건이 어긋났는지 밝히는 오류 메시지와 함께 중단된다. 다른 커밋에서 가장 최근에 성공한 CI 실행을 대신 인정하는 동작은 의도적으로 넣지 않았다.

이 조회를 수행하기 위해 `plan` job에 `actions: read` 권한을 부여했다.

### 필요한 secrets와 environment

저장소 설정에서 다음 값을 미리 등록해야 한다.

| 이름 | 종류 | 설명 |
| --- | --- | --- |
| `VM2_SSH_PRIVATE_KEY` | secret | VM2 배포 계정의 SSH 개인키 전문이다. |
| `VM2_SSH_KNOWN_HOSTS` | secret | VM2의 호스트 키 항목이다. 워크플로가 `StrictHostKeyChecking=yes`로 접속하므로 이 값이 없으면 연결이 거부된다. |
| `VM2_HOST` | secret | VM2의 접속 주소이다. |
| `VM2_USER` | secret (선택) | 접속 계정 이름이며, 등록하지 않으면 `ubuntu`를 사용한다. |
| `production` | environment | `deploy` job이 사용하는 환경이다. 수동 승인이 필요하면 이 환경에 required reviewers를 지정한다. |

GHCR에 push할 때 쓰는 자격 증명은 별도로 등록하지 않는다. `build` job이 `packages: write` 권한으로 발급된 `GITHUB_TOKEN`을 그대로 사용한다.

### 최초 1회 준비

1. 첫 push가 끝나면 GitHub의 Packages 화면에서 `bifrost` 패키지를 열고, 가시성을 public으로 변경한다. 이 설정을 마쳐야 VM2가 `docker login` 없이 이미지를 pull할 수 있다. 같은 화면에서 이 저장소에 `Write` 권한을 연결해 두어야 이후 push가 계속 성공한다.
2. Baedalus 저장소의 `deploy-image.sh`를 VM2의 `/opt/bnbong/deploy-image.sh` 경로에 설치하고 실행 권한을 부여한다. 워크플로는 이 스크립트를 `sudo`로 호출하므로, 배포 계정이 해당 명령을 비밀번호 없이 실행할 수 있어야 한다.
3. `/opt/bnbong/.env`에 `GATEWAY_IMAGE` 항목이 존재하는지 확인한다. compose 파일이 이 변수로 이미지를 고르며, 값이 비어 있으면 로컬 빌드 이미지인 `bnbong-gateway`로 되돌아간다.
4. 저장소 설정에서 `production` 환경을 만들고, 필요한 보호 규칙과 위의 secrets를 등록한다.

### 롤백 방법

Actions 화면에서 `Release` 워크플로를 선택한 뒤 `Run workflow`를 누르고, `image_tag`에 되돌리려는 커밋의 태그를 `sha-1a2b3c4` 형식으로 입력한다. `image_tag`를 지정하면 `build` job을 건너뛰고 그 태그를 그대로 배포한다. `skip_build`를 체크하는 경우에도 `image_tag`는 반드시 함께 입력해야 하며, 비어 있으면 `plan` job이 오류로 중단된다. 앞의 "수동 실행의 두 가지 경로"에서 설명한 대로, 이 경로는 CI 결과를 다시 확인하지 않는 예외에 해당한다.

다만 이 저장소의 롤백에는 아래 "운영 배포 시 주의 사항"에 적힌 제약이 그대로 적용된다. 인증 없는 관리 엔드포인트가 남아 있는 과거 이미지로 되돌리는 경우, Nginx의 차단 규칙이 유지되고 있는지 먼저 확인해야 한다.

VM2에서 직접 되돌려야 하는 상황이라면 `deploy-image.sh`가 남겨 둔 `rollback/vm2-gateway:<UTC 시각>` 태그를 사용할 수 있다. 다만 이 경로로 되돌린 내용은 GitHub 쪽 기록에 남지 않으므로, 이후에 `image_tag`를 사용한 배포로 상태를 맞추어 두는 편이 좋다.

### 실제 Actions에서 확인해야 할 항목

지금까지 이 구성은 YAML 파싱과 actionlint 검사, 워크플로에 포함된 셸 스크립트의 문법 검사까지만 마쳤다. 다음 항목은 실제 GitHub Actions 실행으로 확인해야 한다.

- 단위 테스트는 통과하지만 lint 또는 security가 실패하는 커밋을 `main`에 push했을 때, Release의 `plan` job이 건너뛰어지고 `build`와 `deploy`가 전혀 실행되지 않는지 확인해야 한다.
- 세 job이 모두 성공한 커밋에서는 Release가 이어서 실행되고, 빌드된 이미지의 `sha-` 태그가 CI가 검증한 커밋의 짧은 해시와 일치하는지 확인해야 한다.
- `image_tag`를 비워 둔 채 수동으로 실행했을 때, CI가 실패했거나 아직 끝나지 않은 커밋에서는 `plan` job이 오류 메시지와 함께 중단되는지 확인해야 한다.
- `production` 환경에 설정한 승인 규칙과 배포 브랜치 정책이 실제 실행에서 적용되는지 확인해야 한다.

## 운영 배포 시 주의 사항

과거 버전에 있던 인증 없는 `/api/v1/admin/services` 등록·삭제 엔드포인트는 이번 버전에서 완전히 제거되었다. 그 경로를 Nginx 등에서 별도로 막아 두었다면, 이번 배포 이후에도 그 차단 규칙은 그대로 남겨 두어야 한다. 이 버전에서 새로 필수가 된 환경 변수는 `ALLOWED_HOSTS`이며, production 환경에서 이 값이 비어 있으면 프로세스가 아예 시작되지 않으므로 배포 전에 반드시 채워야 한다. 만약 이번 배포를 롤백해야 하는 상황이 오더라도, 예전 버전에는 인증 없는 관리 엔드포인트가 남아 있으므로 Nginx의 차단 규칙은 롤백 여부와 무관하게 계속 유지해야 한다.

## 알려진 제한과 후속 과제

- 프록시는 buffered 방식만 지원하며, 진짜 스트리밍이나 서버 전송 이벤트를 필요로 하는 업스트림은 지원 범위 밖에 있다.
- 업스트림 응답 본문의 크기에는 별도의 상한이 없다. 요청 본문에만 `MAX_REQUEST_BODY_BYTES` 제한이 적용된다.
- 서비스 health 상태는 관리자가 `health-check-all`을 호출하거나 서비스를 등록·수정할 때만 갱신된다. 주기적으로 알아서 다시 확인하는 스케줄러는 아직 없으므로, 마지막 확인 이후 실제로 상태가 바뀐 서비스가 있어도 그 사실이 자동으로 반영되지 않을 수 있다.
- 서비스 등록부는 프로세스 하나에 대한 메모리 스냅숏이며, 여러 복제본 사이에서 등록부를 동기화하는 기능은 없다. 인스턴스를 여러 개 띄운다면 각 인스턴스가 서로 다른 시점의 등록부를 가질 수 있다는 점, 그리고 rate limiter도 인스턴스별로 독립적으로 동작한다는 점을 함께 감안해야 한다.
