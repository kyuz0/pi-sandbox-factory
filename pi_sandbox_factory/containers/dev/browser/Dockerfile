ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY package.json package-lock.json viewer-client.mjs /opt/betterwright/
RUN npm ci --prefix /opt/betterwright \
    && npm run build:viewer --prefix /opt/betterwright \
    && cp /opt/betterwright/node_modules/@novnc/novnc/LICENSE.txt /opt/betterwright/viewer-license.txt \
    && cat /opt/betterwright/node_modules/@novnc/novnc/vendor/pako/LICENSE >> /opt/betterwright/viewer-license.txt \
    && npm prune --omit=dev --prefix /opt/betterwright \
    && node /opt/betterwright/node_modules/playwright-core/cli.js install-deps chromium \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg tigervnc-standalone-server openbox fonts-noto-core \
    && command -v Xvnc openbox vncconfig setpriv \
    && rm -rf /var/lib/apt/lists/*
# The upstream installer checks the pinned browser archive's SHA-256.
RUN if [ "$(uname -m)" = aarch64 ]; then \
        apt-get update && apt-get install -y --no-install-recommends chromium \
        && rm -rf /var/lib/apt/lists/* && ln -s /usr/bin/chromium /opt/betterwright/chromium; \
    else \
        node --input-type=module -e "import {installChromiumFork} from '/opt/betterwright/node_modules/betterwright/dist/src/chromium-fork-install.js'; const r=await installChromiumFork({home:'/opt/betterwright'}); if (!r.binary) throw Error(r.skipped);" \
        && ln -s /opt/betterwright/.betterwright/chromium/linux-x64/betterchromium /opt/betterwright/chromium; \
    fi \
    && node --input-type=module -e "import {loadAdBlocker} from '/opt/betterwright/node_modules/betterwright/dist/src/ad-blocker.js'; await loadAdBlocker('/opt/betterwright/adblock-cache');" \
    && ln -s /opt/betterwright/node_modules/.bin/bun /usr/local/bin/bun \
    && ln -s /opt/betterwright/node_modules/.bin/betterwright /usr/local/bin/betterwright \
    && chmod -R a+rX /opt/betterwright
RUN cp /opt/pi-security/packages/pi-sandbox/src/browser/*.mjs /opt/betterwright/
COPY check.mjs browser.md /opt/betterwright/
ENV BETTERWRIGHT_CHROMIUM_ROOT=/opt/betterwright/.betterwright/chromium
USER node
