ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY package.json package-lock.json /opt/betterwright/
RUN test "$(uname -m)" = x86_64 || { echo 'Betterwright currently requires a Linux x86_64 host'; exit 1; }
RUN npm ci --omit=dev --prefix /opt/betterwright \
    && node /opt/betterwright/node_modules/playwright-core/cli.js install-deps chromium \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# The upstream installer checks the pinned browser archive's SHA-256.
RUN node --input-type=module -e "import {installChromiumFork} from '/opt/betterwright/node_modules/betterwright/dist/src/chromium-fork-install.js'; const r=await installChromiumFork({home:'/opt/betterwright'}); if (!r.binary) throw Error(r.skipped);" \
    && node --input-type=module -e "import {loadAdBlocker} from '/opt/betterwright/node_modules/betterwright/dist/src/ad-blocker.js'; await loadAdBlocker('/opt/betterwright/adblock-cache');" \
    && ln -s /opt/betterwright/node_modules/.bin/bun /usr/local/bin/bun \
    && ln -s /opt/betterwright/node_modules/.bin/betterwright /usr/local/bin/betterwright \
    && chmod -R a+rX /opt/betterwright
COPY browser.mjs extension.mjs check.mjs browser.md /opt/betterwright/
ENV BETTERWRIGHT_CHROMIUM_ROOT=/opt/betterwright/.betterwright/chromium
USER node
