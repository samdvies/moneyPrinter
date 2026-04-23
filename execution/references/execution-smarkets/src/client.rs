use std::sync::Arc;
use std::time::Duration;

use serde::Deserialize;
use tokio::sync::RwLock;
use tokio::time::Instant;

use crate::{SmarketsError, SmarketsRateLimiter};

#[derive(Clone, Debug)]
struct SessionState {
    token: String,
    expires_at: Instant,
}

/// Authenticated session details returned by login.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Session {
    /// Session token used in outbound requests.
    pub token: String,
    /// Session duration in seconds.
    pub expires_in_seconds: u64,
}

/// Minimal authenticated HTTP client for Smarkets endpoints.
#[derive(Clone)]
pub struct SmarketsClient {
    http: reqwest::Client,
    base_url: String,
    username: String,
    password: String,
    limiter: SmarketsRateLimiter,
    session: Arc<RwLock<Option<SessionState>>>,
}

impl SmarketsClient {
    /// Build a new Smarkets client instance.
    #[must_use]
    pub fn new(
        base_url: impl Into<String>,
        username: impl Into<String>,
        password: impl Into<String>,
        limiter: SmarketsRateLimiter,
    ) -> Self {
        Self {
            http: reqwest::Client::new(),
            base_url: base_url.into(),
            username: username.into(),
            password: password.into(),
            limiter,
            session: Arc::new(RwLock::new(None)),
        }
    }

    /// Logs in and stores an active session.
    pub async fn login(&self) -> Result<Session, SmarketsError> {
        self.limiter.acquire().await;
        let login_url = format!("{}/sessions", self.base_url.trim_end_matches('/'));
        let resp = self
            .http
            .post(login_url)
            .json(&serde_json::json!({
                "username": self.username,
                "password": self.password,
            }))
            .send()
            .await
            .map_err(|err| SmarketsError::Deserialization(err.to_string()))?;

        if resp.status() == reqwest::StatusCode::UNAUTHORIZED {
            return Err(SmarketsError::LoginFailed);
        }
        if resp.status() == reqwest::StatusCode::TOO_MANY_REQUESTS {
            return Err(SmarketsError::RateLimited);
        }
        if !resp.status().is_success() {
            return Err(SmarketsError::HttpStatus(resp.status().as_u16()));
        }

        let body: LoginResponse = resp
            .json()
            .await
            .map_err(|err| SmarketsError::Deserialization(err.to_string()))?;
        let token = body.session_token;
        let expires = body.expires_in_seconds.max(1);
        {
            let mut guard = self.session.write().await;
            *guard = Some(SessionState {
                token: token.clone(),
                expires_at: Instant::now() + Duration::from_secs(expires),
            });
        }

        Ok(Session {
            token,
            expires_in_seconds: expires,
        })
    }

    /// Sends a request requiring auth, with one re-login retry on 401.
    pub async fn send_authenticated_json(
        &self,
        method: reqwest::Method,
        path: &str,
    ) -> Result<serde_json::Value, SmarketsError> {
        let mut attempt = 0;
        loop {
            let token = self.ensure_session().await?;
            self.limiter.acquire().await;
            let url = format!(
                "{}/{}",
                self.base_url.trim_end_matches('/'),
                path.trim_start_matches('/')
            );
            let resp = self
                .http
                .request(method.clone(), url)
                .header("session-token", token)
                .send()
                .await
                .map_err(|err| SmarketsError::Deserialization(err.to_string()))?;

            if resp.status() == reqwest::StatusCode::UNAUTHORIZED && attempt == 0 {
                {
                    let mut guard = self.session.write().await;
                    *guard = None;
                }
                self.login().await?;
                attempt += 1;
                continue;
            }
            if resp.status() == reqwest::StatusCode::TOO_MANY_REQUESTS {
                return Err(SmarketsError::RateLimited);
            }
            if !resp.status().is_success() {
                return Err(SmarketsError::HttpStatus(resp.status().as_u16()));
            }
            return resp
                .json()
                .await
                .map_err(|err| SmarketsError::Deserialization(err.to_string()));
        }
    }

    async fn ensure_session(&self) -> Result<String, SmarketsError> {
        {
            let guard = self.session.read().await;
            if let Some(state) = guard.as_ref() {
                if Instant::now() < state.expires_at {
                    return Ok(state.token.clone());
                }
            }
        }

        let session = self.login().await?;
        Ok(session.token)
    }
}

#[derive(Deserialize)]
struct LoginResponse {
    session_token: String,
    expires_in_seconds: u64,
}
