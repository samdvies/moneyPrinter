-- Historical market-data archive. Populated by the Phase 6a historical loader
-- (see services/ingestion/src/ingestion/historical_loader.py) and read by the
-- backtest harness ArchiveSource. Primary key deduplicates re-loads of the
-- same underlying Betfair TAR file or Redis XRANGE session.

CREATE TABLE IF NOT EXISTS market_data_archive (
    venue         text NOT NULL CHECK (venue IN ('betfair', 'kalshi')),
    market_id     text NOT NULL,
    observed_at   timestamptz NOT NULL,
    bids          jsonb NOT NULL,
    asks          jsonb NOT NULL,
    last_trade    numeric(10, 4),
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (venue, market_id, observed_at)
);

-- TimescaleDB hypertable partitioned on observed_at. Chunk interval starts at
-- one day; tune later once we understand ingest volumes.
SELECT create_hypertable(
    'market_data_archive',
    'observed_at',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Replay cursor: ArchiveSource reads (venue, market_id) slices ordered by
-- observed_at. DESC matches hypertable chunk-pruning heuristics.
CREATE INDEX IF NOT EXISTS idx_market_data_archive_replay
    ON market_data_archive (venue, market_id, observed_at DESC);
