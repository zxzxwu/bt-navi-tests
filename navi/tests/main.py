#  Copyright 2025 Google LLC
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

"""Generic functionality test suite for Bluetooth."""

from collections.abc import Sequence
import inspect
import pkgutil
import importlib
import types
from mobly import base_test
from mobly import suite_runner

from navi.tests import smoke
from navi.tests import functionality


def _run_suite(modules: Sequence[types.ModuleType]) -> None:
    test_classes: list[base_test.BaseTestClass] = []
    for module in modules:
        for submodule_info in pkgutil.iter_modules(
            module.__path__, prefix=module.__name__ + "."
        ):
            submodule = importlib.import_module(submodule_info.name)
            for _, test_class in inspect.getmembers(
                submodule,
                lambda x: inspect.isclass(x) and issubclass(x, base_test.BaseTestClass),
            ):
                test_classes.append(test_class)
    suite_runner.run_suite(test_classes)


def run_smoke() -> None:
    _run_suite([smoke])


def run_venti() -> None:
    _run_suite([functionality])


def run_all() -> None:
    _run_suite([smoke, functionality])
