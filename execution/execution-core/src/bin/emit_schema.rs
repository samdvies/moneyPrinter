use chrono::{TimeZone, Utc};
use execution_core::{ExecutionResult, OrderId, OrderRequest, OrderState, Side};
use rust_decimal::Decimal;
use serde_json::json;
use std::collections::BTreeSet;

fn sorted_fields(value: &serde_json::Value) -> Vec<String> {
    value
        .as_object()
        .expect("schema payload should encode as object")
        .keys()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>()
}

fn emit_order_request() -> serde_json::Value {
    let sample = OrderRequest {
        client_order_id: OrderId::new("sample-client-order"),
        market_id: "sample-market".to_string(),
        selection_id: "sample-selection".to_string(),
        side: Side::Back,
        price: Decimal::new(250, 2),
        stake: Decimal::new(1000, 2),
        schema_version: 1,
    };

    let encoded = serde_json::to_value(sample).expect("order request sample should serialize");
    let fields = sorted_fields(&encoded);

    json!({
        "type": "OrderRequest",
        "fields": fields,
        "optional_fields": Vec::<String>::new(),
    })
}

fn emit_execution_result() -> serde_json::Value {
    let sample = ExecutionResult {
        client_order_id: OrderId::new("sample-client-order"),
        venue_order_id: None,
        state: OrderState::Filled,
        filled_stake: Decimal::new(1000, 2),
        avg_fill_price: None,
        ts_utc: Utc.with_ymd_and_hms(2026, 4, 22, 11, 30, 0).unwrap(),
        schema_version: 1,
    };

    let encoded = serde_json::to_value(sample).expect("execution result sample should serialize");
    let object = encoded
        .as_object()
        .expect("execution result should encode as object");
    let fields = sorted_fields(&encoded);
    let optional_fields = object
        .iter()
        .filter_map(|(name, value)| {
            if value.is_null() {
                Some(name.clone())
            } else {
                None
            }
        })
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();

    json!({
        "type": "ExecutionResult",
        "fields": fields,
        "optional_fields": optional_fields,
    })
}

fn emit_order_state() -> serde_json::Value {
    json!({
        "type": "OrderState",
        "fields": [],
        "optional_fields": [],
        "variants": [
            "Submitted",
            "Accepted",
            "PartiallyFilled",
            "Filled",
            "Cancelled",
            "Rejected"
        ],
    })
}

fn main() {
    for record in [
        emit_order_request(),
        emit_order_state(),
        emit_execution_result(),
    ] {
        println!(
            "{}",
            serde_json::to_string(&record).expect("schema record should serialize")
        );
    }
}
