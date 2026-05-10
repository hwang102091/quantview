"""
매수·매도·중립 시그널 생성기.

매수 조건:
  외인 순매수 3일+ AND RSI<70 AND 퀀트스코어>60
  OR 내부자 매수 $10만+ AND 기관 순매수
매도 조건:
  내부자 대량매도($50만+) AND 공매도 급증(전월비 30%+) AND RSI>75
중립: 나머지
"""
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ── 공개 API ───────────────────────────────────────────────────────────────

def generate_signals(
    stock_data: List[Dict],
    smart_money_data: Dict,
) -> Dict[str, Dict]:
    """
    종목별 매수·매도·중립 시그널 + 칩 텍스트 생성.

    Args:
        stock_data : score_stocks() 또는 run.py watchlist (quant_score 포함).
                     _price_df 필드가 있으면 RSI 계산에 사용.
        smart_money_data : smart_money.fetch() 결과

    Returns:
        {ticker: {signal, chips, rsi, quant_score, ...}}
    """
    form4 = smart_money_data.get("form4") or []
    dataroma = smart_money_data.get("dataroma") or {}

    # 내부자 매수·매도 금액 집계
    insider_buy: Dict[str, float] = {}
    insider_sell: Dict[str, float] = {}
    for row in form4:
        val = row.get("value_usd") or 0.0
        for t in (row.get("tickers") or []):
            if not t:
                continue
            # value > 0 → 매수, value < 0 → 매도로 구분
            if val >= 0:
                insider_buy[t] = insider_buy.get(t, 0) + val
            else:
                insider_sell[t] = insider_sell.get(t, 0) + abs(val)

    # 슈퍼인베스터 신규·확대 티커
    guru_buy: set = {
        h["ticker"]
        for mgr in dataroma.values()
        for h in (mgr.get("holdings") or [])
        if (h.get("recent_activity") or "").strip().lower() in ("buy", "add", "new")
    }

    out: Dict[str, Dict] = {}
    for stock in stock_data:
        ticker = stock.get("ticker", "")
        try:
            out[ticker] = _evaluate(stock, insider_buy, insider_sell, guru_buy)
        except Exception as e:
            log.warning("시그널 산출 실패 %s: %s", ticker, e)
            out[ticker] = {"signal": "neutral", "chips": []}

    buy_n = sum(1 for v in out.values() if v.get("signal") == "buy")
    sell_n = sum(1 for v in out.values() if v.get("signal") == "sell")
    log.info("시그널 완료: 매수=%d 매도=%d 중립=%d", buy_n, sell_n,
             len(out) - buy_n - sell_n)
    return out


# ── run.py 호환 진입점 ─────────────────────────────────────────────────────

def run(watchlist: List[Dict], bundle: Dict[str, Any]) -> Dict[str, dict]:
    """
    기존 run() 인터페이스 유지.
    bundle 에서 price_df / short_ratio 를 watchlist 에 주입한 뒤
    generate_signals() 를 호출한다.
    """
    kr_prices = bundle.get("kr_prices") or {}
    us_prices = bundle.get("us_prices") or {}
    smart_money = bundle.get("smart_money") or {}

    for item in watchlist:
        snap = (kr_prices if item["market"] == "kr" else us_prices).get(item["ticker"], {})
        item["_price_df"] = snap.get("price")
        info = snap.get("info") or {}
        item.setdefault("short_ratio", info.get("shortRatio"))

    return generate_signals(watchlist, smart_money)


# ── 시그널 판정 ───────────────────────────────────────────────────────────

def _evaluate(
    stock: Dict,
    insider_buy: Dict[str, float],
    insider_sell: Dict[str, float],
    guru_tickers: set,
) -> Dict:
    ticker = stock["ticker"]
    quant_score = stock.get("quant_score") or 0.0

    price_df = stock.get("_price_df")
    rsi = _compute_rsi(price_df) if price_df is not None else None

    foreign_days: int = stock.get("foreign_buy_days") or 0
    inst_net = stock.get("inst_net_buy")
    short_surge: Optional[float] = stock.get("short_surge_pct")

    ib_val = insider_buy.get(ticker, 0.0)
    is_val = insider_sell.get(ticker, 0.0)
    is_inst_positive = inst_net is not None and inst_net > 0
    is_guru = ticker in guru_tickers

    chips: List[str] = []
    signal = "neutral"

    # ── 매수 시그널 ────────────────────────────────────────────────────────
    buy_reasons: List[str] = []

    cond_foreign = foreign_days >= 3 and (rsi is None or rsi < 70) and quant_score > 60
    if cond_foreign:
        buy_reasons.append(f"외인 {foreign_days}일 연속 순매수")

    cond_insider = ib_val >= 100_000 and is_inst_positive
    if cond_insider:
        buy_reasons.append(f"내부자 매수 ${ib_val / 1_000:.0f}k")

    if is_guru:
        buy_reasons.append("슈퍼인베스터 신규 편입")

    if buy_reasons:
        signal = "buy"
        chips = buy_reasons

    # ── 매도 시그널 (매수 조건보다 우선) ──────────────────────────────────
    cond_sell_insider = is_val >= 500_000
    cond_sell_short = short_surge is not None and short_surge >= 30
    cond_sell_rsi = rsi is not None and rsi > 75

    if cond_sell_insider and cond_sell_short and cond_sell_rsi:
        signal = "sell"
        chips = []
        chips.append("CEO 대량 매도 경보")
        if cond_sell_short:
            chips.append(f"공매도 {short_surge:.1f}% 급증 주의")
        if rsi is not None:
            chips.append(f"RSI {rsi:.0f} 과열")

    return {
        "signal": signal,
        "chips": chips,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "quant_score": quant_score,
        "foreign_buy_days": foreign_days,
        "insider_buy_usd": ib_val if ib_val > 0 else None,
        "insider_sell_usd": is_val if is_val > 0 else None,
        "is_guru": is_guru,
    }


# ── RSI 계산 ─────────────────────────────────────────────────────────────

def _compute_rsi(price_df, period: int = 14) -> Optional[float]:
    """Wilder EMA 방식 RSI(14)."""
    try:
        close = price_df["Close"]
        if len(close) < period + 1:
            return None
        delta = close.diff().dropna()
        gain = delta.clip(lower=0)
        loss = (-delta.clip(upper=0))
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean().iloc[-1]
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - 100 / (1 + rs))
    except Exception:
        return None
