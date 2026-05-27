from typing import Optional
from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder

PAPER_PORT = 7497   # TWS paper trading
LIVE_PORT  = 7496   # TWS live trading (never use until ready)
HOST       = "127.0.0.1"
CLIENT_ID  = 1


def connect(paper: bool = True) -> Optional[IB]:
    ib = IB()
    port = PAPER_PORT if paper else LIVE_PORT
    try:
        ib.connect(HOST, port, clientId=CLIENT_ID, timeout=10)
        print(f"IBKR connected ({'paper' if paper else 'LIVE'}) on port {port}")
        return ib
    except Exception as e:
        print(f"IBKR connection failed: {e}")
        print("Make sure TWS is running and API connections are enabled.")
        return None


def disconnect(ib: IB):
    try:
        ib.disconnect()
    except Exception:
        pass


def get_portfolio_value(ib: IB) -> float:
    try:
        for item in ib.accountSummary():
            if item.tag == "NetLiquidation":
                return float(item.value)
    except Exception:
        pass
    return 100_000.0


def calculate_quantity(entry_price: float, stop_loss: Optional[float],
                       portfolio_value: float, risk_pct: float = 0.02) -> int:
    if not stop_loss or stop_loss <= 0 or entry_price <= 0:
        return 1
    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share == 0:
        return 1
    max_risk = portfolio_value * risk_pct
    return max(1, int(max_risk / risk_per_share))


def place_bracket_order(ib: IB, symbol: str, action: str,
                        quantity: int, stop_loss: float, take_profit: float) -> Optional[list]:
    try:
        contract = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)

        exit_action = "SELL" if action == "BUY" else "BUY"

        parent = MarketOrder(action, quantity)
        parent.orderId  = ib.client.getReqId()
        parent.transmit = False

        tp_order = LimitOrder(exit_action, quantity, round(take_profit, 2))
        tp_order.parentId = parent.orderId
        tp_order.transmit = False

        sl_order = StopOrder(exit_action, quantity, round(stop_loss, 2))
        sl_order.parentId = parent.orderId
        sl_order.transmit = True  # transmits all three

        trades = []
        for order in [parent, tp_order, sl_order]:
            trade = ib.placeOrder(contract, order)
            trades.append(trade)

        ib.sleep(1)
        order_id = parent.orderId
        print(f"Bracket order placed: {action} {quantity}x {symbol} | SL={stop_loss} TP={take_profit} | orderId={order_id}")
        return trades

    except Exception as e:
        print(f"Order placement failed: {e}")
        return None


def execute_trade(asset: str, decision: str, entry_price: float,
                  stop_loss: Optional[float], take_profit: Optional[float],
                  paper: bool = True) -> Optional[int]:
    """
    Full flow: connect → size position → place bracket order → disconnect.
    Returns the parent order ID or None if skipped/failed.
    """
    if decision == "HOLD":
        print("IBKR: HOLD — no order placed")
        return None

    if not stop_loss or not take_profit:
        print("IBKR: missing stop_loss or take_profit — skipping order")
        return None

    ib = connect(paper=paper)
    if not ib:
        return None

    try:
        portfolio_value = get_portfolio_value(ib)
        quantity = calculate_quantity(entry_price, stop_loss, portfolio_value)
        print(f"IBKR: portfolio=${portfolio_value:,.0f} | sizing {quantity} shares (2% risk)")

        trades = place_bracket_order(ib, asset, decision, quantity, stop_loss, take_profit)
        if trades:
            return trades[0].order.orderId
        return None
    finally:
        disconnect(ib)
