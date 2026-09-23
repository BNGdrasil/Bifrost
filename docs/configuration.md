# 설정

Bifrost가 읽는 환경 변수와 production 환경에서 적용되는 검증 규칙을 설명합니다.

Bifrost는 환경 변수로 설정을 받습니다. `env.example`을 복사해서 `.env`로 만들고 값을 채우면 됩니다. `ALLOWED_HOSTS`나 `RATE_LIMIT_EXEMPT_PATHS`, `SERVICE_URL_ALLOWED_HOSTS`처럼 목록 형태인 값은 쉼표로 구분한 문자열(`a,b,c`)과 JSON 배열(`["a", "b"]`) 표기를 모두 받아들입니다.

값이 비어 있는 환경 변수는 설정하지 않은 것과 같게 취급합니다. compose 파일이 정의되지 않은 변수를 `ENABLE_METRICS=`처럼 빈 값으로 펼치더라도, 파싱에 실패해서 프로세스가 기동하지 못하는 대신 기본값으로 되돌아갑니다. `PROMETHEUS_URL`과 `ALERTMANAGER_URL`처럼 값을 넣지 않아도 되는 주소 설정도 공백만 들어 있으면 설정하지 않은 것으로 봅니다. 다만 값이 들어 있다면 `http`나 `https` 스킴과 호스트를 갖춘 주소여야 하며, 그렇지 않으면 기동 시점에 검증 오류로 중단합니다. 잘못된 주소를 실제로 호출하는 순간까지 미루지 않기 위해서입니다.

목록 형태 설정 중에서 `PROXY_BLOCKED_UPSTREAM_PATHS`와 `SERVICE_URL_ALLOWED_HOSTS`, `SERVICE_URL_DENIED_HOSTS`는 보안 정책을 담고 있기 때문에 조금 다르게 동작합니다. 세 값은 공백이나 쉼표만 들어 있어도 빈 목록으로 받아들이지 않고 선언된 기본값을 그대로 적용하며, 값이 적용되지 않았다는 사실을 경고로 남깁니다. 이 정책들을 실제로 끄려면 `[]`를 명시해야 합니다. 뒤의 두 값은 기본값 자체가 빈 목록이라서 대체된 결과를 값만 보고는 구분할 수 없으므로, 변수가 적용되지 않았다는 사실은 경고 문구로만 드러납니다.

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
| `PROXY_BLOCKED_UPSTREAM_PATHS` | `/metrics` | 프록시가 업스트림으로 전달하지 않는 경로 목록입니다. 목록에 있는 경로와 그 하위 경로로 향하는 요청은 404를 반환합니다. 값이 비어 있거나 공백과 쉼표만 있으면 기본값이 그대로 적용되므로, 차단을 실제로 끄려면 `[]`를 명시해야 합니다. 이 필드는 다른 목록 설정과 달리 이렇게 동작합니다. 정의되지 않은 변수가 전개되어 생긴 빈 값을 "아무것도 차단하지 않는다"로 해석하면, 업스트림의 운영 엔드포인트가 조용히 공개되기 때문입니다. 판단 기준은 [게이트웨이 동작](gateway.md) 문서에서 설명합니다. |
| `SERVICE_URL_ALLOWED_HOSTS` | (비어 있음) | 값이 있으면 이 목록에 있는 호스트만 서비스로 등록할 수 있습니다. 공백이나 쉼표만 들어 있는 값은 무시하고 기본값을 적용하며, 그 사실을 경고로 남깁니다. |
| `SERVICE_URL_DENIED_HOSTS` | (비어 있음) | 이 목록에 있는 호스트는 항상 등록이 거절됩니다. 공백이나 쉼표만 들어 있는 값을 다루는 방식은 위와 같습니다. |
| `AUTH_SERVER_URL` | `http://auth-server:8001` | Bidar 인증 서버의 base URL입니다. |
| `AUTH_SERVER_USERS_PATH` | `/users` | Bidar의 사용자 관리 API 경로입니다. 사용자 관리 프록시는 `AUTH_SERVER_URL`에 이 값을 이어 붙여서 요청을 보냅니다. |
| `ENABLE_METRICS` | `true` | 지표 수집 여부입니다. |
| `PROMETHEUS_URL` | (비어 있음) | 관리자 관측 요약이 질의할 Prometheus의 base URL입니다. VM2 배포에서는 `http://prometheus:9090`을 사용합니다. 값이 없으면 `/admin/api/observability` 아래의 엔드포인트가 501을 반환합니다. |
| `ALERTMANAGER_URL` | (비어 있음) | 알림 요약이 억제 상태를 확인할 Alertmanager의 base URL입니다. VM2 배포에서는 `http://alertmanager:9093`을 사용합니다. 값이 없으면 알림 목록은 그대로 반환하고 `silenced`와 `inhibited`만 `null`로 남습니다. |
| `OBSERVABILITY_QUERY_TIMEOUT_SECONDS` | `2.5` | 관측 백엔드 호출 하나에 허용하는 시간입니다. 연결과 전송, 응답 수신 같은 단계마다 따로 적용하는 값이 아니라, 호출 한 번이 끝날 때까지의 전체 상한입니다. Prometheus 호출이 이 시간을 넘기면 해당 엔드포인트가 502를 반환합니다. 반면 Alertmanager 호출이 이 시간을 넘기면 요청 자체는 200으로 끝나고, 응답의 `alertmanager.available`이 `false`가 되며 `alertmanager.error`에 그 이유가 들어갑니다. 0 이하의 값과 `nan`이나 `inf` 같은 유한하지 않은 값은 기동 시점에 검증 오류로 거절합니다. |
