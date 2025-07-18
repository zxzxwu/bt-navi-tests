#!/usr/bin/env python
import pkgutil
import importlib
import inspect
import types
from mobly import base_test
from collections.abc import Generator
import navi.tests.benchmark
import navi.tests.functionality
import navi.tests.smoke

import mkdocs_gen_files


def iter_modules(root: types.ModuleType) -> Generator[types.ModuleType]:
    if not hasattr(root, "__path__"):
        return
    for module_info in pkgutil.iter_modules(root.__path__):
        module = importlib.import_module(f"{root.__name__}.{module_info.name}")
        yield module
        yield from iter_modules(module)


for category in (navi.tests.benchmark, navi.tests.functionality, navi.tests.smoke):
    category_name = category.__name__.split(".")[-1]
    with mkdocs_gen_files.open(f"cases/{category_name}.md", "w") as f:
        for module in iter_modules(category):
            for class_name, test_class in inspect.getmembers(
                module,
                lambda x: inspect.isclass(x) and issubclass(x, base_test.BaseTestClass),
            ):
                print(f"::: {module.__name__}.{class_name}", file=f)
                print("\toptions:", file=f)
                print("\t\tmembers:", file=f)
                for test_name, test_func in inspect.getmembers(
                    test_class,
                    lambda x: inspect.isfunction(x) and x.__name__.startswith("test_"),
                ):
                    print(f"\t\t\t- {test_name}", file=f)
