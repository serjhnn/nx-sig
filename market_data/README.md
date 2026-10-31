# Market data

Saved price bars, kept apart from `data/` (which is
gitignored and holds the app's own files).

| File | What |
|---|---|
| `MRVU_5m_2026-09-22_2026-10-22.csv` | MRVU 5-minute bars, Sep 22 - Oct 22 2026, pre and post market included |
| `fetch_yahoo_5m.py` | Script that made it |

Columns: `datetime_et` (bar start, New York time),
`timestamp_utc` (unix seconds), `session` (`pre` before
9:30, `regular` 9:30-16:00, `post` after 16:00 ET),
`open`, `high`, `low`, `close`, `volume`.

Pre and post market trading in MRVU is thin, so 5-minute
slots with no trades have no row. Yahoo doesn't give
volume outside regular hours, so `volume` is 0 on every
pre and post bar; the prices are real.

To refresh (Yahoo keeps 5-minute bars for about 60
days, one month per call):

```bash
python market_data/fetch_yahoo_5m.py MRVU
```
