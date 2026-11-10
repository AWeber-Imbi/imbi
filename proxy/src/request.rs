//! Parse the `CONNECT` request and its target.

use std::collections::HashSet;

/// The largest request head that the proxy reads.
pub const MAX_HEAD_BYTES: usize = 8 * 1024;

/// A request that the proxy can decide on.
#[derive(Debug, PartialEq, Eq)]
pub struct Request {
    /// The target host name, in the canonical form.
    pub host: String,
    pub port: u16,
    pub proxy_authorization: Option<String>,
}

/// The reply status and the log reason for a refused request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Refusal {
    pub status: u16,
    pub reason: &'static str,
}

fn bad(reason: &'static str) -> Refusal {
    Refusal {
        status: 400,
        reason,
    }
}

/// Parse the bytes read so far. `Ok(None)` means: read more.
///
/// The buffer must hold the request head and nothing after it, because
/// the client must not send bytes before the proxy replies.
pub fn parse(buf: &[u8]) -> Result<Option<Request>, Refusal> {
    let mut headers = [httparse::EMPTY_HEADER; 32];
    let mut req = httparse::Request::new(&mut headers);
    let end = match req.parse(buf) {
        Ok(httparse::Status::Complete(end)) => end,
        Ok(httparse::Status::Partial) if buf.len() < MAX_HEAD_BYTES => return Ok(None),
        Ok(httparse::Status::Partial) => return Err(bad("head_too_large")),
        Err(_) => return Err(bad("malformed")),
    };
    if end > MAX_HEAD_BYTES {
        return Err(bad("head_too_large"));
    }
    if req.method != Some("CONNECT") {
        return Err(Refusal {
            status: 405,
            reason: "method",
        });
    }
    if req.version != Some(1) {
        return Err(bad("version"));
    }
    if end != buf.len() {
        return Err(bad("early_data"));
    }
    let (host, port) = canonical_target(req.path.unwrap_or_default()).ok_or(bad("target"))?;
    let mut seen = HashSet::new();
    let mut proxy_authorization = None;
    for header in req.headers.iter() {
        let name = header.name.to_ascii_lowercase();
        if name == "content-length" || name == "transfer-encoding" {
            return Err(bad("body"));
        }
        if name == "proxy-authorization" {
            proxy_authorization = Some(String::from_utf8_lossy(header.value).into_owned());
        }
        if !seen.insert(name) {
            return Err(bad("repeated_header"));
        }
    }
    Ok(Some(Request {
        host,
        port,
        proxy_authorization,
    }))
}

/// Make the canonical form of a `name:port` target in authority form.
///
/// The host name gets IDNA A-labels, lower case, and no trailing dot.
/// It must have at least one dot. An IP literal, userinfo, a wildcard,
/// or a path gives `None`. The port is decimal, from 1 to 65535.
pub fn canonical_target(target: &str) -> Option<(String, u16)> {
    let (name, port) = target.rsplit_once(':')?;
    if port.is_empty() || !port.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let port = port.parse::<u16>().ok().filter(|p| *p != 0)?;
    if name.contains(['/', '@', ':', '[', ']', '*']) {
        return None;
    }
    let name = name.strip_suffix('.').unwrap_or(name);
    let host = idna::domain_to_ascii(name).ok()?;
    let labels: Vec<&str> = host.split('.').collect();
    let valid = host.len() <= 253
        && labels.len() >= 2
        && labels.iter().all(|label| {
            !label.is_empty()
                && label.len() <= 63
                && label.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        })
        // The last label must start with a letter. This refuses every
        // numeric and hex IPv4 form (`10.1.2.3`, `0x0a.1`), as the API does.
        && labels.last()?.starts_with(|c: char| c.is_ascii_alphabetic());
    valid.then_some((host, port))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn refusal(head: &str) -> Refusal {
        parse(head.as_bytes()).unwrap_err()
    }

    #[test]
    fn connect_is_parsed() {
        let req = parse(
            b"CONNECT Git.Example.com:443 HTTP/1.1\r\nHost: git.example.com:443\r\n\
              Proxy-Authorization: Basic abc\r\n\r\n",
        )
        .unwrap()
        .unwrap();
        assert_eq!(req.host, "git.example.com");
        assert_eq!(req.port, 443);
        assert_eq!(req.proxy_authorization.as_deref(), Some("Basic abc"));
    }

    #[test]
    fn partial_head_asks_for_more() {
        assert_eq!(parse(b"CONNECT git.example.com:443 HT"), Ok(None));
        assert_eq!(parse(b"CONNECT git.example.com:443 HTTP/1.1\r\n"), Ok(None));
    }

    #[test]
    fn not_connect_is_405() {
        assert_eq!(
            refusal("GET http://a.example.com/ HTTP/1.1\r\n\r\n").status,
            405
        );
    }

    #[test]
    fn http_1_0_is_400() {
        assert_eq!(
            refusal("CONNECT a.example.com:443 HTTP/1.0\r\n\r\n").reason,
            "version"
        );
    }

    #[test]
    fn bad_targets_are_400() {
        for target in [
            "user@git.example.com:443",
            "10.1.2.3:443",
            "[::1]:443",
            "git.example.com:0",
            "git.example.com:65536",
            "git.example.com:+443",
        ] {
            let head = format!("CONNECT {target} HTTP/1.1\r\n\r\n");
            assert_eq!(refusal(&head), bad("target"), "{target}");
        }
    }

    #[test]
    fn ipv4_forms_are_not_host_names() {
        for target in [
            "10.1.2.3:443",
            "0x0a.1:443",
            "2130706433:443",
            "a.0x7f:443",
            "a.1b:443",
        ] {
            assert_eq!(canonical_target(target), None, "{target}");
        }
        assert!(canonical_target("a.b1:443").is_some());
    }

    #[test]
    fn repeated_header_is_400() {
        let head = "CONNECT a.example.com:443 HTTP/1.1\r\nHost: a\r\nhost: b\r\n\r\n";
        assert_eq!(refusal(head).reason, "repeated_header");
    }

    #[test]
    fn body_headers_are_400() {
        for header in ["Content-Length: 0", "Transfer-Encoding: chunked"] {
            let head = format!("CONNECT a.example.com:443 HTTP/1.1\r\n{header}\r\n\r\n");
            assert_eq!(refusal(&head).reason, "body");
        }
    }

    #[test]
    fn bytes_after_the_head_are_400() {
        let head = "CONNECT a.example.com:443 HTTP/1.1\r\n\r\n\x16\x03\x01\x02\x00";
        assert_eq!(refusal(head).reason, "early_data");
    }

    #[test]
    fn large_head_is_400() {
        let head = format!(
            "CONNECT a.example.com:443 HTTP/1.1\r\nX: {}",
            "a".repeat(9000)
        );
        assert_eq!(refusal(&head).reason, "head_too_large");
    }

    #[test]
    fn too_many_headers_is_400() {
        let headers: String = (0..40).map(|i| format!("X-{i}: 1\r\n")).collect();
        let head = format!("CONNECT a.example.com:443 HTTP/1.1\r\n{headers}\r\n");
        assert_eq!(refusal(&head).reason, "malformed");
    }
}
