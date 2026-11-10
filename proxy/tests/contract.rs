//! The C4 contract tests: the proxy side of `tests/contract.json`.
//! The imbi-api tests read the same file.

use imbi_egress_proxy::policy::Keys;
use imbi_egress_proxy::request::canonical_target;
use serde_json::Value;

fn fixture() -> Value {
    let text = include_str!("contract.json");
    serde_json::from_str(text).expect("valid fixture")
}

#[test]
fn tokens() {
    let fixture = fixture();
    let key = |name: &str| fixture["keys"][name].as_str().unwrap().as_bytes();
    let keys = Keys::new(key("current"), Some(key("previous")));
    let tokens = fixture["tokens"].as_array().unwrap();
    assert!(!tokens.is_empty());
    for case in tokens {
        let name = case["name"].as_str().unwrap();
        // One hour after `iat`: the "valid" tokens are not expired, and
        // the "expired" token is past its leeway.
        let now = case["claims"]["iat"].as_i64().unwrap() + 3600;
        let claims = keys.verify(case["token"].as_str().unwrap(), now);
        match case["expect"].as_str().unwrap() {
            "ok" => {
                let claims = claims.unwrap_or_else(|| panic!("{name}: refused"));
                let expected = &case["claims"];
                assert_eq!(claims.chain, expected["chain"].as_str().unwrap(), "{name}");
                assert_eq!(claims.pod, expected["pod"].as_str().unwrap(), "{name}");
                assert_eq!(
                    claims.attempt,
                    expected["attempt"].as_i64().unwrap(),
                    "{name}"
                );
                let hosts: Vec<&str> = expected["hosts"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|h| h.as_str().unwrap())
                    .collect();
                assert_eq!(claims.hosts, hosts, "{name}");
                let cidrs: Vec<(Vec<String>, Vec<u16>)> = claims
                    .cidrs
                    .iter()
                    .map(|c| {
                        let nets = c.nets.iter().map(ToString::to_string).collect();
                        (nets, c.ports.clone())
                    })
                    .collect();
                let expected: Vec<(Vec<String>, Vec<u16>)> = expected["cidrs"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|c| {
                        let nets = serde_json::from_value(c["nets"].clone()).unwrap();
                        let ports = serde_json::from_value(c["ports"].clone()).unwrap();
                        (nets, ports)
                    })
                    .collect();
                assert_eq!(cidrs, expected, "{name}");
            }
            "invalid" => assert!(claims.is_none(), "{name}: accepted"),
            other => panic!("{name}: unknown expect {other}"),
        }
    }
}

#[test]
fn targets() {
    let fixture = fixture();
    let targets = fixture["targets"].as_array().unwrap();
    assert!(!targets.is_empty());
    for case in targets {
        let target = case["target"].as_str().unwrap();
        let result = canonical_target(target);
        match case["expect"].as_str().unwrap() {
            "ok" => {
                let host = case["host"].as_str().unwrap().to_owned();
                let port = case["port"].as_u64().unwrap() as u16;
                assert_eq!(result, Some((host, port)), "{target}");
            }
            "invalid" => assert_eq!(result, None, "{target}"),
            other => panic!("{target}: unknown expect {other}"),
        }
    }
}
