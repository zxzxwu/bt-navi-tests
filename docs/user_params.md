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

## custom_test_session

Type: string (Python class path)

The full Python path to a custom test session class (e.g., `my_module.MySession`). This class allows you to hook into the test lifecycle (setup/teardown) to perform custom actions.

The class must inherit from `navi.tests.navi_test_base.CustomTestSession`.

Available hooks to override:

* `setup_class()`: Called during `setup_class` after `async_setup_class`.
* `teardown_class()`: Called during `teardown_class` before `async_teardown_class`.
* `setup_test()`: Called during `setup_test` after `async_setup_test`.
* `teardown_test()`: Called during `teardown_test` before `async_teardown_test`.

The custom session class receives the test class instance in its constructor (`__init__`), which can be accessed via `self.test_class`.

Example:

In your Mobly config `config.yml`:

```yaml
TestParams:
  custom_test_session: my_custom_package.my_module.MySession
```

In `my_custom_package/my_module.py`:

```python
from navi.tests.navi_test_base import CustomTestSession

class MySession(CustomTestSession):
    def setup_test(self):
        self.test_class.logger.info("Running custom setup for test: %s", self.test_class.current_test_info.name)

    def teardown_test(self):
        self.test_class.logger.info("Running custom teardown")
```
