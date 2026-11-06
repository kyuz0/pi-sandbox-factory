ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY package.json package-lock.json /opt/pi-communications/
RUN npm ci --omit=dev --ignore-scripts --legacy-peer-deps --prefix /opt/pi-communications
COPY extension.mjs /opt/pi-communications/
USER node
