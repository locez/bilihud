{
  description = "BiliHUD - Bilibili danmaku overlay";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    blivedm = {
      url = "github:xfgryujk/blivedm";
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
      # Nix packages follow the revision selected by the flake input instead
      # of maintaining a second release-version source of truth.
      revision = self.shortRev or self.dirtyShortRev or "unknown";
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      mkBilihud =
        pkgs:
        pkgs.callPackage ./packaging/nix/package.nix {
          inherit revision;
          blivedmSrc = blivedm;
        };
      overlay = final: _previous: {
        bilihud = mkBilihud final;
      };
    in
    {
      overlays.default = overlay;

      packages = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          bilihud = mkBilihud pkgs;
        in
        {
          inherit bilihud;
          default = bilihud;
        }
      );

      apps = forAllSystems (system: {
        bilihud = {
          type = "app";
          program = nixpkgs.lib.getExe self.packages.${system}.bilihud;
          meta = {
            description = self.packages.${system}.bilihud.meta.description;
          };
        };
        default = self.apps.${system}.bilihud;
      });

      checks = forAllSystems (system: {
        package = self.packages.${system}.bilihud;
      });

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.alejandra);
    };
}
