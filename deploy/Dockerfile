FROM nginx:stable-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46

ARG MAZELAB_GIT_COMMIT
ARG MAZELAB_RUNTIME_SHA256
ARG MAZELAB_SOURCE_ARCHIVE_SHA256

LABEL org.opencontainers.image.title="Maskwa Maze Lab" \
      org.opencontainers.image.description="Local-first sphere-robot maze coding game" \
      org.opencontainers.image.revision="${MAZELAB_GIT_COMMIT}" \
      ca.spatterson.mazelab.runtime-sha256="${MAZELAB_RUNTIME_SHA256}" \
      ca.spatterson.mazelab.source-archive-sha256="${MAZELAB_SOURCE_ARCHIVE_SHA256}"

COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY deploy/security-headers.conf /etc/nginx/includes/mazelab-security.conf
COPY deploy/worker-security-headers.conf /etc/nginx/includes/mazelab-worker-security.conf
COPY deploy/compute-runtime-sha256.sh /usr/local/bin/compute-mazelab-runtime-sha256
COPY game/index.html game/styles.css game/icon.svg game/manifest.webmanifest game/service-worker.js game/THIRD_PARTY_NOTICES.md /tmp/mazelab-game/
COPY game/js/ /tmp/mazelab-game/js/
COPY game/levels/ /tmp/mazelab-game/levels/
COPY game/assets/stl/ /tmp/mazelab-game/assets/stl/
COPY game/vendor/ /tmp/mazelab-game/vendor/

RUN set -eu; \
    printf '%s\n' "$MAZELAB_GIT_COMMIT" | grep -Eq '^[0-9a-f]{40}$'; \
    printf '%s\n' "$MAZELAB_RUNTIME_SHA256" | grep -Eq '^[0-9a-f]{64}$'; \
    printf '%s\n' "$MAZELAB_SOURCE_ARCHIVE_SHA256" | grep -Eq '^[0-9a-f]{64}$'; \
    test -f /tmp/mazelab-game/index.html; \
    test -f /tmp/mazelab-game/service-worker.js; \
    test -f /tmp/mazelab-game/vendor/pyodide/pyodide.asm.wasm; \
    test ! -e /tmp/mazelab-game/README.md; \
    test ! -e /tmp/mazelab-game/tests; \
    actual_runtime_sha256="$(/usr/local/bin/compute-mazelab-runtime-sha256 /tmp/mazelab-game)"; \
    test "$actual_runtime_sha256" = "$MAZELAB_RUNTIME_SHA256"; \
    rm -rf /usr/share/nginx/html/* /usr/share/nginx/html/.[!.]* /usr/share/nginx/html/..?*; \
    cp -R /tmp/mazelab-game/. /usr/share/nginx/html/; \
    rm -rf /tmp/mazelab-game; \
    chmod 0555 /usr/local/bin/compute-mazelab-runtime-sha256; \
    chmod 0444 /etc/nginx/nginx.conf /etc/nginx/includes/mazelab-security.conf /etc/nginx/includes/mazelab-worker-security.conf; \
    find /usr/share/nginx/html -type d -exec chmod 0555 {} \;; \
    find /usr/share/nginx/html -type f -exec chmod 0444 {} \;; \
    nginx -t; \
    test "$(id -u nginx)" = 101; \
    test "$(id -g nginx)" = 101

EXPOSE 8080

USER 101:101
STOPSIGNAL SIGQUIT
ENTRYPOINT ["nginx", "-g", "daemon off;"]
