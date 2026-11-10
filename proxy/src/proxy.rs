//! One proxy connection: read, decide, connect, copy.

use std::future::Future;
use std::io;
use std::net::{IpAddr, SocketAddr};
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, RwLock};
use std::task::{Context, Poll};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use ipnet::IpNet;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt, ReadBuf};
use tokio::net::TcpStream;
use tokio::sync::Semaphore;
use tokio::time::{sleep_until, timeout};

use crate::metrics;
use crate::pods::PodMap;
use crate::policy::{self, Connection, Decision, Keys};
use crate::request::{self, Refusal, Request};

const HEAD_TIMEOUT: Duration = Duration::from_secs(10);
const DNS_TIMEOUT: Duration = Duration::from_secs(5);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_ADDRESSES: usize = 16;

/// Resolve a host name to its addresses. A fake takes its place in tests.
pub trait Resolve: Send + Sync + 'static {
    fn lookup(&self, host: &str) -> impl Future<Output = Vec<IpAddr>> + Send;
}

impl Resolve for hickory_resolver::TokioResolver {
    async fn lookup(&self, host: &str) -> Vec<IpAddr> {
        // The trailing dot makes the name absolute, so that the search
        // domains of the pod do not apply.
        match self.lookup_ip(format!("{host}.")).await {
            Ok(lookup) => lookup.iter().collect(),
            Err(_) => Vec::new(),
        }
    }
}

pub struct State<R> {
    pub resolver: R,
    pub keys: Keys,
    pub internal: Vec<IpNet>,
    pub pods: Arc<RwLock<PodMap>>,
    pub idle: Duration,
    pub tunnels: Arc<Semaphore>,
}

/// Serve one client connection to its end.
pub async fn serve<R: Resolve>(mut client: TcpStream, source: IpAddr, state: Arc<State<R>>) {
    let source = source.to_canonical();
    // Read the head before the tunnel limit: a reply to a client with
    // unread bytes can be lost to a reset. The head read has a time and
    // a size limit.
    let request = match timeout(HEAD_TIMEOUT, read_head(&mut client)).await {
        Ok(Ok(request)) => request,
        Ok(Err(r)) => {
            let decision = refused(r.status, r.reason);
            log(&decision, None, source);
            reply(&mut client, decision.status).await;
            return;
        }
        Err(_) => {
            log(&refused(400, "head_timeout"), None, source);
            reply(&mut client, 400).await;
            return;
        }
    };
    let Ok(_permit) = state.tunnels.clone().try_acquire_owned() else {
        let decision = refused(503, "max_tunnels");
        log(&decision, Some(&request), source);
        reply(&mut client, decision.status).await;
        return;
    };
    metrics::TUNNELS.inc();
    let (mut decision, addrs) = authorize(&request, source, &state).await;
    let upstream = if decision.allowed() {
        let upstream = connect(&addrs, request.port).await;
        if upstream.is_none() {
            decision = Decision {
                status: 502,
                reason: "connect",
                ..decision
            };
        }
        upstream
    } else {
        None
    };
    log(&decision, Some(&request), source);
    reply(&mut client, decision.status).await;
    if let Some(upstream) = upstream {
        tunnel(client, upstream, state.idle).await;
    }
    metrics::TUNNELS.dec();
}

/// Resolve the target once and decide. The addresses are the only
/// ones that the proxy may connect to.
pub async fn authorize<R: Resolve>(
    request: &Request,
    source: IpAddr,
    state: &State<R>,
) -> (Decision, Vec<IpAddr>) {
    let started = Instant::now();
    let mut addrs = timeout(DNS_TIMEOUT, state.resolver.lookup(&request.host))
        .await
        .unwrap_or_default();
    metrics::DNS_SECONDS.observe(started.elapsed().as_secs_f64());
    addrs.truncate(MAX_ADDRESSES);
    let unix_now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs() as i64);
    let pods = state.pods.read().unwrap_or_else(|e| e.into_inner());
    let decision = policy::decide(
        &Connection {
            host: &request.host,
            port: request.port,
            addrs: &addrs,
            proxy_authorization: request.proxy_authorization.as_deref(),
            source,
        },
        &state.internal,
        &state.keys,
        &pods,
        unix_now,
        Instant::now(),
    );
    (decision, addrs)
}

async fn read_head(client: &mut TcpStream) -> Result<Request, Refusal> {
    let mut buf = Vec::with_capacity(1024);
    let mut chunk = [0u8; 1024];
    loop {
        let n = client.read(&mut chunk).await.unwrap_or(0);
        if n == 0 {
            return Err(Refusal {
                status: 400,
                reason: "closed",
            });
        }
        buf.extend_from_slice(&chunk[..n]);
        if let Some(request) = request::parse(&buf)? {
            return Ok(request);
        }
    }
}

/// Connect to the checked addresses in order.
async fn connect(addrs: &[IpAddr], port: u16) -> Option<TcpStream> {
    for ip in addrs {
        let addr = SocketAddr::new(ip.to_canonical(), port);
        if let Ok(Ok(stream)) = timeout(CONNECT_TIMEOUT, TcpStream::connect(addr)).await {
            return Some(stream);
        }
    }
    None
}

fn refused(status: u16, reason: &'static str) -> Decision {
    Decision {
        status,
        reason,
        chain: None,
    }
}

fn log(decision: &Decision, request: Option<&Request>, source: IpAddr) {
    metrics::DECISIONS
        .with_label_values(&[decision.status.to_string().as_str(), decision.reason])
        .inc();
    tracing::info!(
        chain = decision.chain.as_deref(),
        host = request.map(|r| r.host.as_str()),
        port = request.map(|r| r.port),
        result = decision.status,
        reason = decision.reason,
        source = %source,
        "decision"
    );
}

async fn reply(client: &mut TcpStream, status: u16) {
    let head = match status {
        200 => "200 Connection established\r\n",
        400 => "400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n",
        403 => "403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n",
        405 => {
            "405 Method Not Allowed\r\nAllow: CONNECT\r\nConnection: close\r\nContent-Length: 0\r\n"
        }
        407 => {
            "407 Proxy Authentication Required\r\n\
             Proxy-Authenticate: Basic realm=\"imbi-egress-proxy\"\r\n\
             Connection: close\r\nContent-Length: 0\r\n"
        }
        502 => "502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n",
        _ => "503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n",
    };
    let _ = client
        .write_all(format!("HTTP/1.1 {head}\r\n").as_bytes())
        .await;
}

/// Copy bytes in both directions until one side closes or the tunnel
/// is idle for `idle`.
pub async fn tunnel<A, B>(client: A, mut upstream: B, idle: Duration)
where
    A: AsyncRead + AsyncWrite + Unpin,
    B: AsyncRead + AsyncWrite + Unpin,
{
    let start = tokio::time::Instant::now();
    let last = Arc::new(AtomicU64::new(0));
    let mut client = Activity {
        inner: client,
        start,
        last: last.clone(),
    };
    let watchdog = async {
        loop {
            let deadline = start + Duration::from_millis(last.load(Ordering::Relaxed)) + idle;
            if tokio::time::Instant::now() >= deadline {
                return;
            }
            sleep_until(deadline).await;
        }
    };
    tokio::select! {
        result = tokio::io::copy_bidirectional(&mut client, &mut upstream) => {
            if let Ok((up, down)) = result {
                metrics::BYTES.with_label_values(&["upstream"]).inc_by(up);
                metrics::BYTES.with_label_values(&["downstream"]).inc_by(down);
            }
        }
        () = watchdog => {}
    }
}

/// A stream that records the time of its last read or write.
struct Activity<T> {
    inner: T,
    start: tokio::time::Instant,
    last: Arc<AtomicU64>,
}

impl<T> Activity<T> {
    fn touch(&self) {
        let ms = self.start.elapsed().as_millis() as u64;
        self.last.store(ms, Ordering::Relaxed);
    }
}

impl<T: AsyncRead + Unpin> AsyncRead for Activity<T> {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        let before = buf.filled().len();
        let poll = Pin::new(&mut self.inner).poll_read(cx, buf);
        if buf.filled().len() > before {
            self.touch();
        }
        poll
    }
}

impl<T: AsyncWrite + Unpin> AsyncWrite for Activity<T> {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        let poll = Pin::new(&mut self.inner).poll_write(cx, buf);
        if matches!(poll, Poll::Ready(Ok(n)) if n > 0) {
            self.touch();
        }
        poll
    }

    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.inner).poll_flush(cx)
    }

    fn poll_shutdown(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.inner).poll_shutdown(cx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pods::tests::{listed, pod};
    use std::sync::Mutex;
    use tokio::net::TcpListener;

    /// Gives each answer once, in order.
    struct FakeResolver(Mutex<Vec<Vec<IpAddr>>>);

    impl Resolve for FakeResolver {
        async fn lookup(&self, _host: &str) -> Vec<IpAddr> {
            let mut answers = self.0.lock().unwrap();
            if answers.is_empty() {
                Vec::new()
            } else {
                answers.remove(0)
            }
        }
    }

    fn state(answers: Vec<Vec<&str>>, max_tunnels: usize) -> Arc<State<FakeResolver>> {
        let answers = answers
            .into_iter()
            .map(|a| a.iter().map(|ip| ip.parse().unwrap()).collect())
            .collect();
        Arc::new(State {
            resolver: FakeResolver(Mutex::new(answers)),
            keys: Keys::new(b"key", None),
            internal: vec!["10.0.0.0/8".parse().unwrap()],
            pods: Arc::new(RwLock::new(listed(vec![pod("p", "10.9.0.5", "Running")]))),
            idle: Duration::from_secs(600),
            tunnels: Arc::new(Semaphore::new(max_tunnels)),
        })
    }

    /// Send `data` to a proxy that serves one connection, and give the
    /// reply.
    async fn exchange(state: Arc<State<FakeResolver>>, data: &[u8]) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (stream, peer) = listener.accept().await.unwrap();
            serve(stream, peer.ip(), state).await;
        });
        let mut client = TcpStream::connect(addr).await.unwrap();
        client.write_all(data).await.unwrap();
        let mut out = String::new();
        client.read_to_string(&mut out).await.unwrap();
        server.await.unwrap();
        out
    }

    #[tokio::test]
    async fn refusals_reach_the_client() {
        let cases: [(&[u8], &str); 4] = [
            (b"GET / HTTP/1.1\r\n\r\n", "HTTP/1.1 405 "),
            (
                b"CONNECT a.example.com:443 HTTP/1.1\r\n\r\n\x16\x03\x01",
                "HTTP/1.1 400 ",
            ),
            (
                b"CONNECT a.example.com:443 HTTP/1.1\r\n\r\n",
                "HTTP/1.1 407 ",
            ),
            (
                b"CONNECT b.example.com:443 HTTP/1.1\r\n\r\n",
                "HTTP/1.1 403 ",
            ),
        ];
        for (data, expected) in cases {
            let state = state(vec![vec!["10.1.2.3"]], 4);
            if data.starts_with(b"CONNECT b.") {
                // A loopback answer is never allowed.
                *state.resolver.0.lock().unwrap() = vec![vec!["127.0.0.1".parse().unwrap()]];
            }
            let reply = exchange(state, data).await;
            assert!(reply.starts_with(expected), "{reply:?}");
        }
    }

    #[tokio::test]
    async fn tunnel_limit_is_503() {
        let reply = exchange(
            state(vec![], 0),
            b"CONNECT a.example.com:443 HTTP/1.1\r\n\r\n",
        )
        .await;
        assert!(reply.starts_with("HTTP/1.1 503 "), "{reply:?}");
    }

    #[tokio::test]
    async fn only_the_checked_addresses_are_used() {
        let state = state(vec![vec!["93.184.215.14"], vec!["10.1.2.3"]], 1);
        let request = request::parse(b"CONNECT a.example.com:443 HTTP/1.1\r\n\r\n")
            .unwrap()
            .unwrap();
        let (decision, addrs) = authorize(&request, "10.9.0.5".parse().unwrap(), &state).await;
        assert_eq!(decision.status, 200);
        assert_eq!(addrs, vec!["93.184.215.14".parse::<IpAddr>().unwrap()]);
        // The second answer is still there: one lookup only.
        assert_eq!(state.resolver.0.lock().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn tunnel_copies_both_ways() {
        let (client, mut client_end) = tokio::io::duplex(64);
        let (upstream, mut upstream_end) = tokio::io::duplex(64);
        let task = tokio::spawn(tunnel(client, upstream, Duration::from_secs(5)));
        client_end.write_all(b"ping").await.unwrap();
        let mut buf = [0u8; 4];
        upstream_end.read_exact(&mut buf).await.unwrap();
        assert_eq!(&buf, b"ping");
        upstream_end.write_all(b"pong").await.unwrap();
        client_end.read_exact(&mut buf).await.unwrap();
        assert_eq!(&buf, b"pong");
        drop(client_end);
        drop(upstream_end);
        task.await.unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn idle_tunnel_closes() {
        let (client, _client_end) = tokio::io::duplex(64);
        let (upstream, _upstream_end) = tokio::io::duplex(64);
        timeout(
            Duration::from_secs(11),
            tunnel(client, upstream, Duration::from_secs(10)),
        )
        .await
        .expect("the idle tunnel closes");
    }
}
