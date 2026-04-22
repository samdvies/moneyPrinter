use chrono::{TimeZone, Utc};
use execution_core::{ExecutionResult, OrderId, OrderRequest, OrderState, Side};
use rust_decimal::Decimal;
use serde_json::json;

#[test]
fn order_request_round_trip_preserves_fields() {
    let req = OrderRequest {
        client_order_id: OrderId::new("client-123"),
        market_id: "mkt-1".to_string(),
        selection_id: "runner-42".to_string(),
        side: Side::Back,
        price: Decimal::new(205, 2),
        stake: Decimal::new(1000, 2),
        schema_version: 1,
    };

    let encoded = serde_json::to_string(&req).expect("order request should serialize");
    let decoded: OrderRequest =
        serde_json::from_str(&encoded).expect("order request should deserialize");

    assert_eq!(decoded, req);
}

#[test]
fn execution_result_round_trip_preserves_fields() {
    let result = ExecutionResult {
        client_order_id: OrderId::new("client-abc"),
        venue_order_id: Some("venue-999".to_string()),
        state: OrderState::PartiallyFilled,
        filled_stake: Decimal::new(250, 2),
        avg_fill_price: Some(Decimal::new(198, 2)),
        ts_utc: Utc.with_ymd_and_hms(2026, 4, 22, 11, 30, 0).unwrap(),
        schema_version: 1,
    };

    let encoded = serde_json::to_string(&result).expect("execution result should serialize");
    let decoded: ExecutionResult =
        serde_json::from_str(&encoded).expect("execution result should deserialize");

    assert_eq!(decoded, result);
}

#[test]
fn order_request_rejects_unknown_schema_version() {
    let payload = json!({
        "client_order_id": "client-123",
        "market_id": "mkt-1",
        "selection_id": "runner-42",
        "side": "Back",
        "price": "2.05",
        "stake": "10.00",
        "schema_version": 999
    });

    let err =
        serde_json::from_value::<OrderRequest>(payload).expect_err("schema mismatch must fail");
    let err_msg = err.to_string();
    assert!(
        err_msg.contains("schema_version"),
        "unexpected error: {err_msg}"
    );
}

#[test]
fn execution_result_rejects_unknown_schema_version() {
    let payload = json!({
        "client_order_id": "client-123",
        "venue_order_id": "venue-42",
        "state": "Filled",
        "filled_stake": "10.00",
        "avg_fill_price": "2.00",
        "ts_utc": "2026-04-22T11:30:00Z",
        "schema_version": 999
    });

    let err =
        serde_json::from_value::<ExecutionResult>(payload).expect_err("schema mismatch must fail");
    let err_msg = err.to_string();
    assert!(
        err_msg.contains("schema_version"),
        "unexpected error: {err_msg}"
    );
}
