FROM docker.io/library/debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends squid socat tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /usr/local/bin/proxy-entrypoint
RUN chmod 755 /usr/local/bin/proxy-entrypoint
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/proxy-entrypoint"]
