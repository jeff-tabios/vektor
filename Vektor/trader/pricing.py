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
        ticker = yf.Ticker(symbol)
        # try live 1m data first
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            price = round(float(hist["Close"].iloc[-1]), 4)
            # sanity check — fall back to daily close if price looks wrong
            daily = ticker.history(period="5d")
            if not daily.empty:
                last_close = round(float(daily["Close"].iloc[-1]), 4)
                # if 1m price is more than 5% away from last close, use daily
                if abs(price - last_close) / last_close > 0.05:
                    print(f"Price sanity check failed ({price} vs {last_close}), using daily close")
                    return last_close
            return price
        # fallback to daily
        daily = ticker.history(period="5d")
        if not daily.empty:
            return round(float(daily["Close"].iloc[-1]), 4)
    except Exception as e:
        print(f"Price fetch error [{asset}]: {e}")
    return None


def get_prices(assets: list) -> dict:
    return {asset: get_price(asset) for asset in assets}
