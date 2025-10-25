{
  description = "bounceland telegram bot joshi";

  outputs = { ... } : {
    nixosModules.default = {config, lib, pkgs, ...}: {
      options.services.joshibot = {
        enable = lib.mkEnableOption "Enable joshibot service";

        configFile = lib.mkOption {
          type = lib.types.path;
          description = "the path to the environment file";
        };
      };

      config = lib.mkIf config.services.joshibot.enable {
        systemd.services.joshibot = let 
          python = pkgs.python3.withPackages (ps: with ps; [
            python-telegram-bot
            apscheduler
          ]);
        in {
          description = "Joshibot Webserver";
          wantedBy = ["multi-user.target"];
          after = ["network.target"];
          serviceConfig = {
            ExecStart = "${python}/bin/python ${ ./bot.py }";
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
