{
  description = "BiliHUD - Bilibili danmaku overlay";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    # Keep this revision aligned with the vendor/blivedm gitlink. GitHub source
    # archives do not contain submodule contents, so the package copies it in.
    blivedm = {
      url = "github:xfgryujk/blivedm/93530bcc20de8a67f8d0ee4788096da2480b8a10";
      flake = false;
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      blivedm,
      ...
    }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      mkBilihud =
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        pkgs.callPackage ./packaging/nix/package.nix { blivedmSrc = blivedm; };
    in
    {
      packages = forAllSystems (
        system:
        let
          bilihud = mkBilihud system;
        in
        {
          inherit bilihud;
          default = bilihud;
        }
      );

      apps = forAllSystems (
        system:
        let
          bilihudApp = {
            type = "app";
            program = nixpkgs.lib.getExe self.packages.${system}.bilihud;
            meta.description = "Launch BiliHUD, a Bilibili danmaku overlay";
          };
        in
        {
          bilihud = bilihudApp;
          default = bilihudApp;
        }
      );

      overlays.default = final: _previous: {
        bilihud = final.callPackage ./packaging/nix/package.nix { blivedmSrc = blivedm; };
      };
    };
}
