//! The map from runner pod uid to pod addresses, from a pod watch.

use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

use futures::StreamExt;
use k8s_openapi::api::core::v1::Pod;
use kube::runtime::WatchStreamExt;
use kube::runtime::watcher::{self, Event};
use kube::{Api, Client};

use crate::metrics;

/// The label selector of the runner pods.
pub const SELECTOR: &str = "app.kubernetes.io/name=imbi-harness";

/// After the watch is in error for this time, the map is empty.
pub const WATCH_GRACE: Duration = Duration::from_secs(30);

/// The live runner pods. It is empty until the first full list, and
/// while the watch is in error for [`WATCH_GRACE`] or more.
#[derive(Debug, Default)]
pub struct PodMap {
    ready: bool,
    pods: HashMap<String, Vec<IpAddr>>,
    // The pods of a list that is not complete.
    next: Option<HashMap<String, Vec<IpAddr>>>,
    error_since: Option<Instant>,
}

impl PodMap {
    /// The addresses of a live pod.
    pub fn addresses(&self, uid: &str, now: Instant) -> Option<&[IpAddr]> {
        let failed = self
            .error_since
            .is_some_and(|since| now.saturating_duration_since(since) >= WATCH_GRACE);
        if !self.ready || failed {
            return None;
        }
        self.pods.get(uid).map(Vec::as_slice)
    }

    /// True after the first full list.
    pub fn is_ready(&self) -> bool {
        self.ready
    }

    pub fn len(&self) -> usize {
        self.pods.len()
    }

    pub fn is_empty(&self) -> bool {
        self.pods.is_empty()
    }

    /// Record a watch error. The first error starts the grace time.
    pub fn error(&mut self, now: Instant) {
        self.error_since.get_or_insert(now);
    }

    pub fn apply(&mut self, event: Event<Pod>) {
        match event {
            // A new list keeps the error time: the old map stays
            // refused until the new list is complete.
            Event::Init => self.next = Some(HashMap::new()),
            Event::InitApply(pod) => {
                if let (Some(next), Some((uid, ips))) = (self.next.as_mut(), live(&pod)) {
                    next.insert(uid, ips);
                }
            }
            Event::InitDone => {
                self.pods = self.next.take().unwrap_or_default();
                self.ready = true;
                self.error_since = None;
            }
            Event::Apply(pod) => {
                self.error_since = None;
                match live(&pod) {
                    Some((uid, ips)) => {
                        self.pods.insert(uid, ips);
                    }
                    None => {
                        if let Some(uid) = &pod.metadata.uid {
                            self.pods.remove(uid);
                        }
                    }
                }
            }
            Event::Delete(pod) => {
                self.error_since = None;
                if let Some(uid) = &pod.metadata.uid {
                    self.pods.remove(uid);
                }
            }
        }
    }
}

/// The uid and addresses of a pod that is running and not terminating.
fn live(pod: &Pod) -> Option<(String, Vec<IpAddr>)> {
    if pod.metadata.deletion_timestamp.is_some() {
        return None;
    }
    let status = pod.status.as_ref()?;
    if status.phase.as_deref() != Some("Running") {
        return None;
    }
    let mut ips: Vec<IpAddr> = status
        .pod_ips
        .iter()
        .flatten()
        .filter_map(|p| p.ip.parse().ok())
        .collect();
    if ips.is_empty() {
        ips.extend(
            status
                .pod_ip
                .as_deref()
                .and_then(|ip| ip.parse::<IpAddr>().ok()),
        );
    }
    let uid = pod.metadata.uid.clone()?;
    (!ips.is_empty()).then_some((uid, ips))
}

/// Watch the runner pods and keep `map` current. It does not return.
pub async fn watch(client: Client, namespace: String, map: Arc<RwLock<PodMap>>) {
    let api: Api<Pod> = Api::namespaced(client, &namespace);
    let config = watcher::Config::default().labels(SELECTOR);
    let mut events = watcher::watcher(api, config).default_backoff().boxed();
    while let Some(event) = events.next().await {
        let mut map = map.write().unwrap_or_else(|e| e.into_inner());
        match event {
            Ok(event) => {
                map.apply(event);
                metrics::WATCH_UP.set(1);
            }
            Err(error) => {
                tracing::warn!(%error, "pod watch error");
                map.error(Instant::now());
                metrics::WATCH_UP.set(0);
            }
        }
        metrics::PODS.set(map.len() as i64);
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use k8s_openapi::api::core::v1::{PodIP, PodStatus};
    use k8s_openapi::apimachinery::pkg::apis::meta::v1::Time;

    pub(crate) fn pod(uid: &str, ip: &str, phase: &str) -> Pod {
        let mut pod = Pod::default();
        pod.metadata.uid = Some(uid.into());
        pod.status = Some(PodStatus {
            phase: Some(phase.into()),
            pod_ips: Some(vec![PodIP { ip: ip.into() }]),
            ..Default::default()
        });
        pod
    }

    pub(crate) fn listed(pods: Vec<Pod>) -> PodMap {
        let mut map = PodMap::default();
        map.apply(Event::Init);
        for pod in pods {
            map.apply(Event::InitApply(pod));
        }
        map.apply(Event::InitDone);
        map
    }

    #[test]
    fn empty_before_the_first_list() {
        let mut map = PodMap::default();
        map.apply(Event::Init);
        map.apply(Event::InitApply(pod("a", "10.0.0.1", "Running")));
        assert!(map.addresses("a", Instant::now()).is_none());
        assert!(!map.is_ready());
        map.apply(Event::InitDone);
        assert!(map.is_ready());
        let ip: IpAddr = "10.0.0.1".parse().unwrap();
        assert_eq!(map.addresses("a", Instant::now()), Some(&[ip][..]));
    }

    #[test]
    fn empty_after_the_watch_is_down_for_30_seconds() {
        let mut map = listed(vec![pod("a", "10.0.0.1", "Running")]);
        let start = Instant::now();
        map.error(start);
        assert!(
            map.addresses("a", start + Duration::from_secs(29))
                .is_some()
        );
        // A second error does not move the start of the grace time.
        map.error(start + Duration::from_secs(20));
        assert!(
            map.addresses("a", start + Duration::from_secs(30))
                .is_none()
        );
        // A new list that is not complete does not restore the map.
        map.apply(Event::Init);
        map.apply(Event::InitApply(pod("a", "10.0.0.1", "Running")));
        assert!(
            map.addresses("a", start + Duration::from_secs(31))
                .is_none()
        );
        map.apply(Event::InitDone);
        assert!(
            map.addresses("a", start + Duration::from_secs(31))
                .is_some()
        );
    }

    #[test]
    fn terminating_pod_leaves_the_map() {
        let mut map = listed(vec![pod("a", "10.0.0.1", "Running")]);
        let mut terminating = pod("a", "10.0.0.1", "Running");
        terminating.metadata.deletion_timestamp = Some(Time(Default::default()));
        map.apply(Event::Apply(terminating));
        assert!(map.addresses("a", Instant::now()).is_none());
    }

    #[test]
    fn pod_not_running_leaves_the_map() {
        let mut map = listed(vec![pod("a", "10.0.0.1", "Running")]);
        map.apply(Event::Apply(pod("a", "10.0.0.1", "Succeeded")));
        assert!(map.addresses("a", Instant::now()).is_none());
        map.apply(Event::Apply(pod("b", "10.0.0.2", "Running")));
        map.apply(Event::Delete(pod("b", "10.0.0.2", "Running")));
        assert!(map.is_empty());
    }

    #[test]
    fn pending_pod_is_not_listed() {
        let map = listed(vec![pod("a", "10.0.0.1", "Pending")]);
        assert!(map.is_empty());
    }
}
