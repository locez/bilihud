{
  autoPatchelfHook,
  cmake,
  kdePackages,
  lib,
  ninja,
  pkg-config,
  python313Packages,
  qt6,
  wayland,
  blivedmSrc,
}:

let
  project = (builtins.fromTOML (builtins.readFile ../../pyproject.toml)).project;
in
python313Packages.buildPythonApplication {
  pname = project.name;
  inherit (project) version;
  pyproject = true;

  src = lib.fileset.toSource {
    root = ../..;
    fileset = lib.fileset.unions [
      ../../CMakeLists.txt
      ../../LICENSE
      ../../README.md
      ../../bilihud.desktop
      ../../pyproject.toml
      ../../src
    ];
  };

  postPatch = ''
    mkdir -p vendor/blivedm
    cp -R --no-preserve=mode ${blivedmSrc}/blivedm vendor/blivedm/
  '';

  build-system = [ python313Packages.scikit-build-core ];

  nativeBuildInputs = [
    autoPatchelfHook
    cmake
    ninja
    pkg-config
    qt6.wrapQtAppsHook
  ];

  buildInputs = [
    kdePackages.layer-shell-qt
    qt6.qtbase
    qt6.qtmultimedia
    qt6.qtsvg
    qt6.qtwayland
    wayland
  ];

  dependencies = with python313Packages; [
    aiohttp
    brotli
    keyring
    pillow
    pure-protobuf
    pyqt6
    qasync
    qrcode
  ];

  dontUseCmakeConfigure = true;
  # Qt's setup hook supplies cmake.args on the CLI, overriding pyproject.toml.
  pypaBuildFlags = [
    "--config-setting=cmake.define.BILIHUD_INSTALL_DIR=bilihud"
    "--config-setting=cmake.define.BILIHUD_LAYER_SHELL=ON"
  ];

  # Let the Python application wrapper carry Qt's plugin and platform paths.
  dontWrapQtApps = true;
  makeWrapperArgs = [ "\${qtWrapperArgs[@]}" ];

  postInstall = ''
    install -Dm644 bilihud.desktop "$out/share/applications/bilihud.desktop"
    install -Dm644 src/bilihud/assets/icon.png \
      "$out/share/icons/hicolor/256x256/apps/bilihud.png"

    test -f "$out/${python313Packages.python.sitePackages}/bilihud/libbili-layer.so"
  '';

  pythonImportsCheck = [
    "bilihud"
    "blivedm"
    "PyQt6.QtMultimedia"
    "PyQt6.QtSvg"
  ];

  strictDeps = true;

  meta = {
    inherit (project) description;
    homepage = project.urls.homepage;
    license = lib.licenses.mit;
    mainProgram = "bilihud";
    platforms = lib.platforms.linux;
  };
}
