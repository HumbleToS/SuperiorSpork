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
