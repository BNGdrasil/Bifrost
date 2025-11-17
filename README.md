<p align="center">
    <img align="top" width="30%" src="https://github.com/BNGdrasil/BNGdrasil/blob/main/images/Bifrost.png" alt="Bifrost"/>
</p>

<div align="center">

# 🌉 Bifrost (Bnbong + bifrost)

**API Gateway for Microservices**

[![Python](https://img.shields.io/badge/Python-3.12+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104.1-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Tests](https://img.shields.io/badge/Tests-85%20Passed-green.svg?style=flat-square)](tests/)
[![Code Style](https://img.shields.io/badge/Code%20Style-Black-black.svg?style=flat-square)](https://github.com/psf/black)

*Part of the [BNGdrasil](https://github.com/BNGdrasil/BNGdrasil) ecosystem - A comprehensive cloud infrastructure project*

</div>

---

## Overview

**Bifrost** is a high-performance API Gateway built with FastAPI, designed to be the central entry point for microservices in the [BNGdrasil](https://github.com/BNGdrasil/BNGdrasil) cloud infrastructure. Named after the rainbow bridge in Norse mythology, Bifrost connects different services seamlessly while providing essential gateway features like request routing, load balancing, logging, and monitoring.

### Key Features

- **High Performance**: Built on FastAPI and asyncio for maximum throughput
- **Service Discovery**: Dynamic service registration and management with PostgreSQL persistence
- **Admin Dashboard API**: Comprehensive REST API for system administration
  - Service lifecycle management (CRUD operations)
  - User management and access control
  - System logs and audit trails
  - Real-time statistics and monitoring
- **Security & Authentication**:
  - JWT-based authentication
  - Role-based access control (Admin, Super Admin)
  - CORS, trusted hosts, and rate limiting middleware
- **Database-Driven**: PostgreSQL for persistent storage with SQLAlchemy ORM
- **Monitoring & Observability**:
  - Prometheus metrics export
  - Structured JSON logging with structlog
  - Automatic health checks for registered services
- **Request Proxying**: Intelligent request forwarding to backend services with full HTTP method support
- **Cloud Ready**: Docker support with multi-stage builds and environment-based configuration
- **Developer Friendly**: Comprehensive API documentation via OpenAPI/Swagger

---

## Architecture

```mermaid
graph TB
    Client[Client Applications] --> Bifrost[Bifrost API Gateway]
    Bifrost --> ServiceA[Service A]
    Bifrost --> ServiceB[Service B]
    Bifrost --> ServiceC[Service C]

    Bifrost --> Metrics[Prometheus Metrics]
    Bifrost --> Logs[Structured Logs]

    Admin[Admin Interface] --> Bifrost

    subgraph "Middleware Stack"
        CORS[CORS Middleware]
        Auth[Auth Middleware]
        Rate[Rate Limiting]
        Log[Logging Middleware]
    end
```

### Core Components

- **Gateway API** (`src/api/api.py`): Service discovery, health checks, and request proxying
- **Admin API** (`src/api/admin/`): Service, user, logs, and settings management endpoints
- **Service Registry** (`src/services/services.py`): Dynamic service discovery, health monitoring, and request forwarding
- **Database Layer**:
  - **Models** (`src/models/`): SQLAlchemy ORM models for data persistence
  - **Schemas** (`src/schemas/`): Pydantic models for request/response validation
  - **CRUD** (`src/crud/`): Database operations for service management
- **Core Utilities**:
  - **Configuration** (`src/core/config.py`): Environment-based settings management
  - **Database** (`src/core/database.py`): PostgreSQL connection and session management
  - **Middleware** (`src/core/middleware.py`): CORS, rate limiting, and structured logging
  - **Permissions** (`src/core/permissions.py`): JWT authentication and role-based access control
- **Main Application** (`src/main.py`): FastAPI app initialization, middleware setup, and lifecycle management

---

## Project Structure

```
bifrost/
├── src/                    # Gateway Core
│   ├── api/               # API endpoints
│   │   ├── admin/         # Admin API endpoints
│   │   │   ├── services.py   # Service management
│   │   │   ├── users.py      # User management
│   │   │   ├── logs.py       # Audit logs & system logs
│   │   │   └── settings.py   # System settings
│   │   └── api.py         # Gateway API endpoints
│   ├── core/              # Core functionality
│   │   ├── config.py      # Configuration management
│   │   ├── database.py    # Database connection
│   │   ├── middleware.py  # Custom middleware
│   │   └── permissions.py # Authorization & permissions
│   ├── crud/              # Database operations
│   │   └── service.py     # Service CRUD operations
│   ├── models/            # Database models
│   │   └── service.py     # Service model
│   ├── schemas/           # Pydantic schemas
│   │   └── service.py     # Service schemas
│   ├── services/          # Service registry & management
│   │   └── services.py    # Service discovery & proxy
│   ├── utils/             # Utility functions
│   └── main.py            # FastAPI application
├── tests/                 # Test suites
│   ├── conftest.py        # Test configuration
│   ├── fixtures/          # Test fixtures
│   ├── test_api.py        # API tests
│   ├── test_config.py     # Configuration tests
│   ├── test_integration.py # Integration tests
│   └── test_middleware.py # Middleware tests
├── scripts/               # Utility scripts
│   ├── dev.sh             # Development server
│   ├── format.sh          # Code formatting
│   ├── lint.sh            # Linting
│   ├── test.sh            # Run tests
│   └── test-docker.sh     # Docker-based tests
├── requirements.txt       # Python dependencies
├── pyproject.toml         # Project configuration
├── Dockerfile             # Production container
├── Dockerfile.test        # Test container
├── docker-compose.test.yml # Test environment
└── README.md              # This file
```

### Key Components

The gateway is organized into several key modules:

- **API Layer** (`src/api/`): RESTful endpoints for both gateway and admin operations
  - Gateway API for service discovery and proxying
  - Admin API for service management, user management, logs, and settings

- **Core** (`src/core/`): Essential gateway functionality
  - Configuration management with environment-based settings
  - Database connectivity (PostgreSQL)
  - Custom middleware (CORS, rate limiting, logging)
  - Permission system for admin operations

- **Data Layer** (`src/crud/`, `src/models/`, `src/schemas/`): Database operations
  - SQLAlchemy models for data persistence
  - Pydantic schemas for validation
  - CRUD operations for service management

- **Service Management** (`src/services/`): Service registry and proxy
  - Dynamic service discovery
  - Health check monitoring
  - Request proxying to backend services

---

## Quick Start

### Prerequisites

- **Python 3.12+**
- **Docker** (optional)
- **Redis** (for caching and rate limiting)
- **PostgreSQL** (for persistent storage)

### Installation

#### Using uv

```bash
# Clone the repository
git clone https://github.com/BNGdrasil/Bifrost.git
cd Bifrost

# Install dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate

# Run the application
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

#### Using Docker

```bash
# Build and run
docker build -t bifrost .
docker run -p 8000:8000 bifrost
```

### Access Points

Once running, you can access:

- **API Gateway**: http://localhost:8000/api/v1
- **Admin API**: http://localhost:8000/admin/api
- **Interactive Docs (development only)**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **Metrics**: http://localhost:8000/metrics
- **Root Endpoint**: http://localhost:8000/

---

## Configuration

### Environment Variables

Bifrost uses environment variables for configuration. Create a `.env` file based on `env.example`:

```bash
# Application
ENVIRONMENT=development  # development, production, testing
LOG_LEVEL=INFO

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/bifrost
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

# Redis (for caching and rate limiting)
REDIS_URL=redis://localhost:6379/0

# Security
SECRET_KEY=your-secret-key-here
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000

# Auth Server
AUTH_SERVER_URL=http://localhost:8001
JWT_SECRET_KEY=your-jwt-secret-here
JWT_ALGORITHM=HS256

# Rate Limiting
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=100

# Service Health Check
HEALTH_CHECK_INTERVAL=60
HEALTH_CHECK_TIMEOUT=5
```

### Database Setup

Bifrost uses PostgreSQL for persistent storage of service configurations and metadata.

**Create Database:**
```bash
# Using psql
createdb bifrost

# Or using PostgreSQL CLI
psql -U postgres
CREATE DATABASE bifrost;
```

**Run Migrations:**
```bash
# Install alembic if not already installed
pip install alembic

# Initialize database schema
alembic upgrade head
```

### Service Management

Services are now managed through the database via the Admin API. Use the Admin API endpoints to register, update, and remove services dynamically.

**Example: Register a new service via Admin API:**

```bash
curl -X POST http://localhost:8000/admin/api/services \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-token>" \
  -d '{
    "name": "auth-server",
    "url": "http://auth-server:8001",
    "health_check_endpoint": "/health",
    "timeout": 30,
    "description": "Authentication and authorization service",
    "is_active": true
  }'
```

The service registry automatically reloads when services are added, updated, or removed.

---

## API Reference

<details>
<summary><h3>Gateway API (<code>/api/v1</code>)</h3></summary>

The Gateway API provides service discovery and request proxying.

#### List Services

```http
GET /api/v1/services
```

**Response:**
```json
{
  "services": {
    "auth-server": {
      "url": "http://auth-server:8001",
      "health_check": "/health",
      "timeout": 30
    }
  },
  "count": 1
}
```

#### Check Service Health

```http
GET /api/v1/services/{service_name}/health
```

**Response:**
```json
{
  "service": "auth-server",
  "healthy": true
}
```

#### Request Proxying

All requests to `/api/v1/{service_name}/{path}` are automatically proxied to the registered service:

```http
# This request:
GET /api/v1/auth-server/api/users/123

# Gets proxied to:
GET http://auth-server:8001/api/users/123
```

Supports all HTTP methods: `GET`, `POST`, `PUT`, `DELETE`, `PATCH`

</details>

---

<details>
<summary><h3>Admin API (<code>/admin/api</code>)</h3></summary>

The Admin API provides management endpoints for services, users, logs, and system settings. All endpoints require authentication and appropriate permissions.

#### Authentication

All Admin API requests require a valid JWT token:

```http
Authorization: Bearer <your-token>
```

<details>
<summary><h4>Service Management</h4></summary>

**List All Services**

```http
GET /admin/api/services
```

Query Parameters:
- `skip` (int): Number of services to skip (default: 0)
- `limit` (int): Maximum services to return (default: 100)
- `active_only` (bool): Return only active services (default: false)

**Get Service Statistics**

```http
GET /admin/api/services/stats
```

**Get Service by ID**

```http
GET /admin/api/services/{service_id}
```

**Create New Service**

```http
POST /admin/api/services
Content-Type: application/json

{
  "name": "new-service",
  "url": "http://new-service:8003",
  "health_check_endpoint": "/health",
  "timeout": 30,
  "description": "New microservice",
  "is_active": true
}
```

**Update Service**

```http
PUT /admin/api/services/{service_id}
Content-Type: application/json

{
  "name": "updated-service",
  "url": "http://updated-service:8003",
  "is_active": true
}
```

**Delete Service**

```http
DELETE /admin/api/services/{service_id}
```

**Check Service Health**

```http
GET /admin/api/services/{service_id}/health
```

**Reload Service Registry**

```http
POST /admin/api/services/reload
```

**Trigger Health Check for All Services**

```http
POST /admin/api/services/health-check-all
```

</details>

<details>
<summary><h4>User Management</h4></summary>

**List Users**

```http
GET /admin/api/users
```

Query Parameters:
- `skip` (int): Number of users to skip (default: 0)
- `limit` (int): Maximum users to return (default: 100)

**Get User by ID**

```http
GET /admin/api/users/{user_id}
```

**Delete User (Super Admin Only)**

```http
DELETE /admin/api/users/{user_id}
```

**Reset User Password**

```http
POST /admin/api/users/{user_id}/reset-password
```

</details>

<details>
<summary><h4>Logs & Audit</h4></summary>

**Get System Logs**

```http
GET /admin/api/logs
```

Query Parameters:
- `service` (string): Filter by service name
- `level` (string): Filter by log level (INFO, WARNING, ERROR)
- `limit` (int): Maximum logs to return (default: 100)

**Get Audit Logs**

```http
GET /admin/api/logs/audit
```

Query Parameters:
- `limit` (int): Maximum logs to return (default: 100)

</details>

<details>
<summary><h4>System Settings</h4></summary>

**Get System Settings**

```http
GET /admin/api/settings
```

**Update System Settings (Super Admin Only)**

```http
PUT /admin/api/settings
Content-Type: application/json

{
  "maintenance_mode": false,
  "rate_limit_per_minute": 60
}
```

**Get System Statistics**

```http
GET /admin/api/settings/stats/overview
```

**Response:**

```json
{
  "users": {
    "total": 150,
    "active": 120,
    "new_today": 5
  },
  "services": {
    "total": 3,
    "healthy": 3,
    "unhealthy": 0
  },
  "api_requests": {
    "total_today": 15000,
    "success_rate": 99.5,
    "avg_response_time": 0.05
  }
}
```

</details>

</details>

---

<details>
<summary><h3>System Endpoints</h3></summary>

**Health Check**

```http
GET /health
```

**Prometheus Metrics**

```http
GET /metrics
```

**API Information**

```http
GET /
```

**Admin API Root**

```http
GET /admin/api
```

</details>

---

## Monitoring & Observability

### Prometheus Metrics

Bifrost exposes metrics at `/metrics`:

- `http_requests_total` - Total HTTP requests by method, endpoint, and status
- `http_request_duration_seconds` - Request latency histogram
- `service_health_checks_total` - Service health check results
- `rate_limit_exceeded_total` - Rate limiting events

### Structured Logging

All logs are structured JSON format:

```json
{
  "timestamp": "2024-01-01T12:00:00Z",
  "level": "INFO",
  "event": "Request completed",
  "method": "GET",
  "path": "/api/v1/services",
  "status_code": 200,
  "duration": 0.042,
  "client_ip": "192.168.1.100"
}
```

### Health Checks

- **Application Health**: `GET /health`
- **Service Health**: Automatic background checks for registered services
- **Readiness**: Database and Redis connectivity checks

---

## Security

### Security Features

- **JWT Authentication**: Token-based authentication for Admin API
- **Role-Based Access Control (RBAC)**: Multiple permission levels
  - **Admin**: Can manage services, view logs, and manage users
  - **Super Admin**: Full system access including settings modification
- **CORS Protection**: Configurable origin restrictions
- **Trusted Hosts**: Host header validation *(on fixing...)*
- **Rate Limiting**: Per-IP request throttling with Redis backend
- **Secret Management**: Environment-based secrets
- **Input Validation**: Pydantic model validation
- **Error Handling**: Secure error responses
- **Database Security**: SQLAlchemy ORM with parameter binding

### Permission Levels

Bifrost implements three permission levels:

1. **Public**: Unauthenticated access (Gateway API endpoints)
2. **Admin**: Authenticated users with admin role
   - Service management (read, create, update, delete)
   - User management
   - System logs viewing
   - System statistics
3. **Super Admin**: Highest privilege level
   - All admin permissions
   - System settings modification
   - User deletion

### Authentication Flow

1. User authenticates via Auth Server (`/auth/login`)
2. Auth Server issues JWT token with user role
3. Admin API validates JWT token on each request
4. Permission decorator checks user role against endpoint requirements

---

## BNGdrasil Ecosystem

Bifrost is part of the larger **[BNGdrasil](https://github.com/BNGdrasil)** cloud infrastructure project:

- **🌉 [Bifrost](https://github.com/BNGdrasil/Bifrost)** - API Gateway (this project)
- **🔐 [Bidar](https://github.com/BNGdrasil/Bidar)** - Authentication & Authorization Server
- **🏗️ [Baedalus](https://github.com/BNGdrasil/Baedalus)** - Infrastructure as Code (Terraform)
- **🌐 [Bsgard](https://github.com/BNGdrasil/Bsgard)** - Custom VPC & Networking
- **🎨 [Bantheon](https://github.com/BNGdrasil/Bantheon)** - Web Frontend & Portfolio
- **🎮 [Blysium](https://github.com/BNGdrasil/Blysium)** - Gaming Platform

Each component is designed to work independently while integrating seamlessly with others.

---

## License

This project is used for personal learning and development purposes.
