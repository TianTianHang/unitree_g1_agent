{ pkgs, lib, stdenv, unitree-sdk2 }:

let
  ros2Path = "/opt/ros/humble";
in

stdenv.mkDerivation {
  pname = "unitree-ros2";
  version = "668d1ec5a05d1c38d3306bdca7d59f2ba3581a88";

  src = pkgs.fetchurl {
    url = "https://gh-proxy.com/https://github.com/unitreerobotics/unitree_ros2/archive/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88.tar.gz";
    sha256 = "3e96da843c611878e28148ce113d978e5464dec922fc06dcd8c340f8232a6883";
  };

  # 构建工具
  nativeBuildInputs = with pkgs; [
    cmake
  ];

  # 运行时依赖（除了 ROS2 核心）
  buildInputs = with pkgs; [
    unitree-sdk2  # 依赖 SDK2 包
  ];

  # ROS2 相关环境变量
  ROS_DISTRO = "humble";
  ROS2_PATH = ros2Path;

  # 禁用自动的 fixupPhase，因为 ROS2 包已经有正确的 RPATH
  dontFixup = true;

  configurePhase = ''
    echo "Using external ROS2 from: ${ros2Path}"

    # Source ROS2 环境（构建时需要）
    set -e
    source ${ros2Path}/setup.bash
    set +e
  '';

  buildPhase = ''
    echo "Building unitree ROS2 packages..."

    # 添加系统 PATH 以访问 colcon
    export PATH="/usr/bin:$PATH"

    # Source ROS2 环境
    source ${ros2Path}/setup.bash

    # 检查源码结构
    echo "Source directory contents:"
    ls -la

    # 检查 colcon 是否可用
    echo "Checking colcon:"
    which colcon || echo "colcon not found in PATH: $PATH"

    # 构建 ROS2 工作空间
    cd cyclonedds_ws
    colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release \
                 -DPython3_EXECUTABLE=/usr/bin/python3 \
                 -DPYTHON_EXECUTABLE=/usr/bin/python3 \
                 --base-paths src/unitree \
                 --event-handlers console_direct+
  '';

  installPhase = ''
    echo "Installing unitree ROS2 packages..."

    # 确保输出目录存在
    mkdir -p $out

    # 回到源码根目录
    cd ..

    echo "Current directory: $(pwd)"
    echo "Output directory: $out"
    echo "Contents:"
    ls -la

    # 直接复制整个 install 目录到输出
    if [ -d cyclonedds_ws/install ]; then
      echo "Found install directory, copying..."
      cp -r cyclonedds_ws/install/* $out/

      echo "Installation complete"
      echo "Final contents:"
      ls -la $out/
    else
      echo "Error: install directory not found"
      exit 1
    fi
  '';

  meta = {
    description = "Unitree ROS2 packages for controlling Unitree robots";
    homepage = "https://github.com/unitreerobotics/unitree_ros2";
    license = lib.licenses.bsd3;
    platforms = lib.platforms.linux;
    # 注意：此包依赖外部 ROS2 安装
  };
}
