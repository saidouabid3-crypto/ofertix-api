import os
import requests
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Get API key from .env
apikey = os.getenv("ZENROWS_API_KEY")

print("API KEY:", apikey)
print("LENGTH:", len(apikey) if apikey else "NONE")

# ZenRows request
params = {
    "url": "https://www.amazon.es/",
    "apikey": apikey,
    "js_render": "true",
    "premium_proxy": "true"
}

try:

    response = requests.get(
        "https://api.zenrows.com/v1/",
        params=params,
        timeout=90
    )

    print("STATUS:", response.status_code)

    print(response.text[:1000])

except Exception as e:

    print("ERROR:", e)