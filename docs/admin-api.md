# 관리자 API

`/admin/api` 아래에 있는 관리자 엔드포인트의 권한 규칙과 각 엔드포인트의 동작을 설명합니다.

관리자 API의 모든 엔드포인트는 `Authorization: Bearer <access-token>` 헤더를 요구하며, 이 토큰은 Bidar가 발급한 access 토큰이어야 합니다. 각 엔드포인트는 자신에게 필요한 최소 역할을 먼저 명시하고, 실제 판정은 Bidar의 `/rbac/verify-permission` 응답에 맡깁니다. Bidar가 401이나 403을 돌려주면 Bifrost도 같은 상태 코드로 응답하고, Bidar에 연결할 수 없으면 503을 반환합니다.

## 서비스 관리

`/admin/api/services` 아래의 모든 엔드포인트는 admin 이상의 역할을 요구합니다.

| 경로 | 메서드 | 설명 |
| --- | --- | --- |
| `/admin/api/services` | GET, POST | 서비스 목록을 조회하고 새 서비스를 등록합니다. |
| `/admin/api/services/{id}` | GET, PUT, DELETE | 단건 조회와 수정, 삭제를 수행합니다. |
| `/admin/api/services/{id}/health` | GET | 데이터베이스에 저장되어 있는 마지막 health check 결과를 그대로 읽어서 반환합니다. 이 요청은 업스트림 서비스를 호출하지 않으므로, 실시간으로 검사하려면 `/admin/api/services/health-check-all`을 사용해야 합니다. |
| `/admin/api/services/reload` | POST | 등록부 재적재를 수동으로 다시 실행합니다. |
| `/admin/api/services/health-check-all` | POST | 등록된 모든 서비스에 health check 요청을 보내고 그 결과를 데이터베이스에 기록합니다. |
| `/admin/api/services/stats` | GET | 서비스 통계를 반환합니다. |

서비스의 생성과 조회, 수정, 삭제는 모두 데이터베이스에 반영된 다음 등록부를 바로 다시 불러오는 방식으로 동작합니다. 따라서 관리자 API를 통한 변경이 이 요청과 응답 안에서 게이트웨이의 라우팅 표에 곧바로 반영됩니다. 서비스를 등록할 때 넘기는 URL과 health check 경로는 목적지 정책 검사를 통과해야 하며, 그 내용은 [게이트웨이 동작](gateway.md) 문서에서 설명합니다.

### 등록부 재적재 실패를 알리는 방법

데이터베이스 변경은 등록부를 다시 불러오기 전에 이미 확정됩니다. 그래서 재적재가 실패하면 레코드는 저장되었지만 라우팅 표는 이전 상태에 머물러 있는 상황이 생깁니다. 예전에는 이 실패를 로그에만 남기고 200이나 201을 그대로 돌려주었기 때문에, 호출자는 게이트웨이가 아직 알지 못하는 서비스로 요청을 넘길 수 있다고 잘못 판단했습니다.

지금은 생성과 수정, 삭제 응답이 다음 두 필드를 함께 싣습니다.

- `registry_reloaded`: 등록부 재적재가 성공했으면 `true`이고, 실패했으면 `false`입니다.
- `registry_error`: 실패했을 때 그 원인 문자열이 들어가고, 성공했으면 `null`입니다.

재적재가 실패한 요청은 상태 코드도 `207 Multi-Status`로 바뀝니다. 저장은 성공했고 라우팅 표 갱신은 실패했으므로, 한쪽만 가리키는 2xx나 5xx보다 두 결과가 서로 달랐다는 사실을 그대로 나타내는 편이 정확하기 때문입니다. 다만 207도 2xx에 속하기 때문에, 성공 여부만 확인하는 호출자는 이 응답을 그대로 성공으로 처리합니다. 재적재가 실패했다는 사실을 상태 코드로 알아차리려면 200이나 201과 207을 구분해서 확인하거나, 응답 본문의 `registry_reloaded` 필드를 읽어야 합니다. 데이터베이스 변경은 되돌리지 않습니다. 되돌리려면 재적재가 실패한 것과 같은 이유로 실패할 수 있는 쓰기를 한 번 더 수행해야 하고, 운영자가 방금 요청한 레코드를 버리는 결과가 되기 때문입니다. 이 상태를 해소하려면 `POST /admin/api/services/reload`를 다시 호출해야 합니다.

삭제는 204 대신 200으로 응답하며 본문에 `service_id`와 `service_name`, 위의 두 필드를 담습니다. 본문이 없는 204에는 재적재 결과를 적을 자리가 없기 때문입니다.

생성과 수정 응답은 기존 `ServiceRead` 필드를 모두 그대로 유지한 채 위의 두 필드를 덧붙인 형태이므로, 응답을 `ServiceRead`로 파싱하던 클라이언트는 그대로 동작합니다.

## 사용자 관리 (Bidar 프록시)

사용자 레코드는 Bifrost가 아니라 Bidar가 소유합니다. 그래서 `/admin/api/users` 아래의 요청은 자신의 역할 검사를 통과한 다음 호출자의 `Authorization` 헤더를 그대로 들고 Bidar로 넘어가며, Bidar가 내려준 상태 코드와 오류 메시지를 그대로 되돌려줍니다. 요청 대상 주소는 `AUTH_SERVER_URL`과 `AUTH_SERVER_USERS_PATH`를 이어 붙여서 만듭니다.

| 경로 | 메서드 | 필요 역할 |
| --- | --- | --- |
| `/admin/api/users` | GET | admin |
| `/admin/api/users/{id}` | GET | admin |
| `/admin/api/users` | POST | super_admin |
| `/admin/api/users/{id}` | PATCH | super_admin |
| `/admin/api/users/{id}` | DELETE | super_admin |
| `/admin/api/users/{id}/activate` | PUT | admin |
| `/admin/api/users/{id}/deactivate` | PUT | admin |
| `/admin/api/users/{id}/reset-password` | POST | admin |

조회는 admin 이상이면 되지만, 계정을 새로 만들거나 정보를 바꾸거나 삭제하는 요청은 super_admin만 호출할 수 있습니다. `POST /admin/api/users/{id}/reset-password`는 아직 구현되어 있지 않으며 항상 501을 반환하므로, 비밀번호 재설정은 Bidar 쪽 플로우를 직접 사용해야 합니다.

## 시스템 설정

`GET /admin/api/settings`는 현재 실행 중인 프로세스의 유효 설정 값을 admin 권한으로 읽을 수 있게 해 주지만, 이 값들은 실행 중에 바꿀 수 없습니다. `PUT /admin/api/settings`는 super_admin에게도 501을 반환합니다. 설정을 바꾸려면 배포 환경의 환경 변수를 수정하고 프로세스를 재시작해야 합니다.

## 로그

Bifrost는 로그 인덱스를 직접 갖고 있지 않으므로 `GET /admin/api/logs`와 `GET /admin/api/logs/audit`는 admin 권한이 있어도 항상 501을 반환합니다. 로그는 구조화된 형태로 표준 출력에 기록되고 있으며, 실제 조회는 Loki에 적재된 로그를 Grafana로 확인하는 방식을 사용해야 합니다.

## 관측 요약

`/admin/api/observability` 아래의 두 엔드포인트는 admin 이상의 역할을 요구하며, 모니터링 네트워크의 Prometheus와 Alertmanager에서 정해진 내용만 읽어 옵니다. 호출자가 PromQL을 넘길 수 있는 경로는 없습니다. 질의 문자열은 코드에 상수로 명시되어 있으므로, 이 엔드포인트가 인증 없는 질의 프록시로 바뀔 여지가 없습니다.

| 경로 | 메서드 | 설명 |
| --- | --- | --- |
| `/admin/api/observability/backups` | GET | 구성 요소별 백업 상태를 요약해서 반환합니다. |
| `/admin/api/observability/alerts` | GET | 지금 발화 중인 알림을 요약해서 반환합니다. |

두 엔드포인트는 모두 `PROMETHEUS_URL`을 필요로 합니다. 이 값이 설정되어 있지 않으면 로그 엔드포인트와 같은 방식으로 501을 반환하며, 없는 데이터를 0이나 빈 값으로 꾸며서 내려주지 않습니다. Prometheus 질의가 실패하거나 시간 안에 끝나지 않으면 502를 반환하고 `detail`에 그 이유를 담습니다. 이 호출은 요청마다 별도의 HTTP 클라이언트를 만들어서 `OBSERVABILITY_QUERY_TIMEOUT_SECONDS` 안에 끝나도록 제한하므로, 모니터링 스택이 멈춰 있어도 프록시나 다른 관리자 엔드포인트에는 영향을 주지 않습니다.

### 백업 요약

`GET /admin/api/observability/backups`는 백업 스크립트가 node exporter의 textfile collector로 내보내는 `bngdrasil_backup_last_success_timestamp_seconds`와 `bngdrasil_backup_last_run_timestamp_seconds`, `bngdrasil_backup_last_run_status`, `bngdrasil_backup_unshipped_total`을 한 번의 질의로 읽어서 `component`와 `instance`, `job` 라벨의 조합별로 묶어 줍니다. 세 라벨을 함께 묶음의 기준으로 삼는 이유는, 같은 이름의 구성 요소를 두 호스트가 각각 보고하는 경우에 한쪽 결과가 다른 쪽 결과를 덮어쓰지 않도록 하기 위해서입니다. 그래서 같은 `component` 값이 `instance`만 다른 여러 항목으로 나타날 수 있습니다. 각 항목에는 `age_seconds`가 함께 들어가며, 이 값은 게이트웨이의 서버 시각을 기준으로 마지막 성공 시각으로부터 몇 초가 지났는지를 계산한 결과입니다.

아직 한 번도 보고되지 않은 항목은 0이 아니라 `null`로 내려갑니다. 예를 들어 오프사이트 전송을 담당하는 `ship` 구성 요소는 미전송 개수를 내보내지 않으므로 `unshipped_total`이 `null`입니다. 여기에 0을 채우면 "보낼 것이 남아 있지 않다"라는 뜻으로 읽히는데, 백업 스크립트는 그런 내용을 보고한 적이 없습니다.

Prometheus가 응답했지만 `bngdrasil_backup_` 계열 시계열을 아직 하나도 갖고 있지 않으면, `components`는 빈 목록이 되고 `available`이 `false`가 되며 `note`에 그 이유가 들어갑니다. 빈 목록을 정상 상태로 오해하지 않도록 하기 위해서입니다.

### 알림 요약

`GET /admin/api/observability/alerts`는 Prometheus의 `/api/v1/alerts`에서 `state`가 `firing`인 알림만 골라서 `alertname`과 `severity`, `instance`, `service`, `job`, `component` 라벨과 `activeAt`, `summary` annotation을 반환합니다. `pending` 상태인 알림은 아직 `for` 시간을 채우지 않아 통지 대상도 아니므로 제외합니다. 응답에는 발화 중인 알림의 수를 담은 `firing_count`와 조회 시각을 담은 `queried_at`이 함께 들어갑니다.

응답의 `active_at`은 Prometheus의 `activeAt`을 그대로 옮긴 값입니다. 이 값은 알림이 통지되기 시작한 시각이 아니라, 알림 조건이 처음으로 참이 되어 `for` 대기가 시작된 시각입니다. 예를 들어 `for: 5m`인 규칙이라면 `active_at`은 실제로 발화한 시각보다 5분 앞섭니다.

`ALERTMANAGER_URL`이 설정되어 있으면 Alertmanager의 `/api/v2/alerts`도 조회해서 각 알림에 `silenced`와 `inhibited`를 덧붙입니다. Alertmanager는 Prometheus가 통지할 때 붙이는 external label을 함께 갖고 있으므로, 두 목록은 라벨이 완전히 같은지가 아니라 Alertmanager 쪽 라벨이 규칙이 평가한 라벨을 모두 포함하는지로 대응시킵니다. 이 조건을 만족하는 항목이 여럿이면 발화 중인 알림이 갖고 있지 않은 라벨이 가장 적은 항목, 즉 전달 과정에서 붙은 external label 말고는 더 붙은 것이 없는 항목을 고릅니다. 그렇게 골라도 항목이 둘 이상 남으면, 예를 들어 external label만 서로 다른 항목이 둘 있으면 `silenced`와 `inhibited`를 `null`로 남깁니다. 목록에 먼저 나온 항목을 고르면 Alertmanager가 알림을 나열한 순서가 답을 바꾸게 되는데, 그 순서는 억제 여부와 아무 관계가 없기 때문입니다. 알림이 아직 group wait 안에 있어서 Alertmanager에 도달하지 않은 경우처럼 대응하는 항목이 하나도 없을 때에도 두 필드는 `null`입니다.

Alertmanager 조회가 실패해도 요청 전체가 실패하지는 않습니다. 발화 중인 알림 목록은 Alertmanager 없이도 정확하기 때문입니다. 이때에는 응답의 `alertmanager` 필드가 `{"configured": true, "available": false, "error": "..."}`가 되고, 각 알림의 `silenced`와 `inhibited`는 `null`로 남습니다. 억제 상태를 확인하지 못한 것을 "억제되지 않았다"로 바꾸어 보고하지 않기 위해서입니다. `ALERTMANAGER_URL`을 설정하지 않은 경우에도 같은 이유로 두 필드는 `null`이며, `configured`가 `false`가 됩니다.

## 통계와 null의 의미

`GET /admin/api/services/stats`와 `GET /admin/api/settings/stats/overview`는 admin 이상의 역할을 요구하며, Bifrost가 실제로 계산할 수 있는 값만 채워서 돌려줍니다. 서비스 수와 활성 서비스 수, health 상태별 집계, 등록부의 준비 상태 같은 값은 실제 값이 들어갑니다. 반면 사용자 통계나 API 요청량처럼 Bifrost가 별도로 적재해 두지 않은 값은 임의의 숫자를 만들어내지 않고 `null`로 내려줍니다. 응답에서 `null`이 보인다면 그것은 값이 0이라는 뜻이 아니라, 그 항목을 아직 계산할 수단이 없다는 뜻으로 읽어야 합니다.

## 501을 반환하는 항목 정리

- `POST /admin/api/users/{id}/reset-password`
- `PUT /admin/api/settings`
- `GET /admin/api/logs`
- `GET /admin/api/logs/audit`
- `GET /admin/api/observability/backups` (`PROMETHEUS_URL`이 설정되어 있지 않은 경우에만 해당합니다.)
- `GET /admin/api/observability/alerts` (`PROMETHEUS_URL`이 설정되어 있지 않은 경우에만 해당합니다.)
