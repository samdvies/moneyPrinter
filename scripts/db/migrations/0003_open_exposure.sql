ALTER TABLE strategies
    ADD COLUMN max_exposure_gbp numeric(12, 4) NOT NULL DEFAULT 1000;

ALTER TABLE orders
    ADD COLUMN selection_id text;
CREATE INDEX idx_orders_venue_market_selection
    ON orders (venue, market_id, selection_id);

CREATE VIEW open_order_liability AS
SELECT
    strategy_id,
    venue,
    market_id,
    COALESCE(selection_id, 'order:' || id::text) AS selection_id_key,
    COALESCE(SUM(stake)             FILTER (WHERE side IN ('back','yes','no')), 0) AS back_stake,
    COALESCE(SUM(stake)             FILTER (WHERE side = 'lay'),                 0) AS lay_stake,
    COALESCE(SUM(stake*(price-1))   FILTER (WHERE side IN ('back','yes','no')), 0) AS back_winnings,
    COALESCE(SUM(stake*(price-1))   FILTER (WHERE side = 'lay'),                 0) AS lay_liability
FROM orders
WHERE status IN ('pending', 'placed', 'partially_filled')
GROUP BY strategy_id, venue, market_id, COALESCE(selection_id, 'order:' || id::text);
