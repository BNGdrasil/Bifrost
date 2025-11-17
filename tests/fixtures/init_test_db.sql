-- Initialize test database with schema and test data
-- This script runs when the test database container starts

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    full_name VARCHAR(100),
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    is_superuser BOOLEAN NOT NULL DEFAULT false,
    role VARCHAR(20) DEFAULT 'user',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT check_user_role CHECK (role IN ('user', 'moderator', 'admin', 'super_admin'))
);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users(email);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username);

-- Create services table
CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    url VARCHAR(500) NOT NULL,
    health_check_path VARCHAR(200) DEFAULT '/health',
    timeout_seconds INTEGER DEFAULT 30,
    rate_limit_per_minute INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT true,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_health_check TIMESTAMP WITH TIME ZONE,
    health_status VARCHAR(20) DEFAULT 'unknown',
    metadata JSONB DEFAULT '{}',
    CONSTRAINT check_health_status CHECK (health_status IN ('healthy', 'unhealthy', 'unknown', 'checking'))
);

CREATE INDEX IF NOT EXISTS idx_services_name ON services(name);
CREATE INDEX IF NOT EXISTS idx_services_is_active ON services(is_active);
CREATE INDEX IF NOT EXISTS idx_services_health_status ON services(health_status);

-- Create api_keys table
CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY,
    key_name VARCHAR(100) NOT NULL,
    key_hash VARCHAR(255) NOT NULL,
    user_id INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    last_used_at TIMESTAMP WITHOUT TIME ZONE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Create trigger function for updating updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger for services table
DROP TRIGGER IF EXISTS update_services_updated_at ON services;
CREATE TRIGGER update_services_updated_at
    BEFORE UPDATE ON services
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Insert test data for services
INSERT INTO services (name, display_name, url, health_check_path, timeout_seconds, rate_limit_per_minute, is_active, description, health_status, metadata)
VALUES
    ('qshing-server', 'Qshing Server', 'http://qshing-server:8080', '/health', 30, 100, true, 'Qshing service for testing', 'unknown', '{"environment": "test"}'),
    ('hello', 'Hello Service', 'http://hello:8080', '/health', 30, 100, true, 'Hello service for testing', 'unknown', '{"environment": "test"}'),
    ('test-service', 'Test Service', 'http://test-service:8080', '/health', 30, 100, true, 'Generic test service', 'unknown', '{"environment": "test"}')
ON CONFLICT (name) DO NOTHING;

-- Insert test user
INSERT INTO users (username, email, full_name, hashed_password, is_active, is_superuser, role)
VALUES
    ('testuser', 'test@example.com', 'Test User', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5ux8E4QI.XDsu', true, false, 'user'),
    ('admin', 'admin@example.com', 'Admin User', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5ux8E4QI.XDsu', true, true, 'admin')
ON CONFLICT (username) DO NOTHING;

-- Grant necessary permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO testuser;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO testuser;
