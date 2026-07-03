"""
Shared pytest setup. Makes app.py and matching.py importable regardless of
where pytest is invoked from (adds the app/ directory, one level up from
this tests/ folder, to sys.path).

Nothing else here needs mocking to import app.py / matching.py: both modules
read Supabase/API credentials via os.environ.get(...) at module level, which
returns None rather than raising if a var is missing, and app.py calls
load_dotenv() itself. As long as a real .env file exists in app/ (it does,
for local dev), imports succeed. If .env is ever missing, imports still
succeed -- individual tests just shouldn't call anything that makes a live
network request (none of the Phase 1 tests do).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
