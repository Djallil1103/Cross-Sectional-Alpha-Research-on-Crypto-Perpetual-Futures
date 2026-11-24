"""Brick 1. Download hourly klines, funding and open interest for EVERY USDT perp, delisted ones included."""


import io
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree as ET

import pandas as pd
import requests
from tqdm import tqdm

from src.config import BASE_URL, RAW, S3_LIST, STABLES

NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
PREFIX = {
    "klines": "data/futures/um/monthly/klines/{s}/1h/",
    "funding": "data/futures/um/monthly/fundingRate/{s}/",
    "metrics": "data/futures/um/daily/metrics/{s}/",
}
_local = threading.local()


def session() -> requests.Session:
    """One HTTP session per thread, so connections are reused (keep-alive)."""
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def _s3(prefix, marker=None, delimiter=None):
    params = {"prefix": prefix}
    if marker:
        params["marker"] = marker
    if delimiter:
        params["delimiter"] = delimiter
    r = session().get(S3_LIST, params=params, timeout=30)
    r.raise_for_status()
    return ET.fromstring(r.content)


def list_symbols():
    """List the folders of the bucket: that is every symbol that ever existed."""
    out, marker = [], None
    while True:
        root = _s3("data/futures/um/monthly/klines/", marker, delimiter="/")
        out += [p.find("s3:Prefix", NS).text.split("/")[-2] for p in root.findall("s3:CommonPrefixes", NS)]
        if root.find("s3:IsTruncated", NS).text != "true":
            break
        marker = root.find("s3:NextMarker", NS).text
    # USDT perps only: no dated contracts (BTCUSDT_230331), no stablecoins
    return sorted(s for s in out if s.endswith("USDT") and "_" not in s and s[:-4] not in STABLES)


def list_keys(prefix):
    """List the .zip files under a prefix (pages of 1000)."""
    keys, marker = [], None
    while True:
        root = _s3(prefix, marker)
        page = [c.find("s3:Key", NS).text for c in root.findall("s3:Contents", NS)]
        keys += [k for k in page if k.endswith(".zip")]
        if root.find("s3:IsTruncated", NS).text != "true" or not page:
            return keys
        marker = page[-1]


def fetch(key) -> bytes:
    r = session().get(f"{BASE_URL}/{key}", timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        return z.read(z.namelist()[0])


KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
         "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def parse_klines(raw):
    df = pd.read_csv(io.BytesIO(raw), header=None, names=KCOLS)
    t = pd.to_numeric(df["open_time"], errors="coerce")      # the header row, when present, becomes NaN
    df, t = df[t.notna()], t[t.notna()].astype("int64")
    t = t.where(t < 10**14, t // 1000)                      # safety net: microseconds -> milliseconds
    return pd.DataFrame({
        "ts": pd.to_datetime(t.to_numpy(), unit="ms", utc=True),   # bar OPEN time
        "close": pd.to_numeric(df["close"]).to_numpy(),
        "qv": pd.to_numeric(df["quote_volume"]).to_numpy(),        # volume in USDT
    })


def parse_funding(raw):
    df = pd.read_csv(io.BytesIO(raw))   # columns: calc_time, funding_interval_hours, last_funding_rate
    return pd.DataFrame({
        "ts": pd.to_datetime(pd.to_numeric(df["calc_time"]).to_numpy(), unit="ms", utc=True),
        "funding": pd.to_numeric(df["last_funding_rate"]).to_numpy(),
    })


def parse_metrics(raw):
    df = pd.read_csv(io.BytesIO(raw), usecols=["create_time", "sum_open_interest_value"])
    df = df.iloc[[-1]]                  # keep only the last point of the day (around midnight)
    return pd.DataFrame({
        "ts": pd.to_datetime(df["create_time"].to_numpy(), utc=True),
        "oi": pd.to_numeric(df["sum_open_interest_value"]).to_numpy(),   # OI in USDT
    })


PARSERS = {"klines": parse_klines, "funding": parse_funding, "metrics": parse_metrics}


def _safe(kind, key):
    try:
        return PARSERS[kind](fetch(key))
    except Exception as e:  # one corrupt file must not kill three hours of downloading
        print(f"[skip] {key}: {e}")
        return None


def download(kind, symbols, workers=48):
    out = RAW / kind
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(workers) as ex:
        for s in tqdm(symbols, desc=kind):
            path = out / f"{s}.parquet"
            if path.exists():
                continue
            keys = list_keys(PREFIX[kind].format(s=s))
            frames = [f for f in ex.map(lambda k: _safe(kind, k), keys) if f is not None]
            if frames:
                df = pd.concat(frames).drop_duplicates("ts").sort_values("ts")
                df.to_parquet(path, index=False)


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    symbols = list_symbols()
    print(f"{len(symbols)} USDT perps found (delisted included)")
    pd.Series(symbols, name="symbol").to_csv(RAW / "symbols.csv", index=False)
    for kind in ["klines", "funding", "metrics"]:   # metrics last, it is by far the longest
        download(kind, symbols)