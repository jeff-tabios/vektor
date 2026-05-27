from typing import Optional
import yfinance as yf

SYMBOL_MAP = {
    "SPY":  "SPY",
    "QQQ":  "QQQ",
    "NVDA": "NVDA",
    "TSLA": "TSLA",
    "AAPL": "AAPL",
    "AMD":  "AMD",
    "BTC":  "BTC-USD",
    "ETH":  "ETH-USD",
}


def get_price(asset: str) -> Optional[float]:
    symbol = SYMBOL_MAP.get(asset, asset)
    try:
        hist = yf.Ticker(symbol).history(period="1d", interval="1m")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 4)
    except Exception as e:
        print(f"Price fetch error [{asset}]: {e}")
    return None


def get_prices(assets: list) -> dict:
    return {asset: get_price(asset) for asset in assets}
