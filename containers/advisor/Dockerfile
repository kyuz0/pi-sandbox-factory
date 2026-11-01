FROM docker.io/library/node:22-bookworm-slim
ARG USER_UID=1000
ARG USER_GID=1000
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl bubblewrap socat tini dbus-daemon gnome-keyring libsecret-tools xdg-dbus-proxy python3 \
    && rm -rf /var/lib/apt/lists/* \
    && if [ "$USER_GID" != 1000 ]; then groupmod -g "$USER_GID" node; fi \
    && if [ "$USER_UID" != 1000 ]; then usermod -u "$USER_UID" node; fi
RUN npm install -g @openai/codex \
    && find /usr/local/lib/node_modules/@openai -type f -name codex -executable -exec install -m 755 '{}' /usr/local/bin/advisor-codex ';' \
    && test -x /usr/local/bin/advisor-codex
RUN curl -fSL --retry 3 https://antigravity.google/cli/install.sh -o /tmp/install-agy.sh \
    && bash /tmp/install-agy.sh --dir /usr/local/bin && rm /tmp/install-agy.sh
COPY --from=pi-advisor / /opt/advisor/
COPY advisor/login.sh advisor/entrypoint.sh /opt/advisor/
RUN mkdir -p /work /run/advisor /run/egress /run/advisor-bus \
    && chown -R node:node /home/node /work /run/advisor /run/advisor-bus \
    && chmod 700 /run/advisor /run/advisor-bus \
    && chmod 755 /opt/advisor/*.sh
ENV HOME=/home/node CODEX_HOME=/home/node/.codex \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/advisor-bus/bus \
    XDG_RUNTIME_DIR=/run/advisor-bus AGY_CLI_DISABLE_AUTO_UPDATE=true
USER node
WORKDIR /work
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/advisor/entrypoint.sh"]
