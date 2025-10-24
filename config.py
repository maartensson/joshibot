import json

with open(os.getenv('CONFIG_FILE')) as f:
    settings = json.load(f)

print(settings)
