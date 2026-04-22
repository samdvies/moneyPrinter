use std::sync::Arc;

use execution_core::{OrderId, Venue, VenueError};
use tracing::warn;

use crate::lifecycle::LifecycleTracker;

/// Rebuilds local lifecycle cache from venue open orders.
pub async fn reconcile_startup(
    venue: Arc<dyn Venue>,
    lifecycle: &LifecycleTracker,
) -> Result<(), VenueError> {
    match venue.fetch_open_orders().await {
        Ok(states) => {
            for (idx, state) in states.into_iter().enumerate() {
                // Startup reconciliation in 7a only tracks state snapshots; IDs are placeholders.
                lifecycle.seed(OrderId::new(format!("reconcile-{idx}")), state);
            }
            Ok(())
        }
        Err(VenueError::NotImplemented) => {
            warn!("venue open-order reconciliation not implemented; continuing startup");
            Ok(())
        }
        Err(err) => Err(err),
    }
}
