use execution_bin::config::{AppConfig, ConfigError, VenueKind};
use execution_bin::lifecycle::LifecycleTracker;
use execution_core::{ExecutionResult, OrderId, OrderState};
use rust_decimal::Decimal;
use std::collections::HashMap;

fn vars() -> HashMap<String, String> {
    HashMap::from([
        (
            "REDIS_URL".to_string(),
            "redis://127.0.0.1:6379".to_string(),
        ),
        ("VENUE".to_string(), "mock".to_string()),
        (
            "EXECUTION_CONSUMER_NAME".to_string(),
            "execution-mock-1".to_string(),
        ),
    ])
}

#[test]
fn config_parsing_happy_path_uses_defaults() {
    let cfg = AppConfig::from_map(&vars()).expect("config should parse");
    assert_eq!(cfg.redis_url, "redis://127.0.0.1:6379");
    assert_eq!(cfg.venue, VenueKind::Mock);
    assert_eq!(cfg.max_tracked_orders, 10_000);
    assert_eq!(cfg.shutdown_drain_seconds, 30);
}

#[test]
fn config_parsing_requires_smarkets_credentials() {
    let mut cfg_map = vars();
    cfg_map.insert("VENUE".to_string(), "smarkets".to_string());

    let err =
        AppConfig::from_map(&cfg_map).expect_err("smarkets config should require credentials");
    assert!(matches!(
        err,
        ConfigError::MissingVar("SMARKETS_USERNAME" | "SMARKETS_PASSWORD")
    ));
}

#[tokio::test]
async fn lifecycle_transition_updates_state_and_records_publication() {
    let tracker = LifecycleTracker::new(100);
    let first = sample_event("order-1", OrderState::Accepted);
    let second = sample_event("order-1", OrderState::Filled);
    tracker
        .transition(first.client_order_id.clone(), first)
        .await;
    tracker
        .transition(second.client_order_id.clone(), second)
        .await;

    let current = tracker.current_state(&OrderId::new("order-1"));
    assert_eq!(current, Some(OrderState::Filled));

    let events = tracker.published_events().await;
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].state, OrderState::Accepted);
    assert_eq!(events[1].state, OrderState::Filled);
}

#[test]
fn schema_version_drift_is_detected() {
    let payload = serde_json::json!({
        "client_order_id": "order-1",
        "market_id": "m1",
        "selection_id": "s1",
        "side": "Back",
        "price": "2.00",
        "stake": "10.00",
        "schema_version": 999
    });

    let parsed = serde_json::from_value::<execution_core::OrderRequest>(payload);
    assert!(parsed.is_err(), "unknown schema version must fail");
}

#[test]
fn lifecycle_event_contains_execution_result_shape() {
    let event = sample_event("order-1", OrderState::Accepted);
    assert_eq!(event.state, OrderState::Accepted);
}

fn sample_event(order_id: &str, state: OrderState) -> ExecutionResult {
    ExecutionResult {
        client_order_id: OrderId::new(order_id),
        venue_order_id: Some(format!("venue-{order_id}")),
        state,
        filled_stake: Decimal::ZERO,
        avg_fill_price: None,
        ts_utc: chrono::Utc::now(),
        schema_version: 1,
    }
}
