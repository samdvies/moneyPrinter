FROM rust:1.95.0-bookworm AS rust-build

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends musl-tools ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && rustup target add x86_64-unknown-linux-musl

COPY execution ./execution

RUN cd execution \
    && cargo build --release -p execution-bin --target x86_64-unknown-linux-musl \
    && strip target/x86_64-unknown-linux-musl/release/execution-bin

FROM debian:bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=rust-build /workspace/execution/target/x86_64-unknown-linux-musl/release/execution-bin /usr/local/bin/execution-bin

ENTRYPOINT ["/usr/local/bin/execution-bin"]
