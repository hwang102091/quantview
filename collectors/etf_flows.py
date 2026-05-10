"""
ETF 자금 유출입 수집기

지정 ETF 의 AUM 변화량(= 가격수익률 보정 후 잔여) 으로 1일 / 5일 자금유입을
근사 추정한다. (정확한 NAV*shares_outstanding 계산이 어려운 종목은
가격 수익률 + 거래대금 기반으로 추정)

추적 ETF:
  미국: SOXX SMH XLK URA NLR ITA SHLD IBB XBI XLF XLY XLI XLB XLE XLU CLOU
  한국: 114800(KODEX 인버스) 091160(KODEX 반도체) 305720(KODEX 2차전지산업)

사용 예:
    from collectors import etf_flows
    flows = etf_flows.fetch_etf_flows()
    flows["SOXX"]  # -> {theme, aum, aum_change, flow_1d, flow_5d, ...}
"""
import logging
from typing import Dict, Any, Optional

try:
    import yfinance as yf
except ImportError:
    yf = None

log = logging.getLogger(__name__)

# 미국 ETF -> 섹터/테마 라벨
US_ETFS = {
    "SOXX": "semiconductor",
    "SMH":  "semiconductor",
    "XLK":  "tech",
    "URA":  "uranium",
    "NLR":  "nuclear",
    "ITA":  "defense",
    "SHLD": "defense",
    "IBB":  "biotech",
    "XBI":  "biotech",
    "XLF":  "financials",
    "XLY":  "discretionary",
    "XLI":  "industrials",
    "XLB":  "materials",
    "XLE":  "energy",
    "XLU":  "utilities",
    "CLOU": "cloud",
}

# 한국 ETF (yfinance .KS)
KR_ETFS = {
    "114800": "kodex_inverse",
    "091160": "kodex_semiconductor",
    "305720": "kodex_battery",
}

# 통합 섹터 매핑 (외부에서 사용)
ETF_THEME_MAP: Dict[str, str] = {**US_ETFS, **KR_ETFS}


def fetch_etf_flows() -> Dict[str, Dict[str, Any]]:
    """
    ETF 별 AUM 및 1일·5일 자금흐름 추정.

    Returns:
        {
          "SOXX": {
            "theme": "semiconductor",
            "last_close": float,
            "aum": float|None,         # totalAssets (USD 또는 KRW)
            "aum_change": float|None,  # 5일 전 대비 AUM 추정 변화율(%)
            "flow_1d": float|None,     # 1일 자금흐름 추정 (= 거래대금 * 부호)
            "flow_5d": float|None,     # 5일 누적 자금흐름 추정
            "ret_1d": float|None,
            "ret_5d": float|None,
          }, ...
        }
    """
    if yf is None:
        log.warning("yfinance 미설치 - ETF 자금흐름 빈 dict 반환")
        return {}

    out: Dict[str, Dict[str, Any]] = {}

    # 미국
    for sym, theme in US_ETFS.items():
        out[sym] = _fetch_one(sym, theme, market="us")

    # 한국 (yfinance 는 6자리 코드에 .KS / .KQ 접미사 필요)
    for code, theme in KR_ETFS.items():
        for suffix in (".KS", ".KQ"):
            yf_sym = f"{code}{suffix}"
            row = _fetch_one(yf_sym, theme, market="kr")
            if row.get("last_close") is not None:
                out[code] = row
                break
        else:
            out[code] = {"theme": theme, "market": "kr"}

    success = sum(1 for v in out.values() if v.get("last_close") is not None)
    log.info("ETF 자금흐름 수집 완료: %d / %d", success, len(out))
    return out


def _fetch_one(symbol: str, theme: str, market: str) -> Dict[str, Any]:
    """단일 ETF 처리."""
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period="30d", auto_adjust=False)
        info: Dict[str, Any] = {}
        try:
            info = dict(tk.info or {})
        except Exception:
            pass

        if hist is None or hist.empty:
            return {"theme": theme, "market": market}

        last_close = float(hist["Close"].iloc[-1])
        last_volume = float(hist["Volume"].iloc[-1]) if "Volume" in hist else 0.0

        ret_1d = _pct(hist, 1)
        ret_5d = _pct(hist, 5)

        # 자금흐름 근사: 일일 거래대금 × 가격 변동 부호
        flow_1d = None
        if ret_1d is not None and last_volume:
            flow_1d = last_volume * last_close * (1 if ret_1d >= 0 else -1)

        flow_5d = None
        if len(hist) >= 6:
            recent = hist.tail(5)
            try:
                signed = (
                    (recent["Close"].diff().fillna(0) >= 0).astype(int) * 2 - 1
                ) * recent["Volume"] * recent["Close"]
                flow_5d = float(signed.sum())
            except Exception:
                flow_5d = None

        aum = info.get("totalAssets")
        # AUM 변화율: 가격수익률을 제거해 발행주식수 변화분만 근사
        aum_change = None
        if aum and ret_5d is not None:
            try:
                price_factor = 1.0 + (ret_5d / 100.0)
                aum_change = (1.0 - 1.0 / price_factor) * 100 if price_factor else None
            except Exception:
                aum_change = None

        return {
            "theme": theme,
            "market": market,
            "symbol": symbol,
            "last_close": last_close,
            "aum": aum,
            "aum_change": aum_change,
            "flow_1d": flow_1d,
            "flow_5d": flow_5d,
            "ret_1d": ret_1d,
            "ret_5d": ret_5d,
        }
    except Exception as e:
        log.warning("ETF 수집 실패 %s: %s", symbol, e)
        return {"theme": theme, "market": market}


def _pct(df, n: int) -> Optional[float]:
    """n거래일 수익률(%)."""
    try:
        if df is None or df.empty or len(df) <= n:
            return None
        return float((df["Close"].iloc[-1] / df["Close"].iloc[-1 - n] - 1) * 100)
    except Exception:
        return None


def fetch() -> Dict[str, Any]:
    """run.py 호환 진입점."""
    return fetch_etf_flows()
