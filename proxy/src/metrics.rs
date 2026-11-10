//! Prometheus metrics (plan 12.3, K4).

use std::sync::LazyLock;

use prometheus::{
    Encoder, Histogram, IntCounterVec, IntGauge, TextEncoder, register_histogram,
    register_int_counter_vec, register_int_gauge,
};

pub static DECISIONS: LazyLock<IntCounterVec> = LazyLock::new(|| {
    register_int_counter_vec!(
        "imbi_egress_proxy_decisions_total",
        "Decisions by reply status and reason",
        &["result", "reason"]
    )
    .expect("register metric")
});

pub static TUNNELS: LazyLock<IntGauge> = LazyLock::new(|| {
    register_int_gauge!("imbi_egress_proxy_tunnels_active", "Open connections")
        .expect("register metric")
});

pub static BYTES: LazyLock<IntCounterVec> = LazyLock::new(|| {
    register_int_counter_vec!(
        "imbi_egress_proxy_bytes_total",
        "Bytes copied through tunnels, by direction",
        &["direction"]
    )
    .expect("register metric")
});

pub static DNS_SECONDS: LazyLock<Histogram> = LazyLock::new(|| {
    register_histogram!("imbi_egress_proxy_dns_seconds", "DNS lookup time")
        .expect("register metric")
});

pub static WATCH_UP: LazyLock<IntGauge> = LazyLock::new(|| {
    register_int_gauge!(
        "imbi_egress_proxy_watch_up",
        "1 when the last pod watch event was not an error"
    )
    .expect("register metric")
});

pub static PODS: LazyLock<IntGauge> = LazyLock::new(|| {
    register_int_gauge!("imbi_egress_proxy_pods", "Runner pods in the pod map")
        .expect("register metric")
});

/// The text exposition of every registered metric.
pub fn render() -> String {
    // Register every metric, so that a scrape shows them before they change.
    for gauge in [&*TUNNELS, &*WATCH_UP, &*PODS] {
        let _ = gauge.get();
    }
    let _ = (&*DECISIONS, &*BYTES, &*DNS_SECONDS);
    let mut out = Vec::new();
    TextEncoder::new()
        .encode(&prometheus::gather(), &mut out)
        .expect("encode metrics");
    String::from_utf8(out).unwrap_or_default()
}
