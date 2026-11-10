//! The request parser must not panic on any input.
#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = imbi_egress_proxy::request::parse(data);
});
