use execution_core::{ExecutionResult, OrderId, OrderRequest, OrderState, Venue, VenueError};

use crate::client::SmarketsClient;
use crate::endpoints;

/// Venue adapter that implements [`Venue`] on top of Smarkets HTTP APIs.
pub struct SmarketsVenue {
    client: SmarketsClient,
}

impl SmarketsVenue {
    /// Build a Smarkets venue from a configured client and limiter.
    #[must_use]
    pub fn new(client: SmarketsClient) -> Self {
        Self { client }
    }
}

#[async_trait::async_trait]
impl Venue for SmarketsVenue {
    async fn place_order(&self, req: OrderRequest) -> Result<ExecutionResult, VenueError> {
        endpoints::place_order(&self.client, &req)
            .await
            .map_err(Into::into)
    }

    async fn cancel_order(&self, id: OrderId) -> Result<ExecutionResult, VenueError> {
        endpoints::cancel_order(&self.client, &id)
            .await
            .map_err(Into::into)
    }

    async fn fetch_open_orders(&self) -> Result<Vec<OrderState>, VenueError> {
        endpoints::fetch_open_orders(&self.client)
            .await
            .map_err(Into::into)
    }

    fn venue_name(&self) -> &'static str {
        "smarkets"
    }
}
