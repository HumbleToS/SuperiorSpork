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

RECAP_MODEL = "claude-haiku-4-5-20251001"
WHISPER_MODEL = "small"
WHISPER_THREADS = 2
MODELS_DIR = "./models"

SKU_TIER_1 = 0  # set after Premium Apps SKU setup — CONFIRM token tracked in VOICE-RECAP-PLAN.md and HUMAN-TODO.md
SKU_TIER_2 = 0

REPORT_CHANNEL_ID = 0
PRIVACY_URL = "https://example.com/privacy"  # hosted policy is a HUMAN-TODO
TERMS_URL = "https://example.com/terms"
