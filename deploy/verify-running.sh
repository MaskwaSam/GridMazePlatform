#!/bin/sh
set -eu

mode=${1:-private}
compose_file=${MAZELAB_COMPOSE_FILE:-deploy/compose.yaml}
expected_commit=${MAZELAB_GIT_COMMIT:?Set MAZELAB_GIT_COMMIT}
expected_runtime_sha256=${MAZELAB_RUNTIME_SHA256:?Set MAZELAB_RUNTIME_SHA256}
expected_source_archive_sha256=${MAZELAB_SOURCE_ARCHIVE_SHA256:?Set MAZELAB_SOURCE_ARCHIVE_SHA256}
connector_name=${MAZELAB_CONNECTOR_NAME:-spatterson-cloudflared}

case "$mode" in
  private|connector-attached) ;;
  *) echo "Usage: $0 [private|connector-attached]" >&2; exit 2 ;;
esac

container_id=$(docker compose -f "$compose_file" ps -q mazelab)
test -n "$container_id"
test "$(docker inspect -f '{{.State.Status}}' "$container_id")" = running
test "$(docker inspect -f '{{.State.Health.Status}}' "$container_id")" = healthy
test "$(docker inspect -f '{{.Config.User}}' "$container_id")" = 101:101
test "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$container_id")" = true
test "$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$container_id")" = "$expected_commit"
test "$(docker inspect -f '{{index .Config.Labels "ca.spatterson.mazelab.runtime-sha256"}}' "$container_id")" = "$expected_runtime_sha256"
test "$(docker inspect -f '{{index .Config.Labels "ca.spatterson.mazelab.source-archive-sha256"}}' "$container_id")" = "$expected_source_archive_sha256"
test "$(docker inspect -f '{{json .HostConfig.CapDrop}}' "$container_id")" = '["ALL"]'
docker inspect -f '{{range .HostConfig.SecurityOpt}}{{println .}}{{end}}' "$container_id" | grep -qx 'no-new-privileges:true'
test "$(docker inspect -f '{{.HostConfig.Memory}}' "$container_id")" = 134217728
test "$(docker inspect -f '{{.HostConfig.NanoCpus}}' "$container_id")" = 500000000
test "$(docker inspect -f '{{.HostConfig.PidsLimit}}' "$container_id")" = 64
test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$container_id")" = unless-stopped
test "$(docker inspect -f '{{.HostConfig.LogConfig.Type}}' "$container_id")" = json-file
test "$(docker inspect -f '{{index .HostConfig.LogConfig.Config "max-size"}}' "$container_id")" = 10m
test "$(docker inspect -f '{{index .HostConfig.LogConfig.Config "max-file"}}' "$container_id")" = 3
test "$(docker port "$container_id")" = ""
test "$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$container_id" | sed '/^$/d' | sort)" = mazelab_edge
test "$(docker exec "$container_id" /usr/local/bin/compute-mazelab-runtime-sha256 /usr/share/nginx/html)" = "$expected_runtime_sha256"

image_ref=$(docker inspect -f '{{.Config.Image}}' "$container_id")
probe_network=mazelab_edge

network_internal=$(docker network inspect -f '{{.Internal}}' mazelab_edge)
test "$network_internal" = true
app_container_name=$(docker inspect -f '{{.Name}}' "$container_id" | sed 's#^/##')

if [ "$mode" = private ]; then
  if docker network inspect -f '{{range $id, $value := .Containers}}{{println $value.Name}}{{end}}' mazelab_edge | grep -qx "$connector_name"; then
    echo "Connector must not be attached during private verification." >&2
    exit 1
  fi
  network_members=$(docker network inspect -f '{{range $id, $value := .Containers}}{{println $value.Name}}{{end}}' mazelab_edge | sed '/^$/d' | sort)
  test "$network_members" = "$app_container_name"
else
  expected_connector_id=${MAZELAB_CONNECTOR_ID_BEFORE:?Set MAZELAB_CONNECTOR_ID_BEFORE from the pre-attachment snapshot}
  expected_connector_image_id=${MAZELAB_CONNECTOR_IMAGE_ID_BEFORE:?Set MAZELAB_CONNECTOR_IMAGE_ID_BEFORE from the pre-attachment snapshot}
  expected_connector_restarts=${MAZELAB_CONNECTOR_RESTART_COUNT_BEFORE:?Set MAZELAB_CONNECTOR_RESTART_COUNT_BEFORE from the pre-attachment snapshot}
  connector_networks_before=${MAZELAB_CONNECTOR_NETWORKS_BEFORE:?Set sorted comma-separated MAZELAB_CONNECTOR_NETWORKS_BEFORE}
  test "$(docker inspect -f '{{.Id}}' "$connector_name")" = "$expected_connector_id"
  test "$(docker inspect -f '{{.Image}}' "$connector_name")" = "$expected_connector_image_id"
  test "$(docker inspect -f '{{.RestartCount}}' "$connector_name")" = "$expected_connector_restarts"
  current_connector_networks=$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$connector_name" | sed '/^$/d' | sort | paste -sd, -)
  expected_connector_networks=$(printf '%s\nmazelab_edge\n' "$connector_networks_before" | tr ',' '\n' | sed '/^$/d' | sort -u | paste -sd, -)
  test "$current_connector_networks" = "$expected_connector_networks"
  network_members=$(docker network inspect -f '{{range $id, $value := .Containers}}{{println $value.Name}}{{end}}' mazelab_edge | sed '/^$/d' | sort)
  expected_network_members=$(printf '%s\n%s\n' "$app_container_name" "$connector_name" | sort)
  test "$network_members" = "$expected_network_members"
  probe_network="container:$connector_name"
fi

probe() {
  docker run --rm --network "$probe_network" --entrypoint wget "$image_ref" \
    --timeout=5 --tries=1 -q -O - --header="Host: mazelab.spatterson.ca" "$1"
}

probe_headers() {
  docker run --rm --network "$probe_network" --entrypoint wget "$image_ref" \
    --timeout=5 --tries=1 -S -O /dev/null --header="Host: mazelab.spatterson.ca" "$1" 2>&1
}

raw_request() {
  request_text=$1
  printf '%b' "$request_text" | docker run -i --rm --network "$probe_network" \
    --entrypoint nc "$image_ref" mazelab 8080
}

test "$(probe http://mazelab:8080/healthz)" = healthy
root_body=$(probe http://mazelab:8080/)
printf '%s\n' "$root_body" | grep -q '<title>Maskwa Maze Lab</title>'
service_worker_body=$(probe http://mazelab:8080/service-worker.js)
printf '%s\n' "$service_worker_body" | grep -q 'maskwa-maze-lab-v40'

root_headers=$(probe_headers http://mazelab:8080/)
printf '%s\n' "$root_headers" | grep -Eiq 'HTTP/[0-9.]+ 200'
printf '%s\n' "$root_headers" | grep -Eiq 'Cache-Control: no-store, no-transform'
printf '%s\n' "$root_headers" | grep -Eiq 'Content-Security-Policy:'

service_worker_headers=$(probe_headers http://mazelab:8080/service-worker.js)
printf '%s\n' "$service_worker_headers" | grep -Eiq 'Content-Type: application/javascript'
printf '%s\n' "$service_worker_headers" | grep -Eiq 'Cache-Control: no-store, no-transform'
printf '%s\n' "$service_worker_headers" | grep -Eiq 'Service-Worker-Allowed: /'

wasm_headers=$(probe_headers http://mazelab:8080/vendor/pyodide/pyodide.asm.wasm)
printf '%s\n' "$wasm_headers" | grep -Eiq 'Content-Type: application/wasm'

missing_headers=$(probe_headers http://mazelab:8080/not-a-real-file.js || true)
printf '%s\n' "$missing_headers" | grep -Eiq 'HTTP/[0-9.]+ 404'

head_headers=$(docker run --rm --network "$probe_network" --entrypoint wget "$image_ref" \
  --timeout=5 --tries=1 --spider -S --header="Host: mazelab.spatterson.ca" http://mazelab:8080/ 2>&1)
printf '%s\n' "$head_headers" | grep -Eiq 'HTTP/[0-9.]+ 200'

post_headers=$(raw_request 'POST / HTTP/1.1\r\nHost: mazelab.spatterson.ca\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
printf '%s\n' "$post_headers" | grep -Eiq 'HTTP/[0-9.]+ 405'
printf '%s\n' "$post_headers" | grep -Eiq 'Allow: GET, HEAD'

invalid_host_headers=$(raw_request 'GET / HTTP/1.1\r\nHost: invalid.example\r\nConnection: close\r\n\r\n')
if printf '%s\n' "$invalid_host_headers" | grep -Eiq 'HTTP/[0-9.]+'; then
  echo "Unknown Host returned an HTTP response instead of being dropped." >&2
  exit 1
fi

echo "Maze Lab $mode verification passed for $expected_commit ($expected_runtime_sha256; archive $expected_source_archive_sha256)."
