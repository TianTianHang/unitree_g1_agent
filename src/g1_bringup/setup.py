from glob import glob

from setuptools import find_packages, setup

package_name = "g1_bringup"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="unitree_g1_agent",
    maintainer_email="2450804878@qq.com",
    description="Static motion backend selection for the G1 system",
    license="Apache-2.0",
    tests_require=["pytest"],
)
