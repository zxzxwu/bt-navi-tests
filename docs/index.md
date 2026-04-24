# Home

This is a Bluetooth testing suite originally made for Pixel devices, but released for Android partners to evaluate their Bluetooth and Audio implementation.

## Suites

There are 3 predefined suites in the package:

1. Smoke (`python -m navi_smoke` or `mobly_runner navi_smoke`)

    A suite that all cases are expected to pass.

2. Venti (`python -m navi_venti` or `mobly_runner navi_venti`)

    A suite that allows some cases failed, or requiring more reference devices to run.

3. Firmware (`python -m navi_firmware` or `mobly_runner navi_firmware`)

    A suite designed for HCI-level validation.

4. All (`python -m navi_all` or `mobly_runner navi_all`)

    All test cases.
