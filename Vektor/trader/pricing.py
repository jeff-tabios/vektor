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
        daily = yf.Ticker(symbol).history(period="5d")
        if not daily.empty:
            return round(float(daily["Close"].iloc[-1]), 4)
    except Exception as e:
        print(f"Price fetch error [{asset}]: {e}")
    return None


def get_prices(assets: list) -> dict:
    return {asset: get_price(asset) for asset in assets}
