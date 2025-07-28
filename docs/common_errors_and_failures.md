# Common Errors and Failures

This page records the known common failures.

## General

### Test Cases are skipped

* Caused by: `Intended Behavior`

Expected. Before running tests, we check if DUT supports corresponding features by system property.

### TransportLostLost

* Caused by: `REF device`

Please check your USB connection, or take a bug report and see why the connection between Bumble and Controller is lost.

## Venti

### LePairingTest.test_legacy_pairing

* Caused by: `Android Bluetooth Stack`

Some legacy test cases cannot pass on Android releases before 25Q4 or equivalent mainline modules.

### LePairingTest.test_oob_pairing

* Caused by: `Android Bluetooth Stack`

Legacy OOB pairing has known failure on Android releases around 2025.
