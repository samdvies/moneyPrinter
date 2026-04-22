use chrono::Utc;
use execution_core::{
    ExecutionResult, MockBehavior, MockResponse, MockVenue, OrderId, OrderRequest, OrderState,
    Side, Venue, VenueError,
};
use rust_decimal::Decimal;
use std::sync::Arc;
use tokio::time::{self, Duration};

fn order(client_id: &str, stake: Decimal) -> OrderRequest {
    OrderRequest {
        client_order_id: OrderId::new(client_id),
        market_id: "market-1".to_string(),
        selection_id: "selection-1".to_string(),
        side: Side::Back,
        price: Decimal::new(210, 2),
        stake,
        schema_version: 1,
    }
}

#[tokio::test]
async fn default_mock_fills_orders_immediately() {
    let venue = MockVenue::new(vec![]);
    let req = order("default-fill", Decimal::new(500, 2));
    let expected_price = req.price;
    let expected_stake = req.stake;
    let expected_id = req.client_order_id.clone();

    let result = venue.place_order(req).await.expect("order should fill");

    assert_eq!(result.client_order_id, expected_id);
    assert_eq!(result.state, OrderState::Filled);
    assert_eq!(result.filled_stake, expected_stake);
    assert_eq!(result.avg_fill_price, Some(expected_price));
}

#[tokio::test]
async fn scripted_reject_returns_rejected_execution_result() {
    let venue = MockVenue::new(vec![MockBehavior::new(
        |_req| true,
        MockResponse::Reject("insufficient liquidity".to_string()),
    )]);

    let result = venue
        .place_order(order("reject-me", Decimal::new(100, 2)))
        .await
        .expect("reject behaviour should return execution result");

    assert_eq!(result.state, OrderState::Rejected);
    assert_eq!(result.filled_stake, Decimal::ZERO);
    assert_eq!(result.avg_fill_price, None);
}

#[tokio::test]
async fn partial_fill_behavior_sets_partially_filled_state() {
    let venue = MockVenue::new(vec![MockBehavior::new(
        |_req| true,
        MockResponse::PartialFill {
            filled_stake: Decimal::new(125, 2),
            avg_fill_price: Decimal::new(208, 2),
        },
    )]);

    let result = venue
        .place_order(order("partial", Decimal::new(400, 2)))
        .await
        .expect("partial fill should succeed");

    assert_eq!(result.state, OrderState::PartiallyFilled);
    assert_eq!(result.filled_stake, Decimal::new(125, 2));
    assert_eq!(result.avg_fill_price, Some(Decimal::new(208, 2)));
}

#[tokio::test]
async fn error_behavior_bubbles_venue_error() {
    let venue = MockVenue::new(vec![MockBehavior::new(
        |_req| true,
        MockResponse::Error(VenueError::NetworkTimeout),
    )]);

    let err = venue
        .place_order(order("network-timeout", Decimal::new(100, 2)))
        .await
        .expect_err("error behaviour should bubble error");

    assert_eq!(err, VenueError::NetworkTimeout);
}

#[tokio::test(start_paused = true)]
async fn delay_behavior_respects_configured_duration() {
    let venue = MockVenue::new(vec![MockBehavior::new(
        |_req| true,
        MockResponse::Delay {
            duration: Duration::from_secs(5),
            response: Box::new(MockResponse::Fill),
        },
    )]);
    let venue = Arc::new(venue);
    let req = order("delayed", Decimal::new(300, 2));

    let task = tokio::spawn({
        let venue = Arc::clone(&venue);
        async move { venue.place_order(req).await }
    });
    tokio::task::yield_now().await;

    assert!(!task.is_finished(), "delay should keep order pending");
    time::advance(Duration::from_secs(4)).await;
    tokio::task::yield_now().await;
    assert!(!task.is_finished(), "order should still be waiting");

    time::advance(Duration::from_secs(1)).await;
    let result = task
        .await
        .expect("task join should succeed")
        .expect("fill expected");
    assert_eq!(result.state, OrderState::Filled);
}

#[tokio::test]
async fn cancel_filled_order_returns_terminal_error() {
    let venue = MockVenue::new(vec![]);
    let req = order("filled-order", Decimal::new(150, 2));
    let order_id = req.client_order_id.clone();
    venue.place_order(req).await.expect("fill should succeed");

    let err = venue
        .cancel_order(order_id)
        .await
        .expect_err("filled order cancellation should error");
    assert_eq!(err, VenueError::Other("already terminal".to_string()));
}

#[tokio::test]
async fn cancel_pending_order_returns_cancelled_state() {
    let pending_order_id = OrderId::new("pending-order");
    let venue = MockVenue::with_open_orders(vec![ExecutionResult {
        client_order_id: pending_order_id.clone(),
        venue_order_id: Some("venue-pending".to_string()),
        state: OrderState::Accepted,
        filled_stake: Decimal::ZERO,
        avg_fill_price: None,
        ts_utc: Utc::now(),
        schema_version: 1,
    }]);

    let result = venue
        .cancel_order(pending_order_id.clone())
        .await
        .expect("pending order should cancel");

    assert_eq!(result.client_order_id, pending_order_id);
    assert_eq!(result.state, OrderState::Cancelled);
}

#[tokio::test]
async fn fetch_open_orders_reflects_currently_tracked_orders() {
    let venue = MockVenue::with_open_orders(vec![
        ExecutionResult {
            client_order_id: OrderId::new("open-1"),
            venue_order_id: Some("venue-open-1".to_string()),
            state: OrderState::Accepted,
            filled_stake: Decimal::ZERO,
            avg_fill_price: None,
            ts_utc: Utc::now(),
            schema_version: 1,
        },
        ExecutionResult {
            client_order_id: OrderId::new("open-2"),
            venue_order_id: Some("venue-open-2".to_string()),
            state: OrderState::PartiallyFilled,
            filled_stake: Decimal::new(50, 2),
            avg_fill_price: Some(Decimal::new(203, 2)),
            ts_utc: Utc::now(),
            schema_version: 1,
        },
    ]);

    let open_orders = venue
        .fetch_open_orders()
        .await
        .expect("fetch should succeed");

    assert_eq!(
        open_orders,
        vec![OrderState::Accepted, OrderState::PartiallyFilled]
    );
}
