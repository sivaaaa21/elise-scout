"""Check which API keys are loaded from .env. Values are not printed."""
from dotenv import load_dotenv
import os

load_dotenv()

KEYS = [
    "CENSUS_API_KEY",
    "NEWSAPI_KEY",
    "OPENWEATHER_API_KEY",
    "EMAIL_LLM_PROVIDER",
    "OPENAI_API_KEY",
]

print()
for k in KEYS:
    v = os.getenv(k)
    if v:
        print(f"  {k:<25} set  ({len(v)} chars, starts with {v[:3]}...)")
    else:
        print(f"  {k:<25} missing")
print()
