# The egress proxy image (plan 12.4): a static musl binary in a scratch
# image. The proxy does no TLS, so the image has no CA certificates.
# Build context: proxy/.
FROM rust:1.96.1-alpine3.22 AS build
RUN apk add --no-cache musl-dev
WORKDIR /src
# Only the build inputs: rust-toolchain.toml would make rustup download
# clippy and rustfmt.
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked \
    && cp target/release/imbi-egress-proxy /imbi-egress-proxy

FROM scratch
COPY --from=build --chmod=0555 /imbi-egress-proxy /imbi-egress-proxy
USER 65532:65532
ENTRYPOINT ["/imbi-egress-proxy"]
