use execution_core::{ExecutionResult, OrderId, OrderRequest, OrderState};

use crate::{SmarketsClient, SmarketsError};

/// Attempt to fetch markets from Smarkets.
///
/// 7a keeps this as a scaffold and returns `EndpointNotImplemented`.
pub async fn fetch_markets(client: &SmarketsClient) -> Result<serde_json::Value, SmarketsError> {
    let _ = client;
    Err(SmarketsError::EndpointNotImplemented)
}

/// Place an order on Smarkets.
///
/// 7a intentionally leaves this endpoint stubbed.
pub async fn place_order(
    client: &SmarketsClient,
    req: &OrderRequest,
) -> Result<ExecutionResult, SmarketsError> {
    let _ = (client, req);
    Err(SmarketsError::EndpointNotImplemented)
}

/// Cancel an order on Smarkets.
///
/// 7a intentionally leaves this endpoint stubbed.
pub async fn cancel_order(
    client: &SmarketsClient,
    order_id: &OrderId,
) -> Result<ExecutionResult, SmarketsError> {
    let _ = (client, order_id);
    Err(SmarketsError::EndpointNotImplemented)
}

/// Fetch open orders from Smarkets.
///
/// 7a intentionally leaves this endpoint stubbed.
pub async fn fetch_open_orders(client: &SmarketsClient) -> Result<Vec<OrderState>, SmarketsError> {
    let _ = client;
    Err(SmarketsError::EndpointNotImplemented)
}
