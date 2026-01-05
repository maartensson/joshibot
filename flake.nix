{
  description = "bounceland telegram bot joshi";

  outputs = { ... } : {
    nixosModules.default = {config, lib, pkgs, ...}: {
      options.services.joshibot = {
        enable = lib.mkEnableOption "Enable joshibot service";

        configFile = lib.mkOption {
          type = lib.types.str;
          description = "the path to the environment file";
        };
      };

      config = lib.mkIf config.services.joshibot.enable {
        systemd.services.joshibot = {
          description = "Joshibot Webserver";
          wantedBy = ["multi-user.target"];
          after = ["network.target"];
          serviceConfig = let 
            python = pkgs.python3.withPackages (ps: with ps; [
              python-telegram-bot
              apscheduler
            ]);
          in {
            ExecStart = "${python}/bin/python ${ ./bot.py }";
            Restart = "always";
            Type = "simple";
            DynamicUser = "yes";
            StateDirectory = "joshibot";
            LoadCredential = [
              "config.json:${ toString config.services.joshibot.configFile }"
            ];
            Environment = [
              "CONFIG_FILE=/run/credentials/%n/config.json"

              "MEAL_FILE=/var/lib/joshibot/polls_meal.json"
              "MEAL_MESSAGE_FILE=/var/lib/joshibot/meal_message_id.json"
              "BOUNCE_FILE=/var/lib/joshibot/bounceland.json"
              "BOUNCE_MESSAGE_FILE=/var/lib/joshibot/bounceland_message_id.json"
              "BOUNCE_CSV=/var/lib/joshibot/bounceland_data.csv"
            ];
          };
        };
      };
    };
  };
}
