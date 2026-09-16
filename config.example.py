import os

TESTING = True

_token = "token"
_test_token = "test-token"
TOKEN = _test_token if TESTING else _token

_db_url = "dsn"
_test_db_url = "dsn"
DB_URL = _test_db_url if TESTING else _db_url

_prefix = ",,"
_test_prefix = "t,"
PREFIX = _test_prefix if TESTING else _prefix

os.environ["JISHAKU_NO_UNDERSCORE"] = "True"
os.environ["JISHAKU_NO_DM_TRACEBACK"] = "True"

# voice recap module
_anthropic_key = "key"
_test_anthropic_key = "key"
ANTHROPIC_KEY = _test_anthropic_key if TESTING else _anthropic_key

# cloudflare workers ai (free tier) carries recaps while TESTING; anthropic in prod
SUMMARY_PROVIDER = "cloudflare" if TESTING else "anthropic"
_cf_ai_token = "token"
_test_cf_ai_token = "token"
CF_AI_TOKEN = _test_cf_ai_token if TESTING else _cf_ai_token
CF_ACCOUNT_ID = "account-id"
CF_AI_MODEL = "@cf/meta/llama-3.1-8b-instruct"

RECAP_MODEL = "claude-haiku-4-5-20251001"
WHISPER_MODEL = "small"
WHISPER_THREADS = 2
MODELS_DIR = "./models"

SKU_TIER_1 = 0  # set after Premium Apps SKU setup — CONFIRM token tracked in VOICE-RECAP-PLAN.md and HUMAN-TODO.md
SKU_TIER_2 = 0

REPORT_CHANNEL_ID = 0
PRIVACY_URL = "https://privacy.sprok.umbleh.dev"
TERMS_URL = "https://terms.sprok.umbleh.dev"

# help: prefix help can't be ephemeral, so it goes to DMs ("dm") or a self-deleting post ("temp")
HELP_PREFIX_MODE = "dm"
HELP_DM_NOTE_SECONDS = 10  # the "Sent to your DMs!" note
HELP_TEMP_SECONDS = 60  # in-channel help, when DMs are closed or the mode is "temp"
DASHBOARD_URL = "https://sprok.umbleh.dev"  # shown in help to Manage Server members; empty hides it

# internal api for the dashboard: aiohttp on the private spork-internal network only; an empty token keeps it off
_api_token = "token"
_test_api_token = ""
API_TOKEN = _test_api_token if TESTING else _api_token
API_HOST = "0.0.0.0"
API_PORT = 8080

# activity counts (numbers only, never message text) behind the developer insights; the flush interval in seconds
STATS_FLUSH_SECONDS = 60

# developer tools: the only ids that can see or run /dev (empty fails closed), and a channel that gets one line per use
DEV_OWNER_IDS = {int(value) for value in os.environ.get("DEV_OWNER_IDS", "739219467455823921").split(",") if value.strip()}
DEV_LOG_CHANNEL_ID = 0
