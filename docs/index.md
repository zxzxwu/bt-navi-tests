# Home

This is a Bluetooth testing suite originally made for Pixel devices, but released for Android partners to evaluate their Bluetooth and Audio implementation.

## Suites

There are 3 predefined suites in the package:

1. Smoke (`python -m smoke` or `mobly_runner smoke`)

    A suite that all cases are expected to pass.

2. Venti (`python -m venti` or `mobly_runner venti`)

    A suite that allows some cases failed, or requiring more reference devices to run.

3. All (`python -m run_all` or `mobly_runner run_all`)

    All test cases.
