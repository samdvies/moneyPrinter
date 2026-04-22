use std::collections::HashMap;

/// Runtime venue selection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VenueKind {
    /// In-memory scripted venue for development and tests.
    Mock,
    /// Smarkets HTTP-backed venue.
    Smarkets,
}

/// Smarkets credentials required for `VENUE=smarkets`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SmarketsCredentials {
    /// Smarkets username.
    pub username: String,
    /// Smarkets password.
    pub password: String,
}

/// Configuration parsing failures.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConfigError {
    /// Required environment variable was missing.
    MissingVar(&'static str),
    /// Environment variable had an invalid value.
    InvalidVar {
        /// Variable name.
        key: &'static str,
        /// Invalid value.
        value: String,
        /// Human-readable expectation.
        message: &'static str,
    },
}

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::MissingVar(key) => write!(f, "missing required environment variable: {key}"),
            Self::InvalidVar {
                key,
                value,
                message,
            } => write!(f, "invalid {key}={value:?}: {message}"),
        }
    }
}

impl std::error::Error for ConfigError {}

/// Parsed execution service configuration.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppConfig {
    /// Redis connection URL.
    pub redis_url: String,
    /// Venue implementation to use.
    pub venue: VenueKind,
    /// Smarkets API base URL.
    pub smarkets_base_url: String,
    /// Smarkets credentials, only present for `VENUE=smarkets`.
    pub smarkets_credentials: Option<SmarketsCredentials>,
    /// Outbound Smarkets limiter requests-per-second.
    pub smarkets_rate_limit_rps: u32,
    /// Outbound Smarkets limiter burst capacity.
    pub smarkets_rate_limit_burst: u32,
    /// Redis consumer name for execution group.
    pub execution_consumer_name: String,
    /// In-memory lifecycle map size cap.
    pub max_tracked_orders: usize,
    /// Graceful shutdown drain window in seconds.
    pub shutdown_drain_seconds: u64,
}

impl AppConfig {
    /// Parse config from process environment.
    pub fn from_env() -> Result<Self, ConfigError> {
        let vars: HashMap<String, String> = std::env::vars().collect();
        Self::from_map(&vars)
    }

    /// Parse config from a key/value map (used by tests).
    pub fn from_map(vars: &HashMap<String, String>) -> Result<Self, ConfigError> {
        let redis_url = get_with_default(vars, "REDIS_URL", "redis://127.0.0.1:6379");
        let venue = parse_venue(get_with_default(vars, "VENUE", "mock"))?;
        let smarkets_base_url =
            get_with_default(vars, "SMARKETS_BASE_URL", "https://api.smarkets.com/v3");
        let smarkets_rate_limit_rps = parse_u32(
            vars,
            "SMARKETS_RATE_LIMIT_RPS",
            5,
            "must be a positive integer",
        )?;
        let smarkets_rate_limit_burst = parse_u32(
            vars,
            "SMARKETS_RATE_LIMIT_BURST",
            10,
            "must be a positive integer",
        )?;
        let execution_consumer_name =
            vars.get("EXECUTION_CONSUMER_NAME")
                .cloned()
                .unwrap_or_else(|| match venue {
                    VenueKind::Mock => "execution-mock-1".to_string(),
                    VenueKind::Smarkets => "execution-smarkets-1".to_string(),
                });
        let max_tracked_orders = parse_usize(
            vars,
            "MAX_TRACKED_ORDERS",
            10_000,
            "must be a positive integer",
        )?;
        let shutdown_drain_seconds = parse_u64(
            vars,
            "SHUTDOWN_DRAIN_SECONDS",
            30,
            "must be a positive integer",
        )?;

        let smarkets_credentials = if venue == VenueKind::Smarkets {
            Some(SmarketsCredentials {
                username: get_required(vars, "SMARKETS_USERNAME")?,
                password: get_required(vars, "SMARKETS_PASSWORD")?,
            })
        } else {
            None
        };

        Ok(Self {
            redis_url,
            venue,
            smarkets_base_url,
            smarkets_credentials,
            smarkets_rate_limit_rps,
            smarkets_rate_limit_burst,
            execution_consumer_name,
            max_tracked_orders,
            shutdown_drain_seconds,
        })
    }
}

fn get_required(vars: &HashMap<String, String>, key: &'static str) -> Result<String, ConfigError> {
    vars.get(key)
        .filter(|value| !value.trim().is_empty())
        .cloned()
        .ok_or(ConfigError::MissingVar(key))
}

fn get_with_default(vars: &HashMap<String, String>, key: &str, default: &str) -> String {
    vars.get(key)
        .cloned()
        .unwrap_or_else(|| default.to_string())
}

fn parse_venue(value: String) -> Result<VenueKind, ConfigError> {
    match value.to_lowercase().as_str() {
        "mock" => Ok(VenueKind::Mock),
        "smarkets" => Ok(VenueKind::Smarkets),
        _ => Err(ConfigError::InvalidVar {
            key: "VENUE",
            value,
            message: "expected one of: mock, smarkets",
        }),
    }
}

fn parse_u32(
    vars: &HashMap<String, String>,
    key: &'static str,
    default: u32,
    message: &'static str,
) -> Result<u32, ConfigError> {
    let value = get_with_default(vars, key, &default.to_string());
    value.parse::<u32>().map_err(|_| ConfigError::InvalidVar {
        key,
        value,
        message,
    })
}

fn parse_u64(
    vars: &HashMap<String, String>,
    key: &'static str,
    default: u64,
    message: &'static str,
) -> Result<u64, ConfigError> {
    let value = get_with_default(vars, key, &default.to_string());
    value.parse::<u64>().map_err(|_| ConfigError::InvalidVar {
        key,
        value,
        message,
    })
}

fn parse_usize(
    vars: &HashMap<String, String>,
    key: &'static str,
    default: usize,
    message: &'static str,
) -> Result<usize, ConfigError> {
    let value = get_with_default(vars, key, &default.to_string());
    value.parse::<usize>().map_err(|_| ConfigError::InvalidVar {
        key,
        value,
        message,
    })
}
