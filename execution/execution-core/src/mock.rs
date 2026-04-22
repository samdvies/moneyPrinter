use std::sync::Arc;
use std::time::Duration;

use tokio::sync::Mutex;

use crate::{ExecutionResult, OrderId, OrderRequest, OrderState, Venue, VenueError};

type Predicate = Arc<dyn Fn(&OrderRequest) -> bool + Send + Sync>;

/// Scripted response variants for [`MockVenue`].
#[derive(Clone)]
pub enum MockResponse {
    /// Fully filled at request price.
    Fill,
    /// Partially filled with explicit stake/price.
    PartialFill {
        /// Filled stake amount.
        filled_stake: rust_decimal::Decimal,
        /// Average fill price for the partial fill.
        avg_fill_price: rust_decimal::Decimal,
    },
    /// Rejected by venue with a reason.
    Reject(String),
    /// Return a hard venue error.
    Error(VenueError),
    /// Delay then execute nested response.
    Delay {
        /// Delay duration before evaluating nested response.
        duration: Duration,
        /// Nested response to execute after delay.
        response: Box<MockResponse>,
    },
}

impl MockResponse {
    /// Convenience constructor for delayed responses.
    #[must_use]
    pub fn delay(duration: Duration, response: MockResponse) -> Self {
        Self::Delay {
            duration,
            response: Box::new(response),
        }
    }
}

/// One conditional behavior in the mock matrix.
#[derive(Clone)]
pub struct MockBehavior {
    predicate: Predicate,
    response: MockResponse,
}

impl MockBehavior {
    /// Create a behavior from predicate + response.
    #[must_use]
    pub fn new<F>(predicate: F, response: MockResponse) -> Self
    where
        F: Fn(&OrderRequest) -> bool + Send + Sync + 'static,
    {
        Self {
            predicate: Arc::new(predicate),
            response,
        }
    }
}

/// Scriptable in-memory venue for tests and local dev.
pub struct MockVenue {
    behaviors: Vec<MockBehavior>,
    store: Arc<Mutex<Vec<ExecutionResult>>>,
}

impl MockVenue {
    /// Create a venue with a behavior matrix.
    #[must_use]
    pub fn new(behaviors: Vec<MockBehavior>) -> Self {
        Self::with_store_and_behaviors(Arc::new(Mutex::new(vec![])), behaviors)
    }

    /// Construct a venue preloaded with open orders.
    #[must_use]
    pub fn with_open_orders(open_orders: Vec<ExecutionResult>) -> Self {
        Self::with_store_and_behaviors(Arc::new(Mutex::new(open_orders)), vec![])
    }

    /// Construct a venue using externally shared storage.
    #[must_use]
    pub fn with_store(store: Arc<Mutex<Vec<ExecutionResult>>>) -> Self {
        Self::with_store_and_behaviors(store, vec![])
    }

    fn with_store_and_behaviors(
        store: Arc<Mutex<Vec<ExecutionResult>>>,
        behaviors: Vec<MockBehavior>,
    ) -> Self {
        Self { behaviors, store }
    }

    /// Create the default venue that fills all orders.
    #[must_use]
    pub fn default_fill() -> Self {
        Self::new(vec![])
    }

    fn select_response(&self, req: &OrderRequest) -> MockResponse {
        self.behaviors
            .iter()
            .find_map(|behavior| {
                if (behavior.predicate)(req) {
                    Some(behavior.response.clone())
                } else {
                    None
                }
            })
            .unwrap_or(MockResponse::Fill)
    }

    async fn execute_response(
        &self,
        req: &OrderRequest,
        response: MockResponse,
    ) -> Result<ExecutionResult, VenueError> {
        let mut current = response;
        loop {
            match current {
                MockResponse::Fill => {
                    return Ok(ExecutionResult {
                        client_order_id: req.client_order_id.clone(),
                        venue_order_id: Some(format!("mock-{}", req.client_order_id.as_str())),
                        state: OrderState::Filled,
                        filled_stake: req.stake,
                        avg_fill_price: Some(req.price),
                        ts_utc: chrono::Utc::now(),
                        schema_version: req.schema_version,
                    });
                }
                MockResponse::PartialFill {
                    filled_stake,
                    avg_fill_price,
                } => {
                    return Ok(ExecutionResult {
                        client_order_id: req.client_order_id.clone(),
                        venue_order_id: Some(format!("mock-{}", req.client_order_id.as_str())),
                        state: OrderState::PartiallyFilled,
                        filled_stake,
                        avg_fill_price: Some(avg_fill_price),
                        ts_utc: chrono::Utc::now(),
                        schema_version: req.schema_version,
                    });
                }
                MockResponse::Reject(_reason) => {
                    // The shared execution result contract does not include a rejection reason field.
                    return Ok(ExecutionResult {
                        client_order_id: req.client_order_id.clone(),
                        venue_order_id: None,
                        state: OrderState::Rejected,
                        filled_stake: rust_decimal::Decimal::ZERO,
                        avg_fill_price: None,
                        ts_utc: chrono::Utc::now(),
                        schema_version: req.schema_version,
                    });
                }
                MockResponse::Error(err) => return Err(err),
                MockResponse::Delay { duration, response } => {
                    tokio::time::sleep(duration).await;
                    current = *response;
                }
            }
        }
    }

    fn upsert_result(store: &mut Vec<ExecutionResult>, result: ExecutionResult) {
        if let Some(existing) = store
            .iter_mut()
            .find(|item| item.client_order_id == result.client_order_id)
        {
            *existing = result;
        } else {
            store.push(result);
        }
    }

    fn is_open_state(state: &OrderState) -> bool {
        matches!(
            state,
            OrderState::Submitted | OrderState::Accepted | OrderState::PartiallyFilled
        )
    }
}

impl Default for MockVenue {
    fn default() -> Self {
        Self::default_fill()
    }
}

#[async_trait::async_trait]
impl Venue for MockVenue {
    async fn place_order(&self, req: OrderRequest) -> Result<ExecutionResult, VenueError> {
        let response = self.select_response(&req);
        let result = self.execute_response(&req, response).await?;
        let mut guard = self.store.lock().await;
        Self::upsert_result(&mut guard, result.clone());
        Ok(result)
    }

    async fn cancel_order(&self, id: OrderId) -> Result<ExecutionResult, VenueError> {
        let mut guard = self.store.lock().await;
        let Some(existing) = guard.iter_mut().find(|item| item.client_order_id == id) else {
            return Err(VenueError::Other(format!(
                "order {} not found",
                id.as_str()
            )));
        };

        if !Self::is_open_state(&existing.state) {
            return Err(VenueError::Other("already terminal".to_string()));
        }

        existing.state = OrderState::Cancelled;
        existing.venue_order_id = existing
            .venue_order_id
            .clone()
            .or_else(|| Some(format!("mock-{}", id.as_str())));
        existing.ts_utc = chrono::Utc::now();
        Ok(existing.clone())
    }

    async fn fetch_open_orders(&self) -> Result<Vec<OrderState>, VenueError> {
        let guard = self.store.lock().await;
        Ok(guard
            .iter()
            .filter(|result| Self::is_open_state(&result.state))
            .map(|result| result.state.clone())
            .collect::<Vec<_>>())
    }

    fn venue_name(&self) -> &'static str {
        "mock"
    }
}
