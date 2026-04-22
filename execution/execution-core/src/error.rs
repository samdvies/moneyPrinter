use thiserror::Error;

/// Errors returned by venue implementations.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum VenueError {
    /// Authentication failed or expired.
    #[error("authentication error: {0}")]
    Auth(String),
    /// Venue or upstream proxy returned a rate-limit response.
    #[error("rate limited")]
    RateLimited,
    /// Timeout while waiting for network I/O.
    #[error("network timeout")]
    NetworkTimeout,
    /// Response payload did not match expected schema.
    #[error("malformed response: {0}")]
    MalformedResponse(String),
    /// Venue rejected the order request.
    #[error("order rejected: {0}")]
    Rejected(String),
    /// Endpoint exists in the trait but implementation is not yet complete.
    #[error("not implemented")]
    NotImplemented,
    /// Catch-all for transport or internal errors.
    #[error("{0}")]
    Other(String),
}
