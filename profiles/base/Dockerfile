ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY profile.md /opt/sandbox/profile.md
COPY check.py /opt/sandbox/profile-check.py
ENV SANDBOX_PROFILE=base
USER node
