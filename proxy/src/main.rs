#![forbid(unsafe_code)]

use std::net::{Ipv4Addr, Ipv6Addr, SocketAddr};
use std::process::ExitCode;
use std::sync::{Arc, RwLock};
use std::time::Duration;

use imbi_egress_proxy::config::Config;
use imbi_egress_proxy::metrics;
use imbi_egress_proxy::pods::{self, PodMap};
use imbi_egress_proxy::policy::Keys;
use imbi_egress_proxy::proxy::{self, State};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio::signal::unix::{SignalKind, signal};
use tokio::sync::Semaphore;
use tokio::time::timeout;
use tracing_subscriber::EnvFilter;

const DRAIN: Duration = Duration::from_secs(30);

#[tokio::main]
async fn main() -> ExitCode {
    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("imbi-egress-proxy: {error}");
            ExitCode::FAILURE
        }
    }
}

async fn run() -> Result<(), String> {
    let config = Config::load(|name| std::env::var(name).ok())?;
    let filter =
        EnvFilter::try_new(&config.log).map_err(|e| format!("IMBI_EGRESS_PROXY_LOG: {e}"))?;
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(filter)
        .init();

    let client = kube::Client::try_default()
        .await
        .map_err(|e| format!("Kubernetes client: {e}"))?;
    let resolver = hickory_resolver::TokioResolver::builder_tokio()
        .map_err(|e| format!("DNS resolver: {e}"))?
        .build()
        .map_err(|e| format!("DNS resolver: {e}"))?;
    let pods = Arc::new(RwLock::new(PodMap::default()));
    let state = Arc::new(State {
        resolver,
        keys: Keys::new(
            config.secret.as_bytes(),
            config.previous_secret.as_deref().map(str::as_bytes),
        ),
        internal: config.internal_ranges.clone(),
        pods: pods.clone(),
        idle: config.idle,
        tunnels: Arc::new(Semaphore::new(config.max_tunnels)),
    });

    let listener = bind(config.port).await?;
    let admin = bind(config.admin_port).await?;
    tokio::spawn(pods::watch(client, config.namespace.clone(), pods.clone()));
    tokio::spawn(serve_admin(admin, pods));
    tracing::info!(
        port = config.port,
        admin_port = config.admin_port,
        "listening"
    );

    let mut term = signal(SignalKind::terminate()).map_err(|e| e.to_string())?;
    loop {
        tokio::select! {
            accepted = listener.accept() => {
                if let Ok((stream, peer)) = accepted {
                    tokio::spawn(proxy::serve(stream, peer.ip(), state.clone()));
                }
            }
            _ = term.recv() => break,
            _ = tokio::signal::ctrl_c() => break,
        }
    }

    // Stop accepting, then wait for the open tunnels.
    drop(listener);
    tracing::info!("draining");
    let idle = async {
        while state.tunnels.available_permits() < config.max_tunnels {
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
    };
    let _ = timeout(DRAIN, idle).await;
    Ok(())
}

/// Listen on every IPv6 and IPv4 address, or on IPv4 only when the host
/// has no IPv6.
async fn bind(port: u16) -> Result<TcpListener, String> {
    match TcpListener::bind(SocketAddr::from((Ipv6Addr::UNSPECIFIED, port))).await {
        Ok(listener) => Ok(listener),
        Err(_) => TcpListener::bind(SocketAddr::from((Ipv4Addr::UNSPECIFIED, port)))
            .await
            .map_err(|e| format!("bind port {port}: {e}")),
    }
}

/// `/healthz`, `/readyz`, and `/metrics`. One request per connection.
async fn serve_admin(listener: TcpListener, pods: Arc<RwLock<PodMap>>) {
    loop {
        let Ok((mut stream, _)) = listener.accept().await else {
            continue;
        };
        let pods = pods.clone();
        tokio::spawn(async move {
            let mut buf = [0u8; 1024];
            let Ok(Ok(n)) = timeout(Duration::from_secs(5), stream.read(&mut buf)).await else {
                return;
            };
            let head = String::from_utf8_lossy(&buf[..n]);
            let path = head.split(' ').nth(1).unwrap_or_default();
            let ready = pods.read().is_ok_and(|p| p.is_ready());
            let (status, body) = match path {
                "/healthz" => ("200 OK", "ok\n".to_owned()),
                "/readyz" if ready => ("200 OK", "ok\n".to_owned()),
                "/readyz" => ("503 Service Unavailable", "pod list not done\n".to_owned()),
                "/metrics" => ("200 OK", metrics::render()),
                _ => ("404 Not Found", String::new()),
            };
            let response = format!(
                "HTTP/1.1 {status}\r\nContent-Type: text/plain; version=0.0.4\r\n\
                 Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = stream.write_all(response.as_bytes()).await;
        });
    }
}
