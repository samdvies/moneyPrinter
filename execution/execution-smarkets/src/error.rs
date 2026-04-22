use execution_core::VenueError;
use thiserror::Error;

/// Errors emitted by the Smarkets adapter layer.
#[derive(Debug, Clone, Error, PartialEq, Eq)]
pub enum SmarketsError {
    /// Login request failed.
    #[error("login failed")]
    LoginFailed,
    /// Existing session is no longer valid.
    #[error("session expired")]
    SessionExpired,
    /// Venue responded with rate limiting.
    #[error("rate limited")]
    RateLimited,
    /// Unexpected HTTP status code.
    #[error("unexpected HTTP status {0}")]
    HttpStatus(u16),
    /// Response body could not be deserialized.
    #[error("deserialization error: {0}")]
    Deserialization(String),
    /// Placeholder until 7b endpoint bodies are implemented.
    #[error("endpoint not implemented")]
    EndpointNotImplemented,
}

impl From<SmarketsError> for VenueError {
    fn from(value: SmarketsError) -> Self {
        match value {
            SmarketsError::LoginFailed | SmarketsError::SessionExpired => {
                Self::Auth("smarkets authentication failed".to_string())
            }
            SmarketsError::RateLimited => Self::RateLimited,
            SmarketsError::HttpStatus(code) => Self::Other(format!("smarkets http status {code}")),
            SmarketsError::Deserialization(msg) => Self::MalformedResponse(msg),
            SmarketsError::EndpointNotImplemented => Self::NotImplemented,
        }
    }
}
