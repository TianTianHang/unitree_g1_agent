{
  description = "Unitree G1 Agent - SDK2 Package";

  inputs = {
    # 使用 gh-proxy.com 镜像下载 nixpkgs
    nixpkgs = {
      type = "tarball";
      url = "https://gh-proxy.com/https://github.com/NixOS/nixpkgs/archive/b5aa0fbd538984f6e3d201be0005b4463d8b09f8.tar.gz";
    };
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      # 导入独立的包定义
      callPackage = pkgs.callPackage;
      systemPytest = pkgs.writeShellScriptBin "pytest" ''
        exec /usr/bin/python3 -m pytest "$@"
      '';
    in {
      packages.${system} = {
        # 从独立文件导入包
        unitree-sdk2 = callPackage ./nix/pkgs/unitree-sdk2.nix { };
        unitree-ros2 = callPackage ./nix/pkgs/unitree-ros2.nix {
          inherit (self.packages.${system}) unitree-sdk2;
        };

        default = self.packages.${system}.unitree-sdk2;
      };

      devShells.${system} = {
        default = pkgs.mkShell {
          buildInputs = with pkgs; [
            cmake
            gcc
            ninja
            git
            systemPytest
          ];

          inputsFrom = [
            self.packages.${system}.unitree-sdk2
            self.packages.${system}.unitree-ros2
          ];

          shellHook = ''
            echo "=================================="
            echo "Unitree G1 Agent Development Environment"
            echo "=================================="
            echo "SDK2: ${self.packages.${system}.unitree-sdk2}"
            echo "ROS2: ${self.packages.${system}.unitree-ros2}"

            # Source ROS2 environment if available
            if [ -d /opt/ros/humble ]; then
              echo ""
              echo "ROS2 Humble detected at /opt/ros/humble"
              source /opt/ros/humble/setup.bash

              # Source unitree-ros2 包的 setup.bash
              if [ -f ${self.packages.${system}.unitree-ros2}/setup.bash ]; then
                source ${self.packages.${system}.unitree-ros2}/setup.bash
                echo "Unitree ROS2 packages loaded"
                echo "Available unitree packages:"
                ros2 pkg list 2>/dev/null | grep unitree || echo "  (ros2 pkg list failed)"
              fi

              echo "ROS2 environment configured"
              echo "AMENT_PREFIX_PATH=$AMENT_PREFIX_PATH"

              source install/setup.bash
            fi
            export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
            export CYCLONEDDS_URI='file://./cyclone_ds_lo.xml' 
            echo ""
            echo "Available packages:"
            echo "  unitree-sdk2: ${self.packages.${system}.unitree-sdk2}"
            echo "  unitree-ros2: ${self.packages.${system}.unitree-ros2}"
            echo ""
            echo "Build commands:"
            echo "  nix build .#unitree-sdk2    - Build SDK2 package"
            echo "  nix build .#unitree-ros2     - Build ROS2 package"
            echo "=================================="
          '';
        };
      };
    };
}
