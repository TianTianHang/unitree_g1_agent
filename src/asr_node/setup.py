from glob import glob

from setuptools import find_packages, setup

package_name = "asr_node"

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
    install_requires=["setuptools", "PyYAML", "numpy", "faster-whisper", "torch"],
    zip_safe=True,
    maintainer="unitree_g1_agent",
    maintainer_email="dev@example.local",
    description="Custom ASR node for Unitree G1",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "asr_node=asr_node.node:main",
        ],
    },
)
