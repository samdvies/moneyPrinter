//! Shared modules for the `execution-bin` binary and integration tests.

use std::sync::Arc;

use anyhow::Result;
use chrono::Utc;
use execution_core::{ExecutionResult, MockVenue, OrderId, Venue};
use execution_smarkets::{SmarketsClient, SmarketsRateLimiter, SmarketsVenue};
use rust_decimal::Decimal;
use tokio::signal;
use tracing::{error, info, warn};

use crate::bus::Bus;
use crate::config::{AppConfig, VenueKind};
use crate::lifecycle::LifecycleTracker;
use crate::reconcile::reconcile_startup;

pub mod bus;
pub mod config;
pub mod lifecycle;
pub mod reconcile;

fn build_venue(config: &AppConfig) -> Result<Arc<dyn Venue>> {
    match config.venue {
        VenueKind::Mock => Ok(Arc::new(MockVenue::default())),
        VenueKind::Smarkets => {
            let creds = config.smarkets_credentials.as_ref().ok_or_else(|| {
                anyhow::anyhow!("smarkets credentials missing while VENUE=smarkets")
            })?;
            let limiter = SmarketsRateLimiter::new(
                config.smarkets_rate_limit_rps,
                config.smarkets_rate_limit_burst,
            );
            let client = SmarketsClient::new(
                config.smarkets_base_url.clone(),
                creds.username.clone(),
                creds.password.clone(),
                limiter,
            );
            Ok(Arc::new(SmarketsVenue::new(client)))
        }
    }
}

/// Run the execution service main loop.
pub async fn run() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "execution_bin=info".into()),
        )
        .init();

    let config = AppConfig::from_env()?;
    info!(?config.venue, "starting execution-bin");

    let venue = build_venue(&config)?;
    let bus = Arc::new(Bus::connect(&config.redis_url).await?);
    bus.ensure_group("execution").await?;

    let tracker = LifecycleTracker::new(config.max_tracked_orders);
    if let Err(err) = reconcile_startup(Arc::clone(&venue), &tracker).await {
        if matches!(err, execution_core::VenueError::NotImplemented) {
            warn!("venue reconciliation not implemented; continuing startup");
        } else {
            return Err(err.into());
        }
    }

    let mut sigterm = signal::unix::signal(signal::unix::SignalKind::terminate())?;

    loop {
        tokio::select! {
            _ = sigterm.recv() => {
                info!("received SIGTERM; beginning graceful shutdown");
                tokio::time::sleep(std::time::Duration::from_secs(config.shutdown_drain_seconds)).await;
                break;
            }
            read = bus.read_batch("execution", &config.execution_consumer_name, 32, 1000) => {
                let batch = read?;
                for pending in batch {
                    let order_id: OrderId = pending.order.client_order_id.clone();
                    let result = match venue.place_order(pending.order).await {
                        Ok(ok) => ok,
                        Err(err) => ExecutionResult {
                            client_order_id: order_id.clone(),
                            venue_order_id: None,
                            state: execution_core::OrderState::Rejected,
                            filled_stake: Decimal::ZERO,
                            avg_fill_price: None,
                            ts_utc: Utc::now(),
                            schema_version: 1,
                        }
                        .tap(|_| error!(error = %err, "venue order placement failed")),
                    };

                    tracker.transition(order_id, result.clone()).await;
                    bus.publish_result(&result).await?;
                    bus.ack_signal("execution", &pending.entry_id).await?;
                }
            }
        }
    }

    Ok(())
}

trait Tap: Sized {
    fn tap<F: FnOnce(&Self)>(self, f: F) -> Self {
        f(&self);
        self
    }
}

impl<T> Tap for T {}
