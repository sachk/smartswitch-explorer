{
  description = "SmartSwitch Explorer Python venv development shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    utils,
    ...
  }:
    utils.lib.eachDefaultSystem (system: let
      pkgs = import nixpkgs {inherit system;};
      pythonPackages = pkgs.python3Packages;

      runtimeLibs = with pkgs; [
        libGL
        zlib
        libxkbcommon
        glib
        dbus
        fontconfig
        freetype
        libx11
        libxcb
        libxext
        libxrender
        libxi
        libxrandr
        libxcursor
        libsm
        libice
        stdenv.cc.cc.lib
      ];
    in {
      devShells.default = pkgs.mkShell {
        name = "smartswitch-explorer";
        venvDir = "./.venv";

        buildInputs = [
          pythonPackages.python
          pythonPackages.venvShellHook
          pkgs.uv
          pkgs.git
          pkgs.pkg-config
        ] ++ runtimeLibs;

        postVenvCreation = ''
          unset SOURCE_DATE_EPOCH
          # sync project dependencies (including dev group) into .venv
          uv sync
        '';

        postShellHook = ''
          # allow wheel installs
          unset SOURCE_DATE_EPOCH

          # requested explicit export
          export LD_LIBRARY_PATH=${pkgs.libGL}
          # full runtime search path for Qt/OpenGL/X11 libs
          export LD_LIBRARY_PATH=${pkgs.lib.makeLibraryPath runtimeLibs}:''${LD_LIBRARY_PATH:-}

          echo "SmartSwitch Explorer dev shell ready"
          echo "Run: uv run smartswitch-explorer"
        '';
      };
    });
}
