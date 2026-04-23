ALTER TABLE orders DROP CONSTRAINT orders_venue_check;
ALTER TABLE orders ADD CONSTRAINT orders_venue_check
    CHECK (venue IN ('betfair', 'kalshi', 'polymarket'));
