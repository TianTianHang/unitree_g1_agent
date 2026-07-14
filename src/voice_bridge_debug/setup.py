import os
from glob import glob

from setuptools import find_packages, setup

package_name = "voice_bridge_debug"


def package_files(directory):
    paths = []
    for path, _, filenames in os.walk(directory):
        for filename in filenames:
            full_path = os.path.join(path, filename)
            paths.append(os.path.relpath(full_path, package_name))
    return paths


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["tests"]),
    package_data={package_name: package_files(f"{package_name}/frontend_dist")},
    include_package_data=True,
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", glob("config/*.yaml")),
        (f"share/{package_name}/launch", glob("launch/*.py")),
    ],
    install_requires=[
        "setuptools",
        "PyYAML==6.0.3",
        "fastapi==0.115.12",
        "starlette==0.46.2",
        "uvicorn[standard]==0.34.3",
    ],
    extras_require={
        "test": ["pytest==8.3.5", "httpx==0.28.1"],
    },
    zip_safe=True,
    maintainer="unitree_g1_agent",
    maintainer_email="dev@example.local",
    description="Web debug panel for Unitree G1 voice bridge",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "debug_panel_server = voice_bridge_debug.server:main",
        ],
    },
)
