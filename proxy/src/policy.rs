//! The decision for a `CONNECT` target: address classes, the proxy
//! token, and the rule of section 5.4 of the plan.

use std::net::IpAddr;
use std::sync::LazyLock;
use std::time::Instant;

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use ipnet::IpNet;
use jsonwebtoken::{Algorithm, DecodingKey, Validation};
use serde::Deserialize;

use crate::pods::PodMap;

/// The ranges of the IANA IPv4 and IPv6 special-purpose address
/// registries, plus multicast. An address in one of them is not
/// public. `Ipv4Addr::is_global` is not stable, so the proxy holds
/// the table.
static SPECIAL: LazyLock<Vec<IpNet>> = LazyLock::new(|| {
    [
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.31.196.0/24",
        "192.52.193.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "192.175.48.0/24",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "::/128",
        "::1/128",
        "::ffff:0:0/96",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "100::/64",
        "100:0:0:1::/64",
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
        "2620:4f:8000::/48",
        "3fff::/20",
        "5f00::/16",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    ]
    .iter()
    .map(|net| net.parse().expect("valid special range"))
    .collect()
});

/// The global unicast IPv6 range. Every other IPv6 address is not
/// public.
static GLOBAL_V6: LazyLock<IpNet> = LazyLock::new(|| "2000::/3".parse().expect("valid range"));

/// Ranges that are always refused, also when an internal range holds
/// them: this, loopback, link-local and IMDS, multicast, broadcast.
static NEVER: LazyLock<Vec<IpNet>> = LazyLock::new(|| {
    [
        "0.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "224.0.0.0/4",
        "255.255.255.255/32",
        "::/128",
        "::1/128",
        "fe80::/10",
        "ff00::/8",
        "fd00:ec2::/32",
    ]
    .iter()
    .map(|net| net.parse().expect("valid never range"))
    .collect()
});

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Class {
    Public,
    Internal,
    /// Neither public nor internal: loopback, link-local and IMDS,
    /// multicast, CGNAT, documentation, reserved, and the rest.
    Refused,
}

pub fn classify(ip: IpAddr, internal: &[IpNet]) -> Class {
    let ip = ip.to_canonical();
    if NEVER.iter().any(|net| net.contains(&ip)) {
        return Class::Refused;
    }
    if internal.iter().any(|net| net.contains(&ip)) {
        return Class::Internal;
    }
    let special = SPECIAL.iter().any(|net| net.contains(&ip));
    let global = match ip {
        IpAddr::V4(_) => true,
        IpAddr::V6(_) => GLOBAL_V6.contains(&ip),
    };
    if global && !special {
        Class::Public
    } else {
        Class::Refused
    }
}

/// The claims of a proxy token. Every claim is required and typed.
#[derive(Debug, Deserialize)]
pub struct Claims {
    pub iss: String,
    pub aud: String,
    pub iat: i64,
    pub exp: i64,
    pub chain: String,
    pub attempt: i64,
    pub pod: String,
    pub hosts: Vec<String>,
    pub cidrs: Vec<Cidr>,
}

/// A CIDR grant: the internal addresses in `net`, on the TCP `ports`.
#[derive(Debug, Deserialize)]
pub struct Cidr {
    pub net: IpNet,
    pub ports: Vec<u16>,
}

/// The leeway on `exp`, in seconds.
pub const LEEWAY: i64 = 30;

/// The HS256 keys that verify a proxy token.
pub struct Keys {
    keys: Vec<DecodingKey>,
    validation: Validation,
}

impl Keys {
    pub fn new(current: &[u8], previous: Option<&[u8]>) -> Self {
        let mut validation = Validation::new(Algorithm::HS256);
        validation.set_issuer(&["imbi-api"]);
        validation.set_audience(&["imbi-egress-proxy"]);
        validation.set_required_spec_claims(&["exp", "iss", "aud"]);
        // `exp` is checked against the clock of the caller, below.
        validation.validate_exp = false;
        let keys = std::iter::once(current)
            .chain(previous)
            .map(DecodingKey::from_secret)
            .collect();
        Keys { keys, validation }
    }

    /// The claims of a valid token at `now` (seconds since the epoch).
    pub fn verify(&self, token: &str, now: i64) -> Option<Claims> {
        let claims = self.keys.iter().find_map(|key| {
            jsonwebtoken::decode::<Claims>(token, key, &self.validation)
                .ok()
                .map(|data| data.claims)
        })?;
        let valid = claims.exp.saturating_add(LEEWAY) >= now
            && !claims.chain.is_empty()
            && !claims.pod.is_empty()
            && (!claims.hosts.is_empty() || !claims.cidrs.is_empty())
            && claims
                .cidrs
                .iter()
                .all(|c| !c.ports.is_empty() && !c.ports.contains(&0));
        valid.then_some(claims)
    }
}

/// The JWT in a `Proxy-Authorization: Basic` value with the user
/// `chain`.
pub fn basic_password(value: &str) -> Option<String> {
    let (scheme, credentials) = value.trim().split_once(' ')?;
    if !scheme.eq_ignore_ascii_case("basic") {
        return None;
    }
    let decoded = String::from_utf8(STANDARD.decode(credentials.trim()).ok()?).ok()?;
    let (user, password) = decoded.split_once(':')?;
    (user == "chain").then(|| password.to_owned())
}

/// The result of a decision: the reply status, the log reason, and the
/// chain of the token when it is known.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Decision {
    pub status: u16,
    pub reason: &'static str,
    pub chain: Option<String>,
}

impl Decision {
    fn new(status: u16, reason: &'static str) -> Self {
        Decision {
            status,
            reason,
            chain: None,
        }
    }

    pub fn allowed(&self) -> bool {
        self.status == 200
    }
}

/// What the proxy knows about one connection.
pub struct Connection<'a> {
    pub host: &'a str,
    pub port: u16,
    pub addrs: &'a [IpAddr],
    pub proxy_authorization: Option<&'a str>,
    pub source: IpAddr,
}

/// Decide on a connection (plan 5.4, steps 2 and 3).
pub fn decide(
    conn: &Connection,
    internal: &[IpNet],
    keys: &Keys,
    pods: &PodMap,
    unix_now: i64,
    now: Instant,
) -> Decision {
    if conn.addrs.is_empty() {
        return Decision::new(502, "dns");
    }
    let classes: Vec<Class> = conn
        .addrs
        .iter()
        .map(|ip| classify(*ip, internal))
        .collect();
    if classes.iter().all(|c| *c == Class::Public) {
        return Decision::new(200, "public");
    }
    if classes.contains(&Class::Refused) {
        return Decision::new(403, "special_address");
    }
    let Some(token) = conn.proxy_authorization.and_then(basic_password) else {
        return Decision::new(407, "no_token");
    };
    let Some(claims) = keys.verify(&token, unix_now) else {
        return Decision::new(407, "bad_token");
    };
    let source = conn.source.to_canonical();
    let held = claims.hosts.iter().any(|h| h == conn.host);
    // Every internal address must be in a grant that holds the port.
    // A public address of a mixed answer needs no grant.
    let granted = conn.addrs.iter().zip(&classes).all(|(ip, class)| {
        let ip = ip.to_canonical();
        *class != Class::Internal
            || claims
                .cidrs
                .iter()
                .any(|c| c.net.contains(&ip) && c.ports.contains(&conn.port))
    });
    let decision = match pods.addresses(&claims.pod, now) {
        None => Decision::new(407, "pod_unknown"),
        Some(ips) if !ips.contains(&source) => Decision::new(407, "pod_address"),
        Some(_) if held && conn.port == 443 => Decision::new(200, "held"),
        Some(_) if granted => Decision::new(200, "cidr"),
        Some(_) if held => Decision::new(403, "port"),
        Some(_) => Decision::new(403, "not_held"),
    };
    Decision {
        chain: Some(claims.chain),
        ..decision
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pods::tests::{listed, pod};
    use jsonwebtoken::{EncodingKey, Header, encode};
    use serde_json::{Value, json};

    const KEY: &[u8] = b"current-key";
    const OLD_KEY: &[u8] = b"previous-key";
    const POD: &str = "6c1e2f0a-8b7d-4e3c-a5f4-2d9b1c0e7a66";
    const NOW: i64 = 1_800_000_000;

    fn internal() -> Vec<IpNet> {
        vec!["10.0.0.0/8".parse().unwrap(), "fd10::/16".parse().unwrap()]
    }

    fn claims() -> Value {
        json!({
            "iss": "imbi-api", "aud": "imbi-egress-proxy", "iat": NOW,
            "exp": NOW + 3600, "chain": "chain-1", "attempt": 1, "pod": POD,
            "hosts": ["git.example.com"], "cidrs": [],
        })
    }

    fn sign(alg: Algorithm, key: &[u8], claims: &Value) -> String {
        encode(&Header::new(alg), claims, &EncodingKey::from_secret(key)).unwrap()
    }

    fn basic(user: &str, token: &str) -> String {
        format!("Basic {}", STANDARD.encode(format!("{user}:{token}")))
    }

    struct Case {
        host: &'static str,
        port: u16,
        addrs: Vec<&'static str>,
        auth: Option<String>,
        source: &'static str,
        pods: PodMap,
    }

    impl Case {
        fn new(host: &'static str, addrs: &[&'static str]) -> Self {
            Case {
                host,
                port: 443,
                addrs: addrs.to_vec(),
                auth: Some(basic("chain", &sign(Algorithm::HS256, KEY, &claims()))),
                source: "10.9.0.5",
                pods: listed(vec![pod(POD, "10.9.0.5", "Running")]),
            }
        }

        fn decide(&self) -> Decision {
            let addrs: Vec<IpAddr> = self.addrs.iter().map(|a| a.parse().unwrap()).collect();
            let conn = Connection {
                host: self.host,
                port: self.port,
                addrs: &addrs,
                proxy_authorization: self.auth.as_deref(),
                source: self.source.parse().unwrap(),
            };
            let keys = Keys::new(KEY, Some(OLD_KEY));
            decide(&conn, &internal(), &keys, &self.pods, NOW, Instant::now())
        }

        fn with_claims(mut self, f: impl FnOnce(&mut Value)) -> Self {
            let mut c = claims();
            f(&mut c);
            self.auth = Some(basic("chain", &sign(Algorithm::HS256, KEY, &c)));
            self
        }
    }

    fn reason(case: Case) -> (u16, &'static str) {
        let d = case.decide();
        (d.status, d.reason)
    }

    #[test]
    fn held_host_on_443_to_internal_address_is_allowed() {
        let d = Case::new("git.example.com", &["10.1.2.3", "fd10::5"]).decide();
        assert_eq!((d.status, d.reason), (200, "held"));
        assert_eq!(d.chain.as_deref(), Some("chain-1"));
    }

    #[test]
    fn held_host_on_8443_is_403() {
        let mut case = Case::new("git.example.com", &["10.1.2.3"]);
        case.port = 8443;
        assert_eq!(reason(case), (403, "port"));
    }

    #[test]
    fn host_not_held_to_internal_address_is_403() {
        assert_eq!(
            reason(Case::new("other.example.com", &["10.1.2.3"])),
            (403, "not_held")
        );
    }

    #[test]
    fn host_not_held_with_global_addresses_is_allowed_without_token() {
        let mut case = Case::new(
            "www.example.org",
            &["93.184.215.14", "2606:2800:21f:cb07::1"],
        );
        case.auth = None;
        case.pods = PodMap::default();
        assert_eq!(reason(case), (200, "public"));
    }

    #[test]
    fn global_and_internal_addresses_mixed_need_the_name() {
        assert_eq!(
            reason(Case::new(
                "other.example.com",
                &["93.184.215.14", "fd10::5"]
            )),
            (403, "not_held")
        );
        assert_eq!(
            reason(Case::new(
                "other.example.com",
                &["2606:2800:21f:cb07::1", "10.1.2.3"]
            )),
            (403, "not_held")
        );
    }

    #[test]
    fn held_host_to_a_refused_class_is_403() {
        for addr in [
            "127.0.0.1",
            "::1",
            "169.254.1.1",
            "fe80::1",
            "169.254.169.254",
            "fd00:ec2::254",
            "224.0.0.1",
            "ff02::1",
            "100.64.0.1",
            "192.0.2.1",
            "198.51.100.1",
            "203.0.113.1",
            "2001:db8::1",
            "240.0.0.1",
            "255.255.255.255",
            "0.0.0.0",
            "::",
            "172.16.0.1",
            "::ffff:127.0.0.1",
            "4000::1",
        ] {
            let case = Case::new("git.example.com", &["10.1.2.3", addr]);
            assert_eq!(reason(case), (403, "special_address"), "{addr}");
        }
    }

    #[test]
    fn never_ranges_win_over_internal_ranges() {
        let internal: Vec<IpNet> = ["169.254.0.0/16", "127.0.0.0/8", "fd00::/8", "100.64.0.0/10"]
            .iter()
            .map(|n| n.parse().unwrap())
            .collect();
        for ip in ["169.254.169.254", "127.0.0.1", "fd00:ec2::254"] {
            assert_eq!(
                classify(ip.parse().unwrap(), &internal),
                Class::Refused,
                "{ip}"
            );
        }
        // CGNAT is a valid internal range.
        assert_eq!(
            classify("100.64.1.2".parse().unwrap(), &internal),
            Class::Internal
        );
    }

    #[test]
    fn mapped_internal_address_is_internal() {
        assert_eq!(
            classify("::ffff:10.1.2.3".parse().unwrap(), &internal()),
            Class::Internal
        );
    }

    #[test]
    fn token_problems_are_407() {
        let token = sign(Algorithm::HS256, KEY, &claims());
        let cases: Vec<(Option<String>, &str)> = vec![
            (None, "no_token"),
            (Some("Basic !!!".into()), "no_token"),
            (Some(format!("Bearer {token}")), "no_token"),
            (Some(basic("user", &token)), "no_token"),
            (
                Some(basic("chain", &sign(Algorithm::HS256, b"other", &claims()))),
                "bad_token",
            ),
            (
                Some(basic("chain", &sign(Algorithm::HS384, KEY, &claims()))),
                "bad_token",
            ),
        ];
        for (auth, expected) in cases {
            let mut case = Case::new("git.example.com", &["10.1.2.3"]);
            case.auth = auth.clone();
            assert_eq!(reason(case), (407, expected), "{auth:?}");
        }
    }

    #[test]
    fn bad_claims_are_407() {
        for (claim, value) in [
            ("iss", json!("someone")),
            ("aud", json!("imbi-harness")),
            ("exp", json!(NOW - LEEWAY - 1)),
            ("attempt", json!("1")),
            ("pod", json!("")),
            ("hosts", json!([])),
            ("cidrs", json!([{"net": "10.0.0.0/33", "ports": [443]}])),
            ("cidrs", json!([{"net": "10.0.0.0/8", "ports": []}])),
            ("cidrs", json!([{"net": "10.0.0.0/8", "ports": [0]}])),
            ("cidrs", json!([{"net": "10.0.0.0/8", "ports": [65536]}])),
            ("cidrs", json!([{"net": "10.0.0.0/8"}])),
        ] {
            let case = Case::new("git.example.com", &["10.1.2.3"])
                .with_claims(|c| c[claim] = value.clone());
            assert_eq!(reason(case), (407, "bad_token"), "{claim}");
        }
        for claim in [
            "iss", "aud", "iat", "exp", "chain", "attempt", "pod", "hosts", "cidrs",
        ] {
            let case = Case::new("git.example.com", &["10.1.2.3"])
                .with_claims(|c| _ = c.as_object_mut().unwrap().remove(claim));
            assert_eq!(reason(case), (407, "bad_token"), "{claim}");
        }
    }

    #[test]
    fn exp_has_30_seconds_of_leeway_and_iat_may_be_in_the_future() {
        let case = Case::new("git.example.com", &["10.1.2.3"]).with_claims(|c| {
            c["exp"] = json!(NOW - LEEWAY);
            c["iat"] = json!(NOW + 86_400);
        });
        assert_eq!(reason(case), (200, "held"));
    }

    #[test]
    fn pod_problems_are_407() {
        let mut case = Case::new("git.example.com", &["10.1.2.3"]);
        case.pods = listed(vec![]);
        assert_eq!(reason(case), (407, "pod_unknown"));

        let mut case = Case::new("git.example.com", &["10.1.2.3"]);
        case.source = "10.9.0.6";
        assert_eq!(reason(case), (407, "pod_address"));

        let mut case = Case::new("git.example.com", &["10.1.2.3"]);
        let mut terminating = pod(POD, "10.9.0.5", "Running");
        terminating.metadata.deletion_timestamp = Some(
            k8s_openapi::apimachinery::pkg::apis::meta::v1::Time(Default::default()),
        );
        case.pods
            .apply(kube::runtime::watcher::Event::Apply(terminating));
        assert_eq!(reason(case), (407, "pod_unknown"));
    }

    #[test]
    fn mapped_source_address_matches_the_pod() {
        let mut case = Case::new("git.example.com", &["10.1.2.3"]);
        case.source = "::ffff:10.9.0.5";
        assert_eq!(reason(case), (200, "held"));
    }

    #[test]
    fn token_of_the_previous_key_is_allowed() {
        let mut case = Case::new("git.example.com", &["10.1.2.3"]);
        case.auth = Some(basic("chain", &sign(Algorithm::HS256, OLD_KEY, &claims())));
        assert_eq!(reason(case), (200, "held"));
    }

    fn cidr_case(addrs: &[&'static str], port: u16) -> Case {
        let mut case = Case::new("db.example.com", addrs).with_claims(|c| {
            c["hosts"] = json!([]);
            c["cidrs"] = json!([
                {"net": "10.1.0.0/16", "ports": [5432, 443]},
                {"net": "169.254.0.0/16", "ports": [80]},
            ]);
        });
        case.port = port;
        case
    }

    #[test]
    fn cidr_grant_on_a_granted_port_is_allowed() {
        let d = cidr_case(&["10.1.2.3"], 5432).decide();
        assert_eq!((d.status, d.reason), (200, "cidr"));
        assert_eq!(d.chain.as_deref(), Some("chain-1"));
    }

    #[test]
    fn cidr_grant_on_a_port_not_granted_is_403() {
        assert_eq!(reason(cidr_case(&["10.1.2.3"], 22)), (403, "not_held"));
    }

    #[test]
    fn address_outside_every_grant_is_403() {
        assert_eq!(reason(cidr_case(&["10.2.0.1"], 5432)), (403, "not_held"));
    }

    #[test]
    fn mixed_answer_with_one_address_outside_the_grant_is_403() {
        assert_eq!(
            reason(cidr_case(&["10.1.2.3", "10.2.0.1"], 5432)),
            (403, "not_held")
        );
    }

    #[test]
    fn never_list_wins_over_a_cidr_grant() {
        assert_eq!(
            reason(cidr_case(&["169.254.169.254"], 80)),
            (403, "special_address")
        );
    }

    #[test]
    fn held_host_on_443_with_cidrs_in_the_token_is_allowed() {
        let case = Case::new("git.example.com", &["10.9.9.9"])
            .with_claims(|c| c["cidrs"] = json!([{"net": "10.1.0.0/16", "ports": [22]}]));
        assert_eq!(reason(case), (200, "held"));
    }

    #[test]
    fn no_address_is_502() {
        assert_eq!(reason(Case::new("git.example.com", &[])), (502, "dns"));
    }
}
