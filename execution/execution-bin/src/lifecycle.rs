use std::sync::Arc;

use dashmap::DashMap;
use execution_core::{ExecutionResult, OrderId, OrderState};
use tokio::sync::Mutex;

/// In-memory lifecycle cache with emitted transition history.
pub struct LifecycleTracker {
    states: Arc<DashMap<OrderId, OrderState>>,
    published: Arc<Mutex<Vec<ExecutionResult>>>,
}

impl LifecycleTracker {
    /// Create a lifecycle tracker with a maximum order capacity.
    #[must_use]
    pub fn new(max_tracked_orders: usize) -> Self {
        Self {
            states: Arc::new(DashMap::with_capacity(max_tracked_orders)),
            published: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Transition one order and store a published execution result event.
    pub async fn transition(&self, order_id: OrderId, result: ExecutionResult) {
        self.states.insert(order_id, result.state.clone());
        self.published.lock().await.push(result);
    }

    /// Seed state used by reconciliation startup.
    pub fn seed(&self, order_id: OrderId, state: OrderState) {
        self.states.insert(order_id, state);
    }

    /// Snapshot current state for one order.
    #[must_use]
    pub fn current_state(&self, order_id: &OrderId) -> Option<OrderState> {
        self.states.get(order_id).map(|entry| entry.value().clone())
    }

    /// Return recorded published transition events.
    pub async fn published_events(&self) -> Vec<ExecutionResult> {
        self.published.lock().await.clone()
    }
}
