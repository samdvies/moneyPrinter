CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE strategies (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug         text NOT NULL UNIQUE,
    status       text NOT NULL CHECK (status IN (
                   'hypothesis', 'backtesting', 'paper',
                   'awaiting-approval', 'live', 'retired')),
    parameters   jsonb NOT NULL DEFAULT '{}'::jsonb,
    wiki_path    text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    approved_at  timestamptz,
    approved_by  text
);

CREATE INDEX idx_strategies_status ON strategies (status);

CREATE TABLE strategy_runs (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id  uuid NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    mode         text NOT NULL CHECK (mode IN ('backtest', 'paper', 'live')),
    started_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    metrics      jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_strategy_runs_strategy_id ON strategy_runs (strategy_id);
CREATE INDEX idx_strategy_runs_mode ON strategy_runs (mode);

CREATE TABLE orders (
    id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id    uuid NOT NULL REFERENCES strategies(id),
    run_id         uuid NOT NULL REFERENCES strategy_runs(id),
    mode           text NOT NULL CHECK (mode IN ('backtest', 'paper', 'live')),
    venue          text NOT NULL CHECK (venue IN ('betfair', 'kalshi')),
    market_id      text NOT NULL,
    side           text NOT NULL CHECK (side IN ('back', 'lay', 'yes', 'no')),
    stake          numeric(12, 4) NOT NULL,
    price          numeric(10, 4) NOT NULL,
    status         text NOT NULL CHECK (status IN (
                     'pending', 'placed', 'partially_filled',
                     'filled', 'cancelled', 'rejected')),
    placed_at      timestamptz,
    filled_at      timestamptz,
    filled_price   numeric(10, 4),
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_orders_strategy_id ON orders (strategy_id);
CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_orders_venue_market ON orders (venue, market_id);
