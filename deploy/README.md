# Maskwa Maze Lab production deployment

This package serves the committed standalone game at
`https://mazelab.spatterson.ca` from a dedicated, non-root NGINX container.
The application has no backend, server-side student data, host port, remote
runtime dependency, or persistent volume. Student code, placements, and attempt
history stay in the browser; `.maskwamaze` export/import is the portable recovery
path.

The game includes dormant versioned multiplayer client modules, but this release
still has no WebSocket service and no `/ws` route. Loading the app does not open a
socket. Do not point the client at an ad hoc WebSocket server. The authority,
privacy, ordering, security, two-Chromebook, and rollback gates for a future
same-origin `wss://mazelab.spatterson.ca/ws` service are specified in
`game/MULTIPLAYER.md`.

## Request path and service URL

```text
Browser -> Cloudflare edge -> managed spatterson-site Tunnel
        -> standalone spatterson-cloudflared -> mazelab_edge
        -> mazelab:8080 -> NGINX
```

Use these Cloudflare **Published application** fields only after private origin
verification succeeds:

- Subdomain: `mazelab`
- Domain: `spatterson.ca`
- Path: leave blank
- Service URL: `http://mazelab:8080`

The Compose project joins only the pre-created internal `mazelab_edge` network.
Attach the existing connector to that network without disconnecting it from any
existing network and without restarting or recreating the connector. Do not
publish a host port, change router forwarding, modify the main-site `web`
service, or touch PatterDraw, GeoGon, Moodle, or `mesconline.ca`.

## Release gate

1. Commit the exact `game/`, `deploy/`, level-generator, and two release-test
   files.
2. Run `deploy/prepare-release.sh /absolute/new/release-directory`. The script
   refuses an uncommitted release surface, derives the full commit and runtime
   digest, archives that exact commit, reruns the game/deployment tests from the
   extracted archive, and writes `release.env` plus a human-readable receipt.
   Unrelated CAD/catalog work may remain in the checkout because it is not copied
   into or used to label this release.
3. Independently verify the source-archive SHA-256 from the receipt after every
   transfer and before extraction. Load only the generated `release.env`; do not
   hand-type release identity values.
4. Render the Compose model and confirm that it contains no `ports` entry and
   names only `mazelab_edge`.

The image build checks the 40-character Git commit and both 64-character receipt
digests, recomputes the exact allowlisted runtime digest, rejects symlinks, copies
only the declared runtime surface, validates NGINX, and records the release
identity in OCI labels. The source-archive digest is independently rechecked
before remote extraction; the container never trusts a dirty working directory.

## Initial deployment gates

Before any mutation, record:

- the current public DNS/Tunnel route state for `mazelab.spatterson.ca`;
- the absence or exact state of a `mazelab` container, image, target directory,
  and `mazelab_edge` network;
- the connector container ID, image, restart count, and complete network list;
- neighboring service health and host listeners.

Create only an internal `mazelab_edge` network. Build and start only the
`mazelab` service while the connector is still absent from that network. Run
`deploy/verify-running.sh private` and prove the correct Host returns the health
endpoint and app, an unknown Host is rejected, the WebAssembly response uses
`application/wasm`, the service worker and HTML are `no-store`, missing files
are 404, and the container is non-root, read-only, capability-free,
resource-bounded, log-bounded, and has no published host port.

For a private origin temporarily exposed to the operator workstation, run
`python3 deploy/verify-browser.py --base-url <private-origin>`. It proves that
Three.js, Blockly, and the local Pyodide worker initialize under the production
headers and that the page makes no cross-origin application requests. Remove
the temporary operator-only port or proxy immediately after this check; the
production Compose model must remain host-port-free.

After private acceptance, attach the existing connector to `mazelab_edge`
without restarting it. Run `deploy/verify-running.sh connector-attached`, then
add the Cloudflare route above. The attached verifier requires the pre-attachment
connector ID, image ID, restart count, and sorted network list in the documented
`MAZELAB_CONNECTOR_*_BEFORE` variables; it rejects identity, restart, or neighboring
network drift and probes `mazelab:8080` from a disposable process sharing the
connector's network namespace. Public acceptance must cover HTTPS, the expected
headers, a fresh-profile PWA load, all seven mazes, Blockly and Python execution,
the local Pyodide worker, a `.maskwamaze` export/import round trip, offline reload,
fullscreen, and absence of external application requests. Recheck
`spatterson.ca`, `bible.spatterson.ca`, `draw.spatterson.ca`,
`geogon.spatterson.ca`, and `mesconline.ca` after attachment and after route
activation.

## Rollback

Retain the exact pre-deploy connector and public route state, release archive,
image ID, labels, rendered Compose model, and verification output through the
rollback window. Initial rollback is narrowly scoped:

1. Remove only the `mazelab.spatterson.ca` Published application route and
   verify or remove only its managed DNS record.
2. Disconnect only `spatterson-cloudflared` from `mazelab_edge`; do not restart
   or recreate the connector.
3. Stop only the `mazelab` Compose project.
4. Remove `mazelab_edge` only after proving that no container remains attached.

Do not delete the staged release or accepted image until the rollback window has
closed.
