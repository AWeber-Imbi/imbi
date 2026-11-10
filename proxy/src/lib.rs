//! The egress proxy of the Imbi agent harness.
//!
//! A `CONNECT` proxy. It lets a runner pod reach a public host, or an
//! internal host name that the chain of the pod holds. See
//! `docs/harness-egress-proxy-plan.md`, section 5.4.
#![forbid(unsafe_code)]

pub mod config;
pub mod metrics;
pub mod pods;
pub mod policy;
pub mod proxy;
pub mod request;
