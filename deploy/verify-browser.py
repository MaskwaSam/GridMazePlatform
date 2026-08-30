#!/usr/bin/env python3
"""Browser acceptance for a privately exposed Maskwa Maze Lab origin."""

from __future__ import annotations

import argparse
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="http://mazelab.spatterson.ca:8877",
        help="Privately reachable Maze Lab origin",
    )
    parser.add_argument(
        "--chrome",
        default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        help="Chrome or Chromium executable",
    )
    parser.add_argument(
        "--map-host-to",
        default="127.0.0.1",
        help="Optional address for Chrome's host resolver rule; pass an empty value to disable",
    )
    args = parser.parse_args()

    parsed = urlparse(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        parser.error("--base-url must be an absolute HTTP(S) URL")

    browser_args = ["--enable-unsafe-swiftshader", "--disable-background-networking"]
    if args.map_host_to:
        browser_args.append(f"--host-resolver-rules=MAP {parsed.hostname} {args.map_host_to}")
    if parsed.scheme == "http":
        private_origin = f"{parsed.scheme}://{parsed.netloc}"
        browser_args.append(
            f"--unsafely-treat-insecure-origin-as-secure={private_origin}"
        )

    page_errors: list[str] = []
    console_errors: list[str] = []
    external_requests: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chrome,
            headless=True,
            args=browser_args,
        )
        context = browser.new_context(service_workers="allow")
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "request",
            lambda request: external_requests.append(request.url)
            if urlparse(request.url).hostname != parsed.hostname
            else None,
        )

        response = page.goto(
            f"{args.base_url.rstrip('/')}?level=straight-start",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        assert response is not None and response.ok, "application document did not load"
        assert page.title() == "Maskwa Maze Lab"
        page.locator("#scene-loading").wait_for(state="hidden", timeout=30_000)
        assert page.locator("#blockly-editor .blocklySvg").count() == 1
        assert page.locator("#run-button").is_disabled()

        page.locator("#place-button").click()
        page.locator("#python-tab").click()
        page.locator("#python-editor").fill('print("python-csp-ready")\n')
        assert page.locator("#run-button").is_enabled()
        page.locator("#run-button").click()
        page.locator("#program-log").filter(has_text="python-csp-ready").wait_for(
            timeout=30_000
        )

        if not context.service_workers:
            context.wait_for_event("serviceworker", timeout=30_000)
        page.wait_for_timeout(2_000)
        context.set_offline(True)
        page.reload(wait_until="domcontentloaded", timeout=30_000)
        page.locator("#scene-loading").wait_for(state="hidden", timeout=30_000)
        assert page.locator("#blockly-editor .blocklySvg").count() == 1
        context.set_offline(False)

        expected_private_http_warning = (
            "Cross-Origin-Opener-Policy header has been ignored"
        )
        actionable_console_errors = [
            message
            for message in console_errors
            if not (
                parsed.scheme == "http"
                and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                and expected_private_http_warning in message
            )
        ]
        assert not page_errors, f"page errors: {page_errors}"
        assert not actionable_console_errors, f"console errors: {actionable_console_errors}"
        assert not external_requests, f"external requests: {external_requests}"
        browser.close()

    print(
        "Browser acceptance passed: Three.js, Blockly, local Pyodide, and an "
        "offline reload initialized under production headers."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
