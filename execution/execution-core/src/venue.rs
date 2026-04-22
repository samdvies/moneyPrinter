use async_trait::async_trait;

use crate::{ExecutionResult, OrderId, OrderRequest, OrderState, VenueError};

/// Common venue contract shared by all execution adapters.
#[async_trait]
pub trait Venue: Send + Sync {
    /// Places an order on the venue.
    async fn place_order(&self, req: OrderRequest) -> Result<ExecutionResult, VenueError>;

    /// Cancels a previously placed order.
    async fn cancel_order(&self, id: OrderId) -> Result<ExecutionResult, VenueError>;

    /// Returns open order states known by the venue.
    async fn fetch_open_orders(&self) -> Result<Vec<OrderState>, VenueError>;

    /// Static venue name used for logs and metrics labels.
    fn venue_name(&self) -> &'static str;
}
