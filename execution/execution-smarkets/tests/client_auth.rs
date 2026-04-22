use execution_core::{OrderId, OrderRequest, Side, Venue, VenueError};
use execution_smarkets::{SmarketsClient, SmarketsError, SmarketsRateLimiter, SmarketsVenue};
use rust_decimal::Decimal;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use wiremock::matchers::{body_json, header, method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

fn client(base_url: String) -> SmarketsClient {
    SmarketsClient::new(base_url, "alice", "secret", SmarketsRateLimiter::new(5, 10))
}

fn sample_order() -> OrderRequest {
    OrderRequest {
        client_order_id: OrderId::new("order-1"),
        market_id: "market-1".to_string(),
        selection_id: "selection-1".to_string(),
        side: Side::Back,
        price: Decimal::new(250, 2),
        stake: Decimal::new(1000, 2),
        schema_version: 1,
    }
}

#[tokio::test]
async fn login_happy_path_returns_session() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/sessions"))
        .and(body_json(serde_json::json!({
            "username": "alice",
            "password": "secret"
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "session_token": "tok-123",
            "expires_in_seconds": 300
        })))
        .mount(&server)
        .await;

    let client = client(server.uri());
    let session = client.login().await.expect("login should succeed");

    assert_eq!(session.token, "tok-123");
}

#[tokio::test]
async fn login_unauthorized_maps_to_login_failed() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/sessions"))
        .respond_with(ResponseTemplate::new(401))
        .mount(&server)
        .await;

    let client = client(server.uri());
    let err = client.login().await.expect_err("401 login should fail");

    assert_eq!(err, SmarketsError::LoginFailed);
}

#[tokio::test]
async fn session_token_header_is_sent_on_subsequent_calls() {
    let server = MockServer::start().await;

    Mock::given(method("POST"))
        .and(path("/sessions"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "session_token": "token-a",
            "expires_in_seconds": 300
        })))
        .expect(1)
        .mount(&server)
        .await;

    Mock::given(method("GET"))
        .and(path("/markets"))
        .and(header("session-token", "token-a"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!([
            {"id": "m1", "name": "Market 1"}
        ])))
        .expect(1)
        .mount(&server)
        .await;

    let client = client(server.uri());
    let payload = client
        .send_authenticated_json(reqwest::Method::GET, "/markets")
        .await
        .expect("fetch markets should pass");
    let markets = payload
        .as_array()
        .expect("market payload should be an array");
    assert_eq!(markets.len(), 1);
}

#[tokio::test]
async fn mid_call_401_triggers_relogin_and_retry() {
    let server = MockServer::start().await;

    Mock::given(method("POST"))
        .and(path("/sessions"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "session_token": "token-a",
            "expires_in_seconds": 300
        })))
        .expect(2)
        .mount(&server)
        .await;

    let call_count = Arc::new(AtomicUsize::new(0));
    Mock::given(method("GET"))
        .and(path("/markets"))
        .and(header("session-token", "token-a"))
        .respond_with({
            let call_count = Arc::clone(&call_count);
            move |_request: &wiremock::Request| {
                let invocation = call_count.fetch_add(1, Ordering::SeqCst);
                if invocation == 0 {
                    ResponseTemplate::new(401)
                } else {
                    ResponseTemplate::new(200).set_body_json(serde_json::json!([
                        {"id": "m2", "name": "Market 2"}
                    ]))
                }
            }
        })
        .expect(2)
        .mount(&server)
        .await;

    let client = client(server.uri());
    let payload = client
        .send_authenticated_json(reqwest::Method::GET, "/markets")
        .await
        .expect("retry should succeed");
    let markets = payload
        .as_array()
        .expect("market payload should be an array");
    assert_eq!(markets[0]["id"], "m2");
}

#[tokio::test]
async fn response_429_maps_to_rate_limited() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/sessions"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "session_token": "token-a",
            "expires_in_seconds": 300
        })))
        .mount(&server)
        .await;
    Mock::given(method("GET"))
        .and(path("/markets"))
        .respond_with(ResponseTemplate::new(429))
        .mount(&server)
        .await;

    let client = client(server.uri());
    let err = client
        .send_authenticated_json(reqwest::Method::GET, "/markets")
        .await
        .expect_err("429 should fail");
    assert_eq!(err, SmarketsError::RateLimited);
}

#[tokio::test]
async fn malformed_json_maps_to_deserialization_error() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/sessions"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "session_token": "token-a",
            "expires_in_seconds": 300
        })))
        .mount(&server)
        .await;
    Mock::given(method("GET"))
        .and(path("/markets"))
        .respond_with(ResponseTemplate::new(200).set_body_string("{not-json"))
        .mount(&server)
        .await;

    let client = client(server.uri());
    let err = client
        .send_authenticated_json(reqwest::Method::GET, "/markets")
        .await
        .expect_err("bad json should fail");
    assert!(matches!(err, SmarketsError::Deserialization(_)));
}

#[tokio::test]
async fn venue_place_order_maps_to_not_implemented() {
    let server = MockServer::start().await;
    let client = client(server.uri());
    let venue = SmarketsVenue::new(client);

    let err = venue
        .place_order(sample_order())
        .await
        .expect_err("stub endpoint should return not implemented");

    assert_eq!(err, VenueError::NotImplemented);
}
