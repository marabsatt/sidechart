CREATE TABLE research_signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker VARCHAR(20) NOT NULL,
    signal_type VARCHAR(10) NOT NULL,
    suggested_price NUMERIC(20, 8),
    confidence_score NUMERIC(6, 5),
    analysis_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT research_signals_ticker_not_blank CHECK (BTRIM(ticker) <> ''),
    CONSTRAINT research_signals_signal_type_valid CHECK (signal_type IN ('BUY', 'SELL', 'HOLD')),
    CONSTRAINT research_signals_price_positive CHECK (suggested_price IS NULL OR suggested_price > 0),
    CONSTRAINT research_signals_confidence_range CHECK (
        confidence_score IS NULL OR confidence_score BETWEEN 0 AND 1
    )
);

-- migrate:split
CREATE TABLE supervisor_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    signal_id UUID NOT NULL REFERENCES research_signals(id) ON DELETE RESTRICT,
    status VARCHAR(10) NOT NULL DEFAULT 'PENDING',
    adjusted_quantity INTEGER,
    adjusted_limit_price NUMERIC(20, 8),
    reviewer_notes TEXT,
    reviewed_at TIMESTAMP,
    CONSTRAINT supervisor_reviews_status_valid CHECK (
        status IN ('PENDING', 'APPROVED', 'REJECTED', 'MODIFIED')
    ),
    CONSTRAINT supervisor_reviews_quantity_positive CHECK (
        adjusted_quantity IS NULL OR adjusted_quantity > 0
    ),
    CONSTRAINT supervisor_reviews_limit_price_positive CHECK (
        adjusted_limit_price IS NULL OR adjusted_limit_price > 0
    ),
    CONSTRAINT supervisor_reviews_reviewed_at_consistent CHECK (
        (status = 'PENDING' AND reviewed_at IS NULL)
        OR (status <> 'PENDING' AND reviewed_at IS NOT NULL)
    )
);

-- migrate:split
CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    supervisor_review_id UUID NOT NULL REFERENCES supervisor_reviews(id) ON DELETE RESTRICT,
    ib_order_id INTEGER,
    ib_perm_id INTEGER,
    action VARCHAR(4) NOT NULL,
    order_type VARCHAR(20) NOT NULL,
    status VARCHAR(40) NOT NULL,
    total_qty INTEGER NOT NULL,
    filled_qty INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT orders_action_valid CHECK (action IN ('BUY', 'SELL')),
    CONSTRAINT orders_order_type_not_blank CHECK (BTRIM(order_type) <> ''),
    CONSTRAINT orders_status_not_blank CHECK (BTRIM(status) <> ''),
    CONSTRAINT orders_total_qty_positive CHECK (total_qty > 0),
    CONSTRAINT orders_filled_qty_valid CHECK (filled_qty BETWEEN 0 AND total_qty)
);

-- migrate:split
CREATE TABLE executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
    ib_exec_id VARCHAR(100) NOT NULL UNIQUE,
    price NUMERIC(20, 8) NOT NULL,
    shares INTEGER NOT NULL,
    commission NUMERIC(20, 8),
    executed_at TIMESTAMP NOT NULL,
    CONSTRAINT executions_exec_id_not_blank CHECK (BTRIM(ib_exec_id) <> ''),
    CONSTRAINT executions_price_positive CHECK (price > 0),
    CONSTRAINT executions_shares_positive CHECK (shares > 0)
);

-- migrate:split
CREATE TABLE portfolio_positions (
    ticker VARCHAR(20) PRIMARY KEY,
    position_size INTEGER NOT NULL,
    average_cost NUMERIC(20, 8) NOT NULL,
    market_value NUMERIC(20, 8) NOT NULL,
    unrealized_pnl NUMERIC(20, 8) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT portfolio_positions_ticker_not_blank CHECK (BTRIM(ticker) <> ''),
    CONSTRAINT portfolio_positions_average_cost_nonnegative CHECK (average_cost >= 0)
);

-- migrate:split
CREATE TABLE agent_tokens_audit (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_name VARCHAR(100) NOT NULL,
    signal_id UUID REFERENCES research_signals(id) ON DELETE SET NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    cost NUMERIC(20, 8) NOT NULL,
    CONSTRAINT agent_tokens_audit_agent_not_blank CHECK (BTRIM(agent_name) <> ''),
    CONSTRAINT agent_tokens_audit_prompt_tokens_nonnegative CHECK (prompt_tokens >= 0),
    CONSTRAINT agent_tokens_audit_completion_tokens_nonnegative CHECK (completion_tokens >= 0),
    CONSTRAINT agent_tokens_audit_cost_nonnegative CHECK (cost >= 0)
);

-- migrate:split
CREATE INDEX idx_research_signals_ticker_created_at
ON research_signals(ticker, created_at DESC);

-- migrate:split
CREATE INDEX idx_research_signals_type_created_at
ON research_signals(signal_type, created_at DESC);

-- migrate:split
CREATE INDEX idx_supervisor_reviews_signal_id
ON supervisor_reviews(signal_id);

-- migrate:split
CREATE INDEX idx_supervisor_reviews_status
ON supervisor_reviews(status);

-- migrate:split
CREATE INDEX idx_orders_supervisor_review_id
ON orders(supervisor_review_id);

-- migrate:split
CREATE INDEX idx_orders_ib_order_id
ON orders(ib_order_id) WHERE ib_order_id IS NOT NULL;

-- migrate:split
CREATE UNIQUE INDEX uq_orders_ib_perm_id
ON orders(ib_perm_id) WHERE ib_perm_id IS NOT NULL;

-- migrate:split
CREATE INDEX idx_orders_status_created_at
ON orders(status, created_at DESC);

-- migrate:split
CREATE INDEX idx_executions_order_executed_at
ON executions(order_id, executed_at);

-- migrate:split
CREATE INDEX idx_portfolio_positions_updated_at
ON portfolio_positions(updated_at);

-- migrate:split
CREATE INDEX idx_agent_tokens_audit_signal_id
ON agent_tokens_audit(signal_id) WHERE signal_id IS NOT NULL;

-- migrate:split
CREATE INDEX idx_agent_tokens_audit_agent
ON agent_tokens_audit(agent_name);
