# User Params

In config.yml, some user params are used by Navi for particular purposes.

## max_retry_count

Type: integer

The max retry count applied to all test cases.

Note: If test cases are already decorated with `retry()`, it will select the larger retry count among decorators and user params.

## device_serials

Type: string

A list of device serial numbers separated with comma. When present, test devices will be allocated based on the given order, instead of order provided by config or adb.

Example: `001,002,003`

## crown_driver

Type: one of `android`, `passthrough`, `cf_rootcanal`, default is `android`

The type of Crown (REF) driver.

* `android`: Running HCI Proxy on Android device.
* `passthrough`: Use raw Bumble transports (require `crown_driver_specs`).
* `cf_rootcanal`: Request Rootcanal ports from Cuttlefish emulators.

## crown_driver_specs

Type: list or comma-separated list string

A list of bumble transport specs. REF Bumble devices will run above them.

Example: `["tcp-client:127.0.0.1:7300", "tcp-client:127.0.0.1:7300"]`

## record_full_data

Type: boolean, default is False

Whether full log data will be recorded no matter passed or not, including:

* Bugreports on pass
* Snoop logs and dumpsys on pass
* Recorded audio data

## dump_crown_log_on_fail

Type: boolean, default is False

Whether to dump crown log on fail for debugging.
