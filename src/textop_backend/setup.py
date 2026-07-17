from glob import glob

from setuptools import find_packages, setup

package_name = "textop_backend"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["tests"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", glob("config/*.yaml")),
        (f"share/{package_name}/launch", glob("launch/*.py")),
    ],
    install_requires=["setuptools", "PyYAML", "numpy"],
    zip_safe=True,
    maintainer="unitree_g1_agent",
    maintainer_email="2450804878@qq.com",
    description="TextOp text-to-motion generation and tracking backend",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={"console_scripts": [
        "textop_tracker_node = textop_backend.tracker_node:main",
        "textop_generator_node = textop_backend.generator_node:main",
    ]},
)
