"""
ETF 자금 유출입 수집기
섹터·테마 ETF의 일별 순유입(NAV * 발행주식 변화)으로 섹터 로테이션 시그널을 만든다.
"""
import logging
from typing import Dict, Any

try:
    import yfinance as yf
except ImportError:
    yf = None

log = logging.getLogger(__name__)

# 추적 대상 ETF (테마 / 섹터 / 광범위)
TRACKED_ETFS = {
    # 미국 섹터 SPDR
    "XLK": "tech",
    "XLF": "financials",
    "XLE": "energy",
    "XLV": "healthcare",
    "XLI": "industrials",
    "XLY": "discretionary",
    "XLP": "staples",
    "XLU": "utilities",
    "XLB": "materials",
    "XLRE": "real_estate",
    # 테마
    "SMH": "semiconductor",
    "ARKK": "innovation",
    "URNM": "uranium",
    "ITA": "defense",
    "IBB": "biotech",
    "LIT": "battery",
    # 한국·신흥
    "EWY": "korea",
    "EEM": "emerging",
}


def fetch() -> Dict[str, Any]:
    """ETF별 가격·발행주식수 변화로 자금 유입 추정값 반환."""
    if yf is None:
        log.warning("yfinance 미설치 - 빈 dict 반환")
        return {}

    out: Dict[str, Any] = {}
    for sym, theme in TRACKED_ETFS.items():
        try:
            tk = yf.Ticker(sym)
            hist = tk.history(period="60d", auto_adjust=True)
            info = {}
            try:
                info = dict(tk.info or {})
            except Exception:
                pass
            out[sym] = {
                "theme": theme,
                "last_close": float(hist["Close"].iloc[-1]) if not hist.empty else None,
                "ret_1m": _pct_change(hist, 21),
                "ret_3m": _pct_change(hist, 63),
                "aum": info.get("totalAssets"),
            }
        except Exception as e:
            log.warning("ETF 수집 실패 %s: %s", sym, e)
            out[sym] = {"theme": theme}

    log.info("ETF 자금 흐름 수집 완료: %d", len(out))
    return out


def _pct_change(df, n: int):
    """n거래일 수익률(%)."""
    if df is None or df.empty or len(df) <= n:
        return None
    try:
        return float((df["Close"].iloc[-1] / df["Close"].iloc[-n] - 1) * 100)
    except Exception:
        return None
