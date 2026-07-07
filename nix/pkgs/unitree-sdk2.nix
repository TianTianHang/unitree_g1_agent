{ pkgs, lib, stdenv }:

stdenv.mkDerivation {
  pname = "unitree-sdk2";
  version = "7740f8b67e386ab09c3b333187fd5f8582a75ddc";

  src = pkgs.fetchurl {
    url = "https://gh-proxy.com/https://github.com/unitreerobotics/unitree_sdk2/archive/7740f8b67e386ab09c3b333187fd5f8582a75ddc.tar.gz";
    sha256 = "0b28e58a3c5ffc3dfd7403b2d3aafe066e4452ec907a4c48308e1fae985c7cb8";
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
