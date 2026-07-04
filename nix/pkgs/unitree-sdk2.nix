{ pkgs, lib, stdenv }:

stdenv.mkDerivation {
  pname = "unitree-sdk2";
  version = "master";

  src = pkgs.fetchurl {
    url = "https://gh-proxy.com/https://github.com/unitreerobotics/unitree_sdk2/archive/refs/heads/master.tar.gz";
    sha256 = "eea7220acdc7cc25200d6a3fa3226db4a968b3503befc92eff1207965897c84e";
  };

  nativeBuildInputs = with pkgs; [
    cmake
    ninja
    gcc
  ];

  buildInputs = with pkgs; [
    libusb1
    eigen
  ];

  configurePhase = ''
    mkdir -p build
    cd build
    cmake .. -G Ninja -DCMAKE_BUILD_TYPE=Release
  '';

  buildPhase = ''
    ninja
  '';

  installPhase = ''
    mkdir -p $out/lib
    mkdir -p $out/include

    # Install library (check different locations)
    if [ -f build/libunitree_sdk2.so ]; then
      cp build/libunitree_sdk2.so $out/lib/
    fi

    if [ -f lib/x86_64/libunitree_sdk2.a ]; then
      cp lib/x86_64/libunitree_sdk2.a $out/lib/
    fi

    if [ -d lib/x86_64 ]; then
      cp -r lib/x86_64/*.so* $out/lib/ 2>/dev/null || true
    fi

    # Install headers
    if [ -d include ]; then
      cp -r include/* $out/include/
    fi
  '';

  meta = {
    description = "Unitree Robotics SDK2 for controlling Unitree robots";
    homepage = "https://github.com/unitreerobotics/unitree_sdk2";
    license = lib.licenses.bsd3;
    platforms = lib.platforms.linux;
  };
}
