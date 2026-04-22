use execution_core::{ExecutionResult, OrderRequest, VenueError};
use fred::interfaces::{ClientLike, StreamsInterface};
use fred::prelude::{Builder, RedisClient, RedisConfig, RedisError, RedisErrorKind};
use fred::types::XReadResponse;

/// Redis stream names used by the execution service.
pub const ORDER_SIGNALS_STREAM: &str = "order.signals";
/// Output stream for execution results.
pub const EXECUTION_RESULTS_STREAM: &str = "execution.results";
/// Dead-letter stream for malformed messages.
pub const ORDER_SIGNALS_DEADLETTER_STREAM: &str = "order.signals.deadletter";

/// A decoded order signal pulled from Redis.
#[derive(Debug, Clone)]
pub struct PendingSignal {
    /// Redis stream entry id.
    pub entry_id: String,
    /// Parsed order payload.
    pub order: OrderRequest,
    /// Raw JSON payload used for dead-letter forwarding on downstream validation failures.
    pub raw_json: String,
}

/// Thin wrapper around fred for stream operations.
#[derive(Clone)]
pub struct Bus {
    client: RedisClient,
}

impl Bus {
    /// Connect to Redis and return a bus wrapper.
    pub async fn connect(redis_url: &str) -> Result<Self, RedisError> {
        let config = RedisConfig::from_url(redis_url)?;
        let client = Builder::from_config(config).build()?;
        let _connection_task = client.init().await?;
        client.wait_for_connect().await?;
        Ok(Self { client })
    }

    /// Ensure consumer group exists for order-signals stream.
    pub async fn ensure_group(&self, group: &str) -> Result<(), RedisError> {
        let created: Result<(), RedisError> = self
            .client
            .xgroup_create(
                ORDER_SIGNALS_STREAM,
                group,
                "$",
                true, // MKSTREAM
            )
            .await;
        match created {
            Ok(()) => Ok(()),
            Err(err)
                if err.kind() == &RedisErrorKind::Unknown
                    && err.to_string().contains("BUSYGROUP") =>
            {
                Ok(())
            }
            Err(err) => Err(err),
        }
    }

    /// Read one batch from the order-signals stream.
    pub async fn read_batch(
        &self,
        group: &str,
        consumer: &str,
        count: u64,
        block_ms: u64,
    ) -> Result<Vec<PendingSignal>, RedisError> {
        let values: XReadResponse<String, String, String, String> = self
            .client
            .xreadgroup_map(
                group,
                consumer,
                Some(count),
                Some(block_ms),
                false,
                ORDER_SIGNALS_STREAM,
                ">",
            )
            .await?;

        let mut out = Vec::new();
        for (_stream_name, entries) in values {
            for (entry_id, field_map) in entries {
                if let Some(raw_json) = field_map.get("json") {
                    match serde_json::from_str::<OrderRequest>(raw_json) {
                        Ok(order) => out.push(PendingSignal {
                            entry_id,
                            order,
                            raw_json: raw_json.clone(),
                        }),
                        Err(_err) => {
                            // leave malformed handling to caller via dead-letter path
                        }
                    }
                }
            }
        }
        Ok(out)
    }

    /// Publish one execution result record and return generated stream id.
    pub async fn publish_result(&self, result: &ExecutionResult) -> Result<String, RedisError> {
        let payload = serde_json::to_string(result).map_err(|err| {
            RedisError::new(
                RedisErrorKind::Unknown,
                format!("failed to serialize execution result: {err}"),
            )
        })?;
        self.client
            .xadd(
                EXECUTION_RESULTS_STREAM,
                true,
                None,
                "*",
                vec![("json", payload)],
            )
            .await
    }

    /// Publish dead-letter payload for malformed signals.
    pub async fn publish_deadletter(
        &self,
        entry_id: &str,
        raw_payload: &str,
        reason: &str,
    ) -> Result<String, RedisError> {
        self.client
            .xadd(
                ORDER_SIGNALS_DEADLETTER_STREAM,
                true,
                None,
                "*",
                vec![
                    ("entry_id", entry_id),
                    ("raw", raw_payload),
                    ("reason", reason),
                ],
            )
            .await
    }

    /// Ack a processed order-signal entry.
    pub async fn ack_signal(&self, group: &str, entry_id: &str) -> Result<i64, RedisError> {
        self.client
            .xack(ORDER_SIGNALS_STREAM, group, vec![entry_id])
            .await
    }
}

/// Parse an order signal payload or return schema error.
pub fn parse_signal(raw_json: &str) -> Result<OrderRequest, VenueError> {
    serde_json::from_str(raw_json)
        .map_err(|err| VenueError::MalformedResponse(format!("invalid order signal: {err}")))
}
