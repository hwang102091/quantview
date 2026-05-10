"""
거시경제 지표 수집기

FRED(미국 연준 데이터) + yfinance(BDI / VIX) 통합.

수집 항목:
  DFF       기준금리 (Fed Funds)
  GS10      미국 10년물 국채
  GS2       미국 2년물 국채
  T10Y2Y    장단기 금리차
  CPIAUCSL  CPI(All Urban)
  UNRATE    실업률
  M2SL      M2 통화량
  DEXKOUS   원달러 환율
  HG=F      구리선물 (BDI 대체, 경기선행 지표)
  ^VIX      VIX 변동성 지수 (yfinance)

사용 예:
    from collectors import macro
    dff   = macro.fetch_fred_series("DFF")
    bundle = macro.fetch_all_macro()
"""
import logging
from typing import Dict, Any, Optional
import requests

try:
    import yfinance as yf
except ImportError:
    yf = None

from config import FRED_API_KEY, REQUEST_TIMEOUT

log = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

FRED_SERIES = {
    "DFF":      "fed_funds_rate",
    "GS10":     "treasury_10y",
    "GS2":      "treasury_2y",
    "T10Y2Y":   "yield_spread_10y_2y",
    "CPIAUCSL": "cpi",
    "UNRATE":   "unemployment",
    "M2SL":     "m2_money_supply",
    "DEXKOUS":  "usd_krw",
}


def fetch_fred_series(series_id: str, units: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    FRED 단일 시리즈 최근 1개 관측치.

    Args:
        series_id: FRED 시리즈 ID
        units: 변환 단위 (예: "pc1" = 전년동기비 변화율). None이면 원시값.
    Returns:
        {"series_id": str, "date": str, "value": float} 또는 None
    """
    if not FRED_API_KEY:
        log.warning("FRED_API_KEY 없음 - %s 스킵", series_id)
        return None
    try:
        params: Dict[str, Any] = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        }
        if units:
            params["units"] = units
        r = requests.get(
            FRED_BASE,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        obs = r.json().get("observations", [])
        if not obs:
            log.warning("FRED %s 응답 비어있음", series_id)
            return None
        latest = obs[0]
        raw = latest.get("value")
        try:
            value = float(raw) if raw not in (".", None, "") else None
        except (TypeError, ValueError):
            value = None
        return {
            "series_id": series_id,
            "date": latest.get("date"),
            "value": value,
        }
    except Exception as e:
        log.warning("FRED %s 수집 실패: %s", series_id, e)
        return None


def _fetch_bdi_proxy() -> Optional[Dict[str, Any]]:
    """
    Baltic Dry Index 대리 지표.
    ^BDI 는 Yahoo Finance에서 상장폐지됨.
    대안: 구리 선물 HG=F (경기선행 지표, BDI와 유사한 역할).
    """
    if yf is None:
        return None
    # 구리 선물 (HG=F) — 경기 선행 지표
    result = _fetch_yf_index("HG=F")
    if result:
        result["note"] = "BDI 대체: 구리선물(HG=F) — 경기선행 지표"
        log.info("BDI 대체: 구리선물(HG=F) 수집 완료 (value=%.3f)", result["value"])
        return result
    log.warning("BDI 대체 지표(HG=F) 수집 실패 - 스킵")
    return None


def _fetch_yf_index(symbol: str) -> Optional[Dict[str, Any]]:
    """yfinance 인덱스 최신값 (^BDI, ^VIX 등)."""
    if yf is None:
        log.warning("yfinance 미설치 - %s 스킵", symbol)
        return None
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period="10d", auto_adjust=False)
        if hist is None or hist.empty:
            log.warning("%s 데이터 비어있음", symbol)
            return None
        last_idx = hist.index[-1]
        last_close = float(hist["Close"].iloc[-1])
        return {
            "symbol": symbol,
            "date": str(last_idx.date()) if hasattr(last_idx, "date") else str(last_idx),
            "value": last_close,
        }
    except Exception as e:
        log.warning("%s 수집 실패: %s", symbol, e)
        return None


def fetch_all_macro() -> Dict[str, Any]:
    """
    전체 매크로 지표 통합 dict.

    Returns:
        {
          "fred": {alias: {date, value}, ...},
          "bdi": {symbol, date, value},
          "vix": {symbol, date, value},
        }
    """
    out: Dict[str, Any] = {"fred": {}, "bdi": None, "vix": None}

    # CPI는 전년동기비 변화율(%)로 조회 (원시 지수값 ~330은 대시보드 표시 부적합)
    CPI_PCT_SERIES = {"CPIAUCSL"}

    for sid, alias in FRED_SERIES.items():
        result = fetch_fred_series(sid, units="pc1" if sid in CPI_PCT_SERIES else None)
        if result:
            out["fred"][alias] = {
                "date": result["date"],
                "value": result["value"],
            }

    out["bdi"] = _fetch_bdi_proxy()
    out["vix"] = _fetch_yf_index("^VIX")

    log.info("거시 지표 수집 완료: FRED %d, BDI=%s, VIX=%s",
             len(out["fred"]),
             "ok" if out["bdi"] else "fail",
             "ok" if out["vix"] else "fail")
    return out


def fetch() -> Dict[str, Any]:
    """run.py 호환 진입점."""
    return fetch_all_macro()
