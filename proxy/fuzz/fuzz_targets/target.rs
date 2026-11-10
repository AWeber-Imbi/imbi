//! Target normalization must not panic, and its output must be in the
//! canonical form: a second pass gives the same result.
#![no_main]

use imbi_egress_proxy::request::canonical_target;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &str| {
    if let Some((host, port)) = canonical_target(data) {
        assert_ne!(port, 0);
        let again = canonical_target(&format!("{host}:{port}"));
        assert_eq!(again, Some((host, port)));
    }
});
