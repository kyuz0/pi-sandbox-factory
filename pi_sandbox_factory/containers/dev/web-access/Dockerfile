ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY package.json package-lock.json /opt/pi-web-access/
RUN npm ci --omit=dev --ignore-scripts --prefix /opt/pi-web-access
USER node
