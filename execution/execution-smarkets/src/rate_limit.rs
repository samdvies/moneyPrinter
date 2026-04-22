use governor::clock::DefaultClock;
use governor::state::InMemoryState;
use governor::state::NotKeyed;
use governor::{Quota, RateLimiter as GovernorRateLimiter};
use std::num::NonZeroU32;
use std::sync::Arc;

/// Wrapper around a non-keyed governor rate limiter.
#[derive(Clone)]
pub struct SmarketsRateLimiter {
    inner: Arc<GovernorRateLimiter<NotKeyed, InMemoryState, DefaultClock>>,
}

impl SmarketsRateLimiter {
    /// Construct a limiter with request-per-second and burst settings.
    #[must_use]
    pub fn new(rps: u32, burst: u32) -> Self {
        let normalized_rps = rps.max(1);
        let normalized_burst = burst.max(1);
        let mut quota = Quota::per_second(
            NonZeroU32::new(normalized_rps).expect("normalized rps must be non-zero"),
        );
        quota = quota.allow_burst(
            NonZeroU32::new(normalized_burst).expect("normalized burst must be non-zero"),
        );

        Self {
            inner: Arc::new(GovernorRateLimiter::direct(quota)),
        }
    }

    /// Waits until the limiter allows one request.
    pub async fn acquire(&self) {
        self.inner.until_ready().await;
    }
}
