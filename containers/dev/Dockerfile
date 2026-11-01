FROM docker.io/library/node:22-bookworm-slim
ARG PI_VERSION=1.2.0
ARG PENDANT_VERSION=0.40.0
ARG USER_UID=1000
ARG USER_GID=1000
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git python3 socat tini procps ripgrep iproute2 unzip tmux \
    && rm -rf /var/lib/apt/lists/* \
    && if [ "$USER_GID" != 1000 ]; then groupmod -g "$USER_GID" node; fi \
    && if [ "$USER_UID" != 1000 ]; then usermod -u "$USER_UID" node; fi \
    && chown -R node:node /home/node
COPY document-packages.txt document-requirements.txt install-document-tools.sh /opt/document-tools/
RUN apt-get update \
    && xargs -r apt-get install -y --no-install-recommends < /opt/document-tools/document-packages.txt \
    && cp /opt/document-tools/document-requirements.txt /opt/document-tools/requirements.txt \
    && sh /opt/document-tools/install-document-tools.sh \
    && rm -rf /var/lib/apt/lists/*
COPY check-document-tools.py /opt/document-tools/check.py
COPY document-tools.md /opt/sandbox/document-tools.md
RUN npm install -g "@earendil-works/pi-coding-agent@${PI_VERSION}"
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev libseccomp-dev meson ninja-build pkg-config libcap-dev libselinux1-dev \
    && rm -rf /var/lib/apt/lists/*
COPY security/ /opt/pi-security/
RUN python3 /opt/pi-security/fetch.py \
    && npm ci --omit=dev --prefix /opt/pi-security \
    && python3 /opt/pi-security/scripts/prepare-container.py
ENV PI_SANDBOX_CONTAINER=1
COPY security/security.md /opt/sandbox/security.md
# Preload the extension during the trusted image build, before network restrictions.
RUN curl -fSL --retry 3 \
    "https://open-vsx.org/api/cdervis/vscode-pi/${PENDANT_VERSION}/file/cdervis.vscode-pi-${PENDANT_VERSION}.vsix" \
    -o /tmp/pendant.vsix \
    && mkdir -p /opt/pendant \
    && unzip -q /tmp/pendant.vsix 'extension/*' -d /opt/pendant \
    && rm /tmp/pendant.vsix \
    && mv /opt/pendant/extension "/opt/pendant/cdervis.vscode-pi-${PENDANT_VERSION}"
COPY check-pendant.py /opt/sandbox/check-pendant.py
RUN python3 /opt/sandbox/check-pendant.py "${PENDANT_VERSION}"
COPY entrypoint.sh /usr/local/bin/sandbox-entrypoint
COPY --from=pi-local-model-manager / /opt/pi-local-model-manager/
COPY --from=pi-advisor / /opt/pi-advisor/
COPY bootstrap.py /usr/local/lib/sandbox-bootstrap.py
RUN chmod 755 /usr/local/bin/sandbox-entrypoint \
    && mkdir -p /workspace /pi-config /run/egress \
    && chown node:node /workspace
ENV PI_CODING_AGENT_DIR=/home/node/.pi/agent
USER node
WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/sandbox-entrypoint"]
