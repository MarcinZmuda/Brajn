"""
Centralized configuration for Brajn SEO application.
All settings loaded from environment variables.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# === Authentication ===
API_KEY = os.getenv("API_KEY", "")
PANEL_LOGIN = os.getenv("PANEL_LOGIN", "admin")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")

# === S1: SERP Analysis ===
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

# === Cloudflare Browser Rendering ===
CF_BROWSER_RENDERING_URL = os.getenv("CF_BROWSER_RENDERING_URL", "")
CF_BROWSER_RENDERING_TOKEN = os.getenv("CF_BROWSER_RENDERING_TOKEN", "")

# === AI/LLM ===
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# === Firebase ===
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
FIREBASE_CREDS_JSON = os.getenv("FIREBASE_CREDS_JSON", "")

# === Feature Flags ===
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
ENTITY_SEO_ENABLED = os.getenv("ENTITY_SEO_ENABLED", "true").lower() == "true"

# === Limits ===
MAX_CONTENT_SIZE = 30_000       # Max 30KB per page
MAX_TOTAL_CONTENT = 200_000     # Max 200KB total content
SCRAPE_TIMEOUT = 8              # seconds per page
SKIP_DOMAINS = ["bip.", ".pdf", "gov.pl/dana/", "/uploads/files/"]

# === App ===
VERSION = "1.0.0"
APP_NAME = "Brajn SEO"
MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # 32 MB

# === CORS ===
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "*").split(",")
    if o.strip()
]
