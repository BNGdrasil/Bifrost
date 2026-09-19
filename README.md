<p align="center">
    <img align="top" width="30%" src="https://raw.githubusercontent.com/BNGdrasil/.github/main/images/Bifrost.png" alt="Bifrost"/>
</p>

<div align="center">

# Bifrost (Bnbong + bifrost)

**BNGdrasil의 API 게이트웨이**

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=flat-square&logo=prometheus&logoColor=white)

*[BNGdrasil](https://github.com/BNGdrasil) 생태계의 일부입니다*

</div>

---

## 소개

Bifrost는 BNGdrasil의 API 게이트웨이입니다. 등록된 서비스 목록으로 요청을 라우팅합니다. 권한 판단은 Bidar에 위임합니다. 서비스 등록용 관리자 API도 제공합니다.

## 주요 기능

- 등록된 서비스로 요청을 프록시합니다.
- 위험한 헤더와 경로 조작을 차단합니다.
- 관리자 API로 서비스를 등록합니다.
- 사용자 요청을 Bidar로 중계합니다.
- 업스트림 URL을 정책으로 제한합니다.
- 헬스체크와 Prometheus 지표를 제공합니다.

## 빠른 시작

```bash
uv sync
cp env.example .env                       # 값을 채운 뒤 사용합니다
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

DATABASE_URL=sqlite:///:memory: SECRET_KEY=local-test-secret-key ENVIRONMENT=test uv run pytest
```

## 문서

| 문서 | 내용 |
| --- | --- |
| [게이트웨이 동작](docs/gateway.md) | 공개 경로와 프록시 계약 |
| [관리자 API](docs/admin-api.md) | 서비스·사용자·설정 관리 API |
| [설정](docs/configuration.md) | 환경 변수와 검증 규칙 |
| [관측](docs/observability.md) | 프로브와 지표, rate limit |
| [운영과 배포](docs/operations.md) | 배포와 롤백, 알려진 제한 |
| [개발](docs/development.md) | 로컬 개발과 테스트, 빌드 |

## 관련 프로젝트

- [Bidar](https://github.com/BNGdrasil/Bidar): 인증 서버
- [Bantheon](https://github.com/BNGdrasil/Bantheon): 웹 클라이언트와 VM1 Nginx 설정
- [Baedalus](https://github.com/BNGdrasil/Baedalus): 인프라 코드와 운영 도구
