//! Core execution types and the `Venue` trait.
//!
//! This crate defines the shared contract every venue implementation must
//! satisfy. Types here mirror `algobet_common.schemas` on the Python side;
//! the `scripts/check_schema_parity.py` check guards drift.

#![deny(missing_docs)]

mod error;
mod types;
mod venue;

pub use error::VenueError;
pub use types::{ExecutionResult, OrderId, OrderRequest, OrderState, Side};
pub use venue::Venue;
