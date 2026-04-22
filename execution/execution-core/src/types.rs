use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use serde::de::{self, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use std::fmt;

const SCHEMA_VERSION_V1: u32 = 1;

fn deserialize_schema_version<'de, D>(deserializer: D) -> Result<u32, D::Error>
where
    D: Deserializer<'de>,
{
    struct SchemaVersionVisitor;

    impl Visitor<'_> for SchemaVersionVisitor {
        type Value = u32;

        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("schema version 1")
        }

        fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            if value == u64::from(SCHEMA_VERSION_V1) {
                Ok(SCHEMA_VERSION_V1)
            } else {
                Err(E::custom(format!(
                    "unsupported schema_version {value}; expected {SCHEMA_VERSION_V1}",
                )))
            }
        }
    }

    deserializer.deserialize_u64(SchemaVersionVisitor)
}

/// Order identifier used by execution services.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(transparent)]
pub struct OrderId(String);

impl OrderId {
    /// Creates a new order identifier.
    #[must_use]
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Returns the underlying identifier string.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Side of a sports-exchange order.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum Side {
    /// Back the selection.
    Back,
    /// Lay the selection.
    Lay,
}

/// Venue order lifecycle status.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum OrderState {
    /// Request accepted by local execution loop.
    Submitted,
    /// Venue accepted the order.
    Accepted,
    /// Order has at least one fill but is not complete.
    PartiallyFilled,
    /// Order has been fully filled.
    Filled,
    /// Order was cancelled.
    Cancelled,
    /// Order was rejected.
    Rejected,
}

/// Order request sent to a venue implementation.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct OrderRequest {
    /// Local client-side order identifier.
    pub client_order_id: OrderId,
    /// Venue market identifier.
    pub market_id: String,
    /// Venue selection identifier.
    pub selection_id: String,
    /// Back or lay side.
    pub side: Side,
    /// Requested odds price.
    pub price: Decimal,
    /// Requested stake size.
    pub stake: Decimal,
    /// Message schema version.
    #[serde(deserialize_with = "deserialize_schema_version")]
    pub schema_version: u32,
}

/// Execution outcome emitted by a venue implementation.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ExecutionResult {
    /// Local client-side order identifier.
    pub client_order_id: OrderId,
    /// Venue-side order identifier when available.
    pub venue_order_id: Option<String>,
    /// Latest known order state.
    pub state: OrderState,
    /// Filled stake amount.
    pub filled_stake: Decimal,
    /// Average fill price when fills exist.
    pub avg_fill_price: Option<Decimal>,
    /// Event timestamp in UTC.
    pub ts_utc: DateTime<Utc>,
    /// Message schema version.
    #[serde(deserialize_with = "deserialize_schema_version")]
    pub schema_version: u32,
}
