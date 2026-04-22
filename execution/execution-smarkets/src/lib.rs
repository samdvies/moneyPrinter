//! Smarkets venue crate scaffold for execution.
//!
//! This crate provides shared Smarkets-specific primitives used by the
//! execution binary and the venue implementation.

#![deny(missing_docs)]

/// Smarkets-specific error types and mappings.
pub mod error;
/// Governor-backed outbound request rate limiter.
pub mod rate_limit;

pub use error::SmarketsError;
pub use rate_limit::SmarketsRateLimiter;
