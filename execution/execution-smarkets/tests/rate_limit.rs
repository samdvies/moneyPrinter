use execution_core::VenueError;
use execution_smarkets::{SmarketsError, SmarketsRateLimiter};
use tokio::time::{self, Duration};

#[tokio::test(start_paused = true)]
async fn limiter_allows_burst_then_waits_for_capacity() {
    let limiter = SmarketsRateLimiter::new(2, 2);

    limiter.acquire().await;
    limiter.acquire().await;

    let pending = tokio::spawn({
        let limiter = limiter.clone();
        async move { limiter.acquire().await }
    });

    tokio::task::yield_now().await;
    assert!(
        !pending.is_finished(),
        "third acquire should be rate-limited"
    );

    time::advance(Duration::from_millis(499)).await;
    tokio::task::yield_now().await;
    assert!(!pending.is_finished(), "token should not be available yet");

    time::advance(Duration::from_millis(1)).await;
    pending.await.expect("join handle should succeed");
}

#[test]
fn smarkets_error_maps_to_expected_venue_error_variants() {
    assert_eq!(
        VenueError::from(SmarketsError::LoginFailed),
        VenueError::Auth("smarkets authentication failed".to_string())
    );
    assert_eq!(
        VenueError::from(SmarketsError::SessionExpired),
        VenueError::Auth("smarkets authentication failed".to_string())
    );
    assert_eq!(
        VenueError::from(SmarketsError::RateLimited),
        VenueError::RateLimited
    );
    assert_eq!(
        VenueError::from(SmarketsError::HttpStatus(502)),
        VenueError::Other("smarkets http status 502".to_string())
    );
    assert_eq!(
        VenueError::from(SmarketsError::Deserialization("bad json".to_string())),
        VenueError::MalformedResponse("bad json".to_string())
    );
    assert_eq!(
        VenueError::from(SmarketsError::EndpointNotImplemented),
        VenueError::NotImplemented
    );
}
