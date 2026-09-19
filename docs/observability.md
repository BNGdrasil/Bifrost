# 관측

프로브 엔드포인트와 Prometheus 지표, rate limiter의 적용 범위를 설명합니다.

## 프로브

`/health`는 liveness 프로브입니다. 프로세스가 요청을 처리할 수 있는 상태이기만 하면 항상 200을 반환하며, 데이터베이스나 등록부 상태는 확인하지 않습니다.

`/ready`는 readiness 프로브입니다. 데이터베이스 연결 확인과 서비스 등록부의 준비 상태를 함께 검사해서, 둘 중 하나라도 실패하면 503을 반환합니다. 응답 본문에는 데이터베이스 상태와 등록부 상태, 등록된 서비스 수가 들어가고, 실패한 경우에는 그 원인 문자열도 함께 들어갑니다.

## 지표

`/metrics`는 Prometheus exposition 형식으로 다음 지표를 노출합니다.

- `http_requests_total{method, service, status_class}`: 게이트웨이가 처리한 HTTP 요청 수입니다. `service` 레이블은 프록시된 요청이면 등록된 서비스 이름이 되고, 그 외의 게이트웨이 자체 엔드포인트는 `gateway`가 됩니다. 등록되지 않은 서비스로 향한 요청은 `unknown`으로 집계합니다. `method`는 표준 HTTP 메서드 집합으로만 값이 제한되며, 그 밖의 값은 `OTHER`로 묶입니다. `status_class`는 `2xx`나 `4xx`처럼 앞자리 하나로 묶은 값입니다.
- `http_request_duration_seconds{method, service}`: 같은 레이블 조합으로 측정한 요청 처리 시간 히스토그램입니다.

경로 자체를 레이블로 쓰지 않는 이유는, 등록된 서비스 수만큼만 카디널리티가 늘어나게 하기 위해서입니다. 계측 미들웨어는 `/health`와 `/ready`, `/metrics`를 포함한 모든 요청에 대해 동작하므로, 이 경로들도 `service=gateway`로 집계됩니다.

## Rate limiter

Rate limiter는 각 프로세스 내부의 메모리에만 상태를 들고 있는 고정 윈도우 방식입니다. 그래서 게이트웨이를 여러 인스턴스로 복제하면 그 제한은 인스턴스별로 독립적으로 적용되며, 인스턴스 사이에 공유되지 않습니다. `RATE_LIMIT_EXEMPT_PATHS`에 지정한 경로는 제한 대상에서 제외됩니다.

## 로그

로그는 `structlog`로 구조화된 JSON 형태로 표준 출력에 남습니다. 저장과 조회는 Loki와 Grafana가 담당합니다.
