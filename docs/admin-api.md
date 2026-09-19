# 관리자 API

`/admin/api` 아래에 있는 관리자 엔드포인트의 권한 규칙과 각 엔드포인트의 동작을 설명합니다.

관리자 API의 모든 엔드포인트는 `Authorization: Bearer <access-token>` 헤더를 요구하며, 이 토큰은 Bidar가 발급한 access 토큰이어야 합니다. 각 엔드포인트는 자신에게 필요한 최소 역할을 먼저 명시하고, 실제 판정은 Bidar의 `/rbac/verify-permission` 응답에 맡깁니다. Bidar가 401이나 403을 돌려주면 Bifrost도 같은 상태 코드로 응답하고, Bidar에 연결할 수 없으면 503을 반환합니다.

## 서비스 관리

`/admin/api/services` 아래의 모든 엔드포인트는 admin 이상의 역할을 요구합니다.

| 경로 | 메서드 | 설명 |
| --- | --- | --- |
| `/admin/api/services` | GET, POST | 서비스 목록을 조회하고 새 서비스를 등록합니다. |
| `/admin/api/services/{id}` | GET, PUT, DELETE | 단건 조회와 수정, 삭제를 수행합니다. |
| `/admin/api/services/{id}/health` | GET | 해당 서비스에 실제로 health check를 수행합니다. |
| `/admin/api/services/reload` | POST | 등록부 재적재를 수동으로 다시 실행합니다. |
| `/admin/api/services/health-check-all` | POST | 등록된 모든 서비스에 health check 요청을 보내고 그 결과를 데이터베이스에 기록합니다. |
| `/admin/api/services/stats` | GET | 서비스 통계를 반환합니다. |

서비스의 생성과 조회, 수정, 삭제는 모두 데이터베이스에 반영된 다음 등록부를 바로 다시 불러오는 방식으로 동작합니다. 따라서 관리자 API를 통한 변경이 이 요청과 응답 안에서 게이트웨이의 라우팅 표에 곧바로 반영됩니다. 서비스를 등록할 때 넘기는 URL과 health check 경로는 목적지 정책 검사를 통과해야 하며, 그 내용은 [게이트웨이 동작](gateway.md) 문서에서 설명합니다.

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

## 통계와 null의 의미

`GET /admin/api/services/stats`와 `GET /admin/api/settings/stats/overview`는 admin 이상의 역할을 요구하며, Bifrost가 실제로 계산할 수 있는 값만 채워서 돌려줍니다. 서비스 수와 활성 서비스 수, health 상태별 집계, 등록부의 준비 상태 같은 값은 실제 값이 들어갑니다. 반면 사용자 통계나 API 요청량처럼 Bifrost가 별도로 적재해 두지 않은 값은 임의의 숫자를 만들어내지 않고 `null`로 내려줍니다. 응답에서 `null`이 보인다면 그것은 값이 0이라는 뜻이 아니라, 그 항목을 아직 계산할 수단이 없다는 뜻으로 읽어야 합니다.

## 501을 반환하는 항목 정리

- `POST /admin/api/users/{id}/reset-password`
- `PUT /admin/api/settings`
- `GET /admin/api/logs`
- `GET /admin/api/logs/audit`
