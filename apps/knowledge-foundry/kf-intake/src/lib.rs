//! Shared Knowledge Foundry authority boundary.
//!
//! The CLI and PostgreSQL adapter both consume the same opaque, verified authority type so
//! caller-selected authority-domain or project strings cannot be reintroduced after signature
//! verification. Stored proofs can re-stream their scoped CAS bytes before database registration.

pub mod authority;
pub mod cas;
mod jcs;
