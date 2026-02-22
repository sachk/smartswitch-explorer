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
        zstd
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
        xcbutil
        xcbutilcursor
        xcbutilimage
        xcbutilkeysyms
        xcbutilrenderutil
        xcbutilwm
        stdenv.cc.cc.lib
      ];

      ldLibraryPath = pkgs.lib.makeLibraryPath runtimeLibs;

      runGui = pkgs.writeShellApplication {
        name = "smartswitch-explorer-run";
        runtimeInputs = [pkgs.uv];
        text = ''
          unset SOURCE_DATE_EPOCH
          export LD_LIBRARY_PATH=${pkgs.libGL}
          export LD_LIBRARY_PATH=${ldLibraryPath}:''${LD_LIBRARY_PATH:-}
          export QT_QPA_PLATFORM=xcb
          unset QT_PLUGIN_PATH
          unset QML2_IMPORT_PATH

          pyside_plugins="$(uv run python -c 'from PySide6.QtCore import QLibraryInfo; print(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath) or "")')"
          if [ -z "$pyside_plugins" ]; then
            echo "Failed to locate Qt plugins path from PySide6." >&2
            exit 1
          fi
          export QT_PLUGIN_PATH="$pyside_plugins"
          export QT_QPA_PLATFORM_PLUGIN_PATH="$pyside_plugins/platforms"

          exec uv run smartswitch-explorer "$@"
        '';
      };
    in {
      packages.default = runGui;
      apps.default = {
        type = "app";
        program = "${runGui}/bin/smartswitch-explorer-run";
      };

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
          export LD_LIBRARY_PATH=${ldLibraryPath}:''${LD_LIBRARY_PATH:-}
          export QT_QPA_PLATFORM=xcb
          unset QT_PLUGIN_PATH
          unset QML2_IMPORT_PATH

          echo "SmartSwitch Explorer dev shell ready"
          echo "Run: uv run smartswitch-explorer"
          echo "Or:  nix run"
        '';
      };
    });
}
