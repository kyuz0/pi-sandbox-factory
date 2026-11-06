FROM docker.io/library/debian:bookworm-slim
ARG USER_UID=1000
ARG USER_GID=1000
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client python3 tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g "$USER_GID" sshaccess && useradd -m -u "$USER_UID" -g "$USER_GID" sshaccess \
    && mkdir -p /private /run/ssh-access \
    && chown sshaccess:sshaccess /private /run/ssh-access \
    && chmod 700 /private /run/ssh-access
COPY service.py unlock.py /opt/ssh-access/
ENV SSH_AUTH_SOCK=/run/ssh-access/agent.sock
USER sshaccess
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/opt/ssh-access/service.py"]
