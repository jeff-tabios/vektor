from datetime import datetime
import yfinance as yf
import pandas as pd

ASSETS = {
    "SPY":  "SPY",
    "QQQ":  "QQQ",
    "NVDA": "NVDA",
    "TSLA": "TSLA",
    "AAPL": "AAPL",
    "AMD":  "AMD",
}


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return float((100 - 100 / (1 + rs)).iloc[-1])


def _macd_signal(close: pd.Series) -> str:
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd  = ema12 - ema26
    sig   = macd.ewm(span=9).mean()
    if macd.iloc[-1] > sig.iloc[-1] and macd.iloc[-2] <= sig.iloc[-2]:
        return "bullish crossover"
    if macd.iloc[-1] < sig.iloc[-1] and macd.iloc[-2] >= sig.iloc[-2]:
        return "bearish crossover"
    return "bullish" if macd.iloc[-1] > sig.iloc[-1] else "bearish"


def _bb_position(close: pd.Series) -> str:
    sma  = close.rolling(20).mean()
    std  = close.rolling(20).std()
    if close.iloc[-1] > (sma + 2 * std).iloc[-1]:
        return "above upper band (overbought)"
    if close.iloc[-1] < (sma - 2 * std).iloc[-1]:
        return "below lower band (oversold)"
    return "within bands"


def fetch_market_data() -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    chunks = []

    try:
        vix_close = yf.Ticker("^VIX").history(period="5d")["Close"]
        vix_now   = float(vix_close.iloc[-1])
        vix_5d    = ((vix_now / float(vix_close.iloc[0])) - 1) * 100
        vix_label = "high fear" if vix_now > 30 else "elevated fear" if vix_now > 20 else "low fear"
        vix_text  = f"VIX: {vix_now:.2f} ({vix_5d:+.1f}% 5D) — {vix_label}"
    except Exception as e:
        vix_text = f"VIX: unavailable ({e})"

    for symbol, asset in ASSETS.items():
        try:
            hist   = yf.Ticker(symbol).history(period="60d")
            if hist.empty or len(hist) < 20:
                continue

            close  = hist["Close"]
            volume = hist["Volume"]
            price  = float(close.iloc[-1])
            ma20   = float(close.rolling(20).mean().iloc[-1])
            ma50   = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else ma20
            rsi    = _rsi(close)
            macd   = _macd_signal(close)
            bb     = _bb_position(close)
            vol_r  = float(volume.iloc[-1] / volume.rolling(20).mean().iloc[-1])
            d1     = ((price / float(close.iloc[-2])) - 1) * 100
            d5     = ((price / float(close.iloc[-5])) - 1) * 100
            d20    = ((price / float(close.iloc[-20])) - 1) * 100
            trend  = "uptrend" if price > ma20 > ma50 else "downtrend" if price < ma20 < ma50 else "mixed"
            rsi_lbl = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"
            vol_lbl = "high" if vol_r > 1.5 else "low" if vol_r < 0.7 else "normal"

            text = (
                f"Market data for {symbol} as of {today}:\n"
                f"Price: ${price:.2f} | 1D: {d1:+.2f}% | 5D: {d5:+.2f}% | 20D: {d20:+.2f}%\n"
                f"Trend: {trend} | MA20: ${ma20:.2f} | MA50: ${ma50:.2f}\n"
                f"RSI(14): {rsi:.1f} ({rsi_lbl})\n"
                f"MACD: {macd}\n"
                f"Bollinger Bands: {bb}\n"
                f"Volume: {vol_r:.1f}x average ({vol_lbl} activity)\n"
                f"{vix_text}"
            )

            chunks.append({
                "text":       text,
                "source":     "market_data",
                "source_url": f"market_data_{symbol}_{today}",
                "asset":      asset,
            })
        except Exception as e:
            print(f"market_data error [{symbol}]: {e}")

    return chunks
