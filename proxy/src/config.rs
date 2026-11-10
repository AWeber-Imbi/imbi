//! Configuration from environment variables (plan 12.3, K2).

use std::str::FromStr;
use std::time::Duration;

use ipnet::IpNet;

#[derive(Debug)]
pub struct Config {
    pub port: u16,
    pub admin_port: u16,
    pub namespace: String,
    pub internal_ranges: Vec<IpNet>,
    pub secret: String,
    pub previous_secret: Option<String>,
    pub max_tunnels: usize,
    pub idle: Duration,
    pub log: String,
}

impl Config {
    /// Read the configuration. `var` gives the value of a variable.
    /// A bad or missing value is an error.
    pub fn load(var: impl Fn(&str) -> Option<String>) -> Result<Self, String> {
        let required = |name: &str| {
            var(name)
                .filter(|v| !v.trim().is_empty())
                .ok_or(format!("{name} is required"))
        };
        let number = |name: &str, default: u64| -> Result<u64, String> {
            match var(name) {
                None => Ok(default),
                Some(v) => u64::from_str(v.trim())
                    .ok()
                    .filter(|n| *n > 0)
                    .ok_or(format!("{name} must be a positive integer, not {v:?}")),
            }
        };
        let port = |name: &str, default: u16| -> Result<u16, String> {
            u16::try_from(number(name, default.into())?)
                .map_err(|_| format!("{name} must be a port number"))
        };
        let internal_ranges = required("IMBI_EGRESS_PROXY_INTERNAL_RANGES")?
            .split(',')
            .map(|r| {
                IpNet::from_str(r.trim())
                    .map_err(|_| format!("bad CIDR in IMBI_EGRESS_PROXY_INTERNAL_RANGES: {r:?}"))
            })
            .collect::<Result<_, _>>()?;
        Ok(Config {
            port: port("IMBI_EGRESS_PROXY_PORT", 3128)?,
            admin_port: port("IMBI_EGRESS_PROXY_ADMIN_PORT", 9090)?,
            namespace: required("IMBI_EGRESS_PROXY_NAMESPACE")?,
            internal_ranges,
            secret: required("IMBI_HARNESS_EGRESS_PROXY_SECRET")?,
            previous_secret: var("IMBI_HARNESS_EGRESS_PROXY_SECRET_PREVIOUS")
                .filter(|v| !v.is_empty()),
            max_tunnels: number("IMBI_EGRESS_PROXY_MAX_TUNNELS", 512)? as usize,
            idle: Duration::from_secs(number("IMBI_EGRESS_PROXY_IDLE_SECONDS", 600)?),
            log: var("IMBI_EGRESS_PROXY_LOG").unwrap_or_else(|| "info".into()),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn load(pairs: &[(&str, &str)]) -> Result<Config, String> {
        let mut env: HashMap<String, String> = [
            ("IMBI_EGRESS_PROXY_NAMESPACE", "imbi-runners"),
            ("IMBI_EGRESS_PROXY_INTERNAL_RANGES", "10.0.0.0/8, fd00::/8"),
            ("IMBI_HARNESS_EGRESS_PROXY_SECRET", "key"),
        ]
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        for (k, v) in pairs {
            env.insert(k.to_string(), v.to_string());
        }
        Config::load(|name| env.get(name).cloned())
    }

    #[test]
    fn defaults() {
        let config = load(&[]).unwrap();
        assert_eq!(
            (config.port, config.admin_port, config.max_tunnels),
            (3128, 9090, 512)
        );
        assert_eq!(config.idle, Duration::from_secs(600));
        assert_eq!(config.internal_ranges.len(), 2);
    }

    #[test]
    fn bad_values_fail() {
        for pair in [
            ("IMBI_EGRESS_PROXY_PORT", "70000"),
            ("IMBI_EGRESS_PROXY_PORT", "0"),
            ("IMBI_EGRESS_PROXY_MAX_TUNNELS", "many"),
            ("IMBI_EGRESS_PROXY_INTERNAL_RANGES", "10.0.0.0/8,nope"),
            ("IMBI_EGRESS_PROXY_INTERNAL_RANGES", ""),
            ("IMBI_HARNESS_EGRESS_PROXY_SECRET", ""),
        ] {
            assert!(load(&[pair]).is_err(), "{pair:?}");
        }
    }
}
