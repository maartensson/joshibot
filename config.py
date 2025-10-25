from dataclasses import dataclass
import json, os

@dataclass
class Settings:
    telegram_bot_token: str
    chat_id: int
    owner_id: int
    thread_id_bounceland: int
    thread_id_meal: int
    meal_file: str
    meal_message_file: str
    bounce_file: str
    bounce_message_file: str
    bounce_csv: str
    update_interval: float
    scheduler_timezone: str
    meal_poll_hour: int
    meal_poll_minute: int
    meal_poll_day: str


with open(os.getenv("CONFIG_FILE")) as f:
    data = json.load(f)
    settings = Settings(**data)


print(settings.telegram_bot_token)
print(settings.scheduler_timezone)
print(settings.meal_poll_day)


if settings.meal_poll_day == "sat":
    print("Meal poll runs on Saturday!")
