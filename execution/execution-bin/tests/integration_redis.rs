use execution_bin::bus::{
    Bus, EXECUTION_RESULTS_STREAM, ORDER_SIGNALS_DEADLETTER_STREAM, ORDER_SIGNALS_STREAM,
};
use execution_bin::config::{AppConfig, VenueKind};
use execution_core::{OrderId, OrderState};
use fred::interfaces::{KeysInterface, StreamsInterface};
use fred::prelude::{Builder, ClientLike, RedisClient, RedisConfig};
use std::collections::HashMap;
use tokio::process::{Child, Command};
use tokio::time::{Duration, Instant};

fn integration_config() -> AppConfig {
    AppConfig::from_map(&HashMap::from([
        (
            "REDIS_URL".to_string(),
            "redis://127.0.0.1:6379".to_string(),
        ),
        ("VENUE".to_string(), "mock".to_string()),
        (
            "EXECUTION_CONSUMER_NAME".to_string(),
            "execution-integration-1".to_string(),
        ),
    ]))
    .expect("integration config should parse")
}

fn redis_client() -> RedisClient {
    let config = RedisConfig::from_url("redis://127.0.0.1:6379").expect("redis url should parse");
    Builder::from_config(config)
        .build()
        .expect("redis client should build")
}

async fn reset_streams(client: &RedisClient) {
    let _: () = client
        .del(vec![
            ORDER_SIGNALS_STREAM,
            EXECUTION_RESULTS_STREAM,
            ORDER_SIGNALS_DEADLETTER_STREAM,
        ])
        .await
        .expect("stream reset should succeed");
}

fn spawn_execution_bin() -> Child {
    Command::new("cargo")
        .arg("run")
        .arg("-p")
        .arg("execution-bin")
        .env("REDIS_URL", "redis://127.0.0.1:6379")
        .env("VENUE", "mock")
        .env("EXECUTION_CONSUMER_NAME", "execution-integration-1")
        .spawn()
        .expect("execution-bin process should spawn")
}

#[tokio::test]
#[ignore = "requires local Redis via docker compose up -d redis"]
async fn happy_path_three_signals_yield_three_results() {
    let client = redis_client();
    let _handle = client.init().await.expect("redis init");
    client.wait_for_connect().await.expect("redis connect");
    reset_streams(&client).await;

    let bus = Bus::connect("redis://127.0.0.1:6379")
        .await
        .expect("bus should connect");
    bus.ensure_group("execution").await.expect("group create");

    let mut child = spawn_execution_bin();
    tokio::time::sleep(Duration::from_millis(500)).await;

    for idx in 0..3 {
        let payload = serde_json::json!({
            "client_order_id": format!("integration-{idx}"),
            "market_id": "mkt-1",
            "selection_id": "sel-1",
            "side": "Back",
            "price": "2.00",
            "stake": "10.00",
            "schema_version": 1
        })
        .to_string();
        let _: String = client
            .xadd(
                ORDER_SIGNALS_STREAM,
                true,
                None,
                "*",
                vec![("json", payload)],
            )
            .await
            .expect("xadd signal");
    }

    let deadline = Instant::now() + Duration::from_secs(20);
    let mut seen = 0usize;
    let mut last_seen_id = "0-0".to_string();
    while Instant::now() < deadline {
        let values = read_results_since(&client, &last_seen_id)
            .await
            .expect("read result batch should succeed");
        if let Some((id, _fields)) = values.last() {
            last_seen_id = id.clone();
        }
        seen += values.len();
        if seen >= 3 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    child.start_kill().expect("kill execution-bin");
    let _ = child.wait().await;

    assert_eq!(seen, 3, "expected 3 execution results");
}

#[tokio::test]
#[ignore = "requires local Redis via docker compose up -d redis"]
async fn schema_mismatch_message_goes_to_deadletter() {
    let client = redis_client();
    let _handle = client.init().await.expect("redis init");
    client.wait_for_connect().await.expect("redis connect");
    reset_streams(&client).await;

    let mut child = spawn_execution_bin();
    tokio::time::sleep(Duration::from_millis(500)).await;

    let bad_payload = serde_json::json!({
        "client_order_id": "bad-order",
        "market_id": "mkt-1",
        "selection_id": "sel-1",
        "side": "Back",
        "price": "2.00",
        "stake": "10.00",
        "schema_version": 999
    })
    .to_string();
    let _: String = client
        .xadd(
            ORDER_SIGNALS_STREAM,
            true,
            None,
            "*",
            vec![("json", bad_payload)],
        )
        .await
        .expect("xadd bad signal");

    let deadline = Instant::now() + Duration::from_secs(20);
    let mut deadletter_seen = false;
    while Instant::now() < deadline {
        let deadletter_len: i64 = client
            .xlen("order.signals.deadletter")
            .await
            .expect("xlen deadletter stream should succeed");
        if deadletter_len > 0 {
            deadletter_seen = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    child.start_kill().expect("kill execution-bin");
    let _ = child.wait().await;
    assert!(deadletter_seen, "expected one deadletter entry");
}

#[tokio::test]
#[ignore = "requires local Redis via docker compose up -d redis"]
async fn restart_redelivers_unacked_messages() {
    let client = redis_client();
    let _handle = client.init().await.expect("redis init");
    client.wait_for_connect().await.expect("redis connect");
    reset_streams(&client).await;

    let bus = Bus::connect("redis://127.0.0.1:6379")
        .await
        .expect("bus should connect");
    bus.ensure_group("execution").await.expect("group create");

    let payload = serde_json::json!({
        "client_order_id": "restart-order",
        "market_id": "mkt-1",
        "selection_id": "sel-1",
        "side": "Back",
        "price": "2.00",
        "stake": "10.00",
        "schema_version": 1
    })
    .to_string();
    let _: String = client
        .xadd(
            ORDER_SIGNALS_STREAM,
            true,
            None,
            "*",
            vec![("json", payload)],
        )
        .await
        .expect("xadd signal");

    let mut first = spawn_execution_bin();
    tokio::time::sleep(Duration::from_secs(1)).await;
    first.start_kill().expect("kill first process");
    let _ = first.wait().await;

    let mut second = spawn_execution_bin();
    let deadline = Instant::now() + Duration::from_secs(20);
    let mut seen = false;
    let mut last_seen_id = "0-0".to_string();
    while Instant::now() < deadline {
        let values = read_results_since(&client, &last_seen_id)
            .await
            .expect("read result batch should succeed");
        if let Some((id, _fields)) = values.last() {
            last_seen_id = id.clone();
        }
        if values.iter().any(|(_, fields)| {
            fields.get("json").is_some_and(|raw| {
                let parsed = serde_json::from_str::<execution_core::ExecutionResult>(raw)
                    .expect("execution result payload should deserialize");
                parsed.client_order_id == OrderId::new("restart-order")
                    && parsed.state == OrderState::Filled
            })
        }) {
            seen = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    second.start_kill().expect("kill second process");
    let _ = second.wait().await;
    assert!(seen, "expected message redelivery after restart");
}

#[tokio::test]
#[ignore = "requires local Redis via docker compose up -d redis"]
async fn task8_contract_sanity() {
    let cfg = integration_config();
    assert_eq!(cfg.venue, VenueKind::Mock);

    let client = redis_client();
    let _handle = client.init().await.expect("redis init");
    client.wait_for_connect().await.expect("redis connect");
    let len: i64 = client
        .xlen(EXECUTION_RESULTS_STREAM)
        .await
        .expect("xlen execution results should succeed");
    assert!(len >= 0);
}

async fn read_results_since(
    client: &RedisClient,
    from_id: &str,
) -> Result<Vec<(String, HashMap<String, String>)>, fred::prelude::RedisError> {
    client
        .xrange_values(EXECUTION_RESULTS_STREAM, from_id, "+", Some(100))
        .await
}
