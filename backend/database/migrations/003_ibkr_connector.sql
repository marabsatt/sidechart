ALTER TABLE orders
ADD COLUMN command_id UUID;

-- migrate:split
ALTER TABLE orders
ADD COLUMN limit_price NUMERIC(20, 8);

-- migrate:split
ALTER TABLE orders
ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- migrate:split
ALTER TABLE orders
ADD CONSTRAINT orders_limit_price_positive
CHECK (limit_price IS NULL OR limit_price > 0);

-- migrate:split
CREATE UNIQUE INDEX uq_orders_command_id
ON orders(command_id) WHERE command_id IS NOT NULL;

-- migrate:split
CREATE UNIQUE INDEX uq_orders_supervisor_review_id
ON orders(supervisor_review_id);

-- migrate:split
CREATE TABLE broker_connectors (
    connector_id VARCHAR(100) PRIMARY KEY,
    account_mode VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL,
    gateway_port INTEGER,
    client_id INTEGER,
    version VARCHAR(40),
    last_heartbeat_at TIMESTAMPTZ NOT NULL,
    last_connected_at TIMESTAMPTZ,
    last_error TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT broker_connectors_id_not_blank CHECK (BTRIM(connector_id) <> ''),
    CONSTRAINT broker_connectors_mode_valid CHECK (account_mode IN ('PAPER', 'LIVE')),
    CONSTRAINT broker_connectors_status_valid CHECK (
        status IN ('CONNECTED', 'DISCONNECTED', 'DEGRADED', 'OFFLINE')
    ),
    CONSTRAINT broker_connectors_port_valid CHECK (
        gateway_port IS NULL OR gateway_port BETWEEN 1 AND 65535
    )
);

-- migrate:split
CREATE TABLE broker_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL UNIQUE,
    connector_id VARCHAR(100) NOT NULL
        REFERENCES broker_connectors(connector_id) ON DELETE RESTRICT,
    event_type VARCHAR(40) NOT NULL,
    order_id UUID REFERENCES orders(id) ON DELETE RESTRICT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT broker_events_type_not_blank CHECK (BTRIM(event_type) <> '')
);

-- migrate:split
CREATE INDEX idx_broker_connectors_heartbeat
ON broker_connectors(last_heartbeat_at DESC);

-- migrate:split
CREATE INDEX idx_broker_events_connector_occurred
ON broker_events(connector_id, occurred_at DESC);

-- migrate:split
CREATE INDEX idx_broker_events_order_occurred
ON broker_events(order_id, occurred_at DESC) WHERE order_id IS NOT NULL;
