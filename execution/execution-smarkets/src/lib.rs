//! Smarkets venue crate scaffold for execution.
//!
//! This crate provides shared Smarkets-specific primitives used by the
//! execution binary and the venue implementation.

#![deny(missing_docs)]

/// HTTP auth client and session lifecycle for Smarkets.
pub mod client;
/// Endpoint wrappers used by the venue adapter.
pub mod endpoints;
/// Smarkets-specific error types and mappings.
pub mod error;
/// Governor-backed outbound request rate limiter.
pub mod rate_limit;
/// `Venue` trait adapter backed by Smarkets API.
pub mod venue_impl;

pub use client::{Session, SmarketsClient};
pub use endpoints::{cancel_order, fetch_markets, fetch_open_orders, place_order};
pub use error::SmarketsError;
pub use rate_limit::SmarketsRateLimiter;
pub use venue_impl::SmarketsVenue;
