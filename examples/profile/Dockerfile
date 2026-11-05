ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY profile.md /opt/sandbox/profile.md
COPY check.py /opt/sandbox/profile-check.py
COPY reporting/ /opt/reporting/
COPY resources.json /opt/sandbox/resources.json
ENV SANDBOX_PROFILE=reporting
USER node
