{
  description = "bounceland telegram bot joshi";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {self, nixpkgs, flake-utils, ...}:
  flake-utils.lib.eachDefaultSystem (system: let 
    pkgs = nixpkgs.legacyPackages.${system};
  in {
    packages.default = pkgs.python3Packages.buildPythonPackage {
      pname = "bounceland";
      version = "0.0.1";
      src = ./.;
      format = "setuptools";
      propagatedBuildInputs = with pkgs.python3Packages; [
        python-telegram-bot
        apscheduler
      ];
    };

    apps.default = {
      type = "app";
      program = "${self.packages.${system}.default}/bin/bot";
    };
  }) // {
    nixosModules.default = {config, lib, pkgs, ...}: let
      myPkg = self.packages.${pkgs.system}.default;
    in{
      options.services.joshibot = {
        enable = lib.mkEnableOption "Enable joshibot service";

        configFile = lib.mkOption {
          type = lib.types.path;
          description = "the path to the environment file";
        };
      };

      config = lib.mkIf config.services.joshibot.enable {
        systemd.services.joshibot= {
          description = "Joshibot Webserver";
          wantedBy = ["multi-user.target"];
          after = ["network.target"];
          serviceConfig = {
            ExecStart = "${pkgs.python3}/bin/python ${myPkg}/bin/config.py";
            Restart = "always";
            Type = "simple";
            DynamicUser = "yes";
            LoadCredential = [
              "config.json:${ toString config.services.joshibot.configFile }"
            ];
            Environment = [
              "CONFIG_FILE=/run/credentials/%n/config.json"
            ];
          };
        };
      };
    };
  };
}


