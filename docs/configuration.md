# 설정

Bifrost가 읽는 환경 변수와 production 환경에서 적용되는 검증 규칙을 설명합니다.

Bifrost는 환경 변수로 설정을 받습니다. `env.example`을 복사해서 `.env`로 만들고 값을 채우면 됩니다. `ALLOWED_HOSTS`나 `RATE_LIMIT_EXEMPT_PATHS`, `SERVICE_URL_ALLOWED_HOSTS`처럼 목록 형태인 값은 쉼표로 구분한 문자열(`a,b,c`)과 JSON 배열(`["a", "b"]`) 표기를 모두 받아들입니다.

값이 비어 있는 환경 변수는 설정하지 않은 것과 같게 취급합니다. compose 파일이 정의되지 않은 변수를 `ENABLE_METRICS=`처럼 빈 값으로 펼치더라도, 파싱에 실패해서 프로세스가 기동하지 못하는 대신 기본값으로 되돌아갑니다.

## production 검증 규칙

`ENVIRONMENT=production`일 때는 다음 조건을 만족해야 하며, 어긋나면 프로세스가 시작하지 않습니다.

| 변수 | 요구 사항 |
| --- | --- |
| `SECRET_KEY` | 값이 있어야 하고, 32자 이상이어야 하며, `env.example`에 들어 있는 예시 값과 같으면 안 됩니다. |
| `DATABASE_URL` | 비어 있으면 안 됩니다. |
| `ALLOWED_HOSTS` | 비어 있으면 안 되고, `*`를 포함해도 안 됩니다. 두 경우 모두 호스트 헤더 검사를 조용히 끄는 결과가 되므로, production에서는 실제로 제공하는 호스트 이름을 명시해야 합니다. |

`BACKEND_CORS_ORIGINS`에 `*`가 들어 있으면 기동은 되지만 경고를 남깁니다. 브라우저가 자격 증명을 포함한 요청을 거부하기 때문입니다.

production이 아닌 환경에서는 `ALLOWED_HOSTS`가 비어 있으면 경고와 함께 `["*"]`로 되돌아가고, `SECRET_KEY`가 비어 있으면 프로세스마다 임시 키를 무작위로 생성합니다. `DATABASE_URL`이 비어 있으면 기본 접속 문자열을 사용합니다.

## 주요 환경 변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `SECRET_KEY` | (비어 있음, production 외에는 프로세스마다 무작위 생성) | 서명 등에 쓰이는 비밀 값입니다. |
| `ENVIRONMENT` | `development` | `development`와 `production`, `test` 중 하나입니다. |
| `DEBUG` | `false` | 디버그 모드 여부입니다. |
| `LOG_LEVEL` | `INFO` | 로그 레벨입니다. |
| `HOST` | `0.0.0.0` | 프로세스가 바인딩하는 주소입니다. |
| `PORT` | `8000` | 프로세스가 바인딩하는 포트입니다. |
| `DATABASE_URL` | (비어 있음, 기본값은 `postgresql://bnbong:password@postgres:5432/bngdrasil`) | 서비스 등록부가 저장되는 PostgreSQL 접속 문자열입니다. |
| `ALLOWED_HOSTS` | (비어 있음, production 외에는 `["*"]`로 대체) | `TrustedHostMiddleware`가 허용하는 호스트 헤더 목록입니다. |
| `BACKEND_CORS_ORIGINS` | `["*"]` | CORS 미들웨어가 허용하는 origin 목록입니다. `CLIENT_ORIGIN`에 값이 있으면 이 목록에 추가됩니다. |
| `CLIENT_ORIGIN` | (비어 있음) | CORS 허용 목록에 덧붙일 origin 하나를 지정합니다. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | uvicorn이 `X-Forwarded-*` 헤더를 신뢰할 리버스 프록시의 주소입니다. |
| `RATE_LIMIT_PER_MINUTE` | `60` | 클라이언트 하나당 분당 허용 요청 수입니다. |
| `RATE_LIMIT_EXEMPT_PATHS` | `/health,/ready,/metrics` | rate limit 대상에서 제외되는 경로입니다. |
| `MAX_REQUEST_BODY_BYTES` | `10485760` | 프록시 요청 본문의 최대 크기입니다. |
| `PROXY_TIMEOUT_SECONDS` | `30` | 업스트림 요청의 기본 타임아웃입니다. |
| `PROXY_MAX_CONNECTIONS` | `100` | 업스트림으로 나가는 커넥션 풀의 최대 연결 수입니다. |
| `SERVICE_URL_ALLOWED_HOSTS` | (비어 있음) | 값이 있으면 이 목록에 있는 호스트만 서비스로 등록할 수 있습니다. |
| `SERVICE_URL_DENIED_HOSTS` | (비어 있음) | 이 목록에 있는 호스트는 항상 등록이 거절됩니다. |
| `AUTH_SERVER_URL` | `http://auth-server:8001` | Bidar 인증 서버의 base URL입니다. |
| `AUTH_SERVER_USERS_PATH` | `/users` | Bidar의 사용자 관리 API 경로입니다. 사용자 관리 프록시는 `AUTH_SERVER_URL`에 이 값을 이어 붙여서 요청을 보냅니다. |
| `ENABLE_METRICS` | `true` | 지표 수집 여부입니다. |
