"""Global settings. Every research choice lives here and nowhere else."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "results"

# Binance sources (public files, no API key needed)
BASE_URL = "https://data.binance.vision"
S3_LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
STABLES = {"USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD", "USDE", "EUR", "GBP", "AEUR"}

# Research calendar
OOS_START = pd.Timestamp("2022-07-01", tz="UTC")      # out-of-sample start (OI history begins late 2021)
LOCKBOX_START = pd.Timestamp("2026-01-01", tz="UTC")  # lockbox, opened ONCE at the very end

# Universe and model
TOP_N = 100            # tradable perps per day, ranked by volume
MIN_AGE = 35           # days of continuous listing before a perp can enter (longer than the 30-day windows)
PURGE, EMBARGO = 2, 7  # in days
ALPHAS = [1e-2, 1e-1, 1.0, 10.0, 100.0]  # ridge penalty grid (scaled by n)

# Execution and costs
FEE = 0.0005           # standard-user taker fee on USDⓈ-M perps, 5 bps
HALF_SPREAD = 0.0002   # assumed average half-spread, 2 bps
IMPACT_Y = 0.7         # square-root impact constant
AUM = 1_000_000        # book size in USD (drives the impact cost)
ANN = 365              # crypto trades every day