"""Self-check: fetch_donki.main() keeps good endpoints when one fails. Run: python -m unittest tools/test_fetch_donki.py -v"""
import contextlib
import io
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_donki  # noqa: E402

SCHEMA = (TOOLS.parent / "db" / "schema.sql").read_text(encoding="utf-8")
CREATE = re.search(r"CREATE TABLE IF NOT EXISTS solar_events \(.*?\n\);", SCHEMA, re.S).group(0)
RECORDS = {"SEP": {"sepID": "s1", "eventTime": "2026-11-01T01:00Z"},
           "CME": {"activityID": "c1", "startTime": "2026-11-02T02:00Z"}}


class FetchDonkiTest(unittest.TestCase):
    def run_main(self, fake_fetch):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            conn = sqlite3.connect(db)
            conn.execute(CREATE)
            conn.commit()
            conn.close()
            with mock.patch.object(fetch_donki, "fetch", fake_fetch), \
                    contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                code = fetch_donki.main(["--days", "1", "--db", str(db)])
            conn = sqlite3.connect(db)
            count = conn.execute("SELECT COUNT(*) FROM solar_events").fetchone()[0]
            conn.close()
            return code, count

    def test_one_endpoint_fails(self):
        def fake(kind, first, last, key):
            if kind == "CME":
                raise fetch_donki.FetchError("NASA DONKI CME returned HTTP 404. Check the API key.")
            return [RECORDS[kind]]
        self.assertEqual(self.run_main(fake), (0, 1))

    def test_all_endpoints_fail(self):
        def fake(kind, first, last, key):
            raise fetch_donki.FetchError(f"NASA DONKI {kind} returned HTTP 404.")
        self.assertEqual(self.run_main(fake), (1, 0))


    def test_falls_back_to_second_address(self):
        calls = []
        def fake_from(base, kind, first, last, key):
            calls.append(base)
            if base == fetch_donki.BASE_URLS[0]:
                raise fetch_donki.FetchError("NASA DONKI CME sent a response that is not JSON.")
            return [RECORDS[kind]]
        with mock.patch.object(fetch_donki, "fetch_from", fake_from):
            self.assertEqual(fetch_donki.fetch("CME", None, None, "k"), [RECORDS["CME"]])
        self.assertEqual(calls, list(fetch_donki.BASE_URLS))

    def test_all_addresses_fail(self):
        def fake_from(base, kind, first, last, key):
            raise fetch_donki.FetchError(f"fail {base}")
        with mock.patch.object(fetch_donki, "fetch_from", fake_from):
            with self.assertRaisesRegex(fetch_donki.FetchError, "api.nasa.gov"):
                fetch_donki.fetch("CME", None, None, "k")


    def test_real_sep_is_context_only(self):
        row = fetch_donki.to_row("SEP", RECORDS["SEP"])
        self.assertEqual((row["event_type"], row["dose_relevant"]), ("SEP", 0))


    def test_api_key_only_goes_to_api_nasa_gov(self):
        from datetime import date
        urls = []
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        def fake_urlopen(request, timeout=None):
            urls.append(request.full_url)
            return Resp(b"[]")
        with mock.patch.object(fetch_donki.urllib.request, "urlopen", fake_urlopen):
            for base in fetch_donki.BASE_URLS:
                fetch_donki.fetch_from(base, "CME", date(2026, 11, 1), date(2026, 11, 2), "SECRET")
        self.assertNotIn("SECRET", urls[0])
        self.assertIn("api_key=SECRET", urls[1])


if __name__ == "__main__":
    unittest.main()
