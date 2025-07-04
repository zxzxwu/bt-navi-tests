from glob import glob
from setuptools import setup
from pybind11.setup_helpers import Pybind11Extension, build_ext

ext_modules = [
    Pybind11Extension(
        "navi.utils.lc3_pybind",
        sorted(glob("navi/utils/lc3_pybind.cc") + glob("liblc3/src/**.c")),
        include_dirs=["liblc3/include"],
    ),
]

setup(
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
)
