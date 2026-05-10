"""
시장 센티먼트 수집기

- CNN Fear & Greed Index (메인 + 세부 지표)
- CBOE Put/Call Ratio (CBOE CDN → yfinance ^PCALL 순으로 시도)
- VIX (yfinance)
- CNN 센티먼트 세부 지표 (AAII 대체)

사용 예:
    from collectors import sentiment
    fng    = sentiment.fetch_fear_greed()
    pcr    = sentiment.fetch_put_call()
    vix    = sentiment.fetch_vix()
    bundle = sentiment.fetch()
"""
import logging
from typing import Dict, Any, Optional
import requests

try:
    import yfinance as yf
except ImportError:
    yf = None

from config import REQUEST_TIMEOUT

log = logging.getLogger(__name__)

CNN_FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CBOE_PCR_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/PUT_CALL_RATIO.json"

# CBOE 요청 시 Referer 포함 — 403 우회 목적
CBOE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
    "Referer": "https://www.cboe.com/",
    "Origin": "https://www.cboe.com",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
}


def fetch_fear_greed() -> Optional[Dict[str, Any]]:
    """CNN Fear & Greed Index 최신값 + 세부 지표."""
    try:
        r = requests.get(CNN_FNG_URL, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        fng = data.get("fear_and_greed") or {}
        indicators = data.get("fear_and_greed_historical") or {}
        return {
            "score": fng.get("score"),
            "rating": fng.get("rating"),
            "timestamp": fng.get("timestamp"),
            "previous_close": fng.get("previous_close"),
            "previous_1_week": fng.get("previous_1_week"),
            "previous_1_month": fng.get("previous_1_month"),
            "previous_1_year": fng.get("previous_1_year"),
        }
    except Exception as e:
        log.warning("Fear & Greed 수집 실패: %s", e)
        return None


def fetch_put_call() -> Optional[Dict[str, Any]]:
    """
    CBOE Put/Call Ratio 최신값.
    1차: CBOE CDN (Referer 헤더 포함)
    2차: yfinance ^PCALL
    둘 다 실패 시 None 반환.
    """
    # 1차 시도: CBOE CDN
    try:
        r = requests.get(CBOE_PCR_URL, headers=CBOE_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            rows = data.get("data") or []
            if rows:
                latest = rows[-1]
                if isinstance(latest, dict):
                    return {
                        "source": "cboe",
                        "date": latest.get("Date") or latest.get("date"),
                        "total": _to_float(latest.get("Total") or latest.get("RATIO")),
                        "equity": _to_float(latest.get("Equity")),
                        "index": _to_float(latest.get("Index")),
                    }
                if isinstance(latest, list) and len(latest) >= 2:
                    return {
                        "source": "cboe",
                        "date": latest[0],
                        "total": _to_float(latest[1]),
                        "equity": None,
                        "index": None,
                    }
        log.warning("CBOE P/C CDN 응답 이상 (status=%s) — yfinance 대체 시도", r.status_code)
    except Exception as e:
        log.warning("CBOE P/C CDN 실패: %s — yfinance 대체 시도", e)

    # 2차 시도: yfinance ^PCALL
    if yf is not None:
        try:
            hist = yf.Ticker("^PCALL").history(period="5d", auto_adjust=False)
            if hist is not None and not hist.empty:
                last_idx = hist.index[-1]
                return {
                    "source": "yfinance_pcall",
                    "date": str(last_idx.date()) if hasattr(last_idx, "date") else str(last_idx),
                    "total": float(hist["Close"].iloc[-1]),
                    "equity": None,
                    "index": None,
                }
        except Exception as e:
            log.warning("yfinance ^PCALL 수집 실패: %s", e)

    log.warning("Put/Call Ratio 수집 실패 — 두 소스 모두 응답 없음")
    return None


def fetch_vix() -> Optional[Dict[str, Any]]:
    """VIX 최신값 (yfinance ^VIX)."""
    if yf is None:
        log.warning("yfinance 미설치 - VIX 스킵")
        return None
    try:
        hist = yf.Ticker("^VIX").history(period="10d", auto_adjust=False)
        if hist is None or hist.empty:
            log.warning("^VIX 데이터 비어있음")
            return None
        last_idx = hist.index[-1]
        return {
            "date": str(last_idx.date()) if hasattr(last_idx, "date") else str(last_idx),
            "value": float(hist["Close"].iloc[-1]),
        }
    except Exception as e:
        log.warning("VIX 수집 실패: %s", e)
        return None


def fetch_cnn_sentiment() -> Optional[Dict[str, Any]]:
    """
    CNN Fear & Greed 세부 지표에서 sentiment 파싱 (AAII 대체).
    score 변화량으로 bull/bear 방향성을 추정한다.
    """
    try:
        r = requests.get(CNN_FNG_URL, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        fng = data.get("fear_and_greed") or {}

        score = fng.get("score")
        prev_close = fng.get("previous_close")
        prev_week = fng.get("previous_1_week")
        prev_month = fng.get("previous_1_month")

        if score is None:
            return None

        # score 0~100 기반으로 bull/bear 추정
        bullish = max(0.0, min(100.0, float(score)))
        bearish = 100.0 - bullish
        result = {
            "source": "cnn_fng",
            "score": score,
            "rating": fng.get("rating"),
            "bullish_pct": round(bullish, 1),
            "bearish_pct": round(bearish, 1),
            "previous_close": prev_close,
            "previous_1_week": prev_week,
            "previous_1_month": prev_month,
            "weekly_change": (
                round(float(score) - float(prev_week), 2)
                if score is not None and prev_week is not None else None
            ),
        }
        log.info("CNN sentiment 수집 완료: score=%.1f rating=%s", score, fng.get("rating"))
        return result
    except Exception as e:
        log.warning("CNN sentiment 수집 실패: %s", e)
        return None


# AAII 대체 공개 alias
fetch_aaii = fetch_cnn_sentiment


def fetch() -> Dict[str, Any]:
    """모든 센티먼트 지표 통합 dict (run.py 호환)."""
    return {
        "fear_greed": fetch_fear_greed() or {},
        "put_call":   fetch_put_call() or {},
        "vix":        fetch_vix() or {},
        "aaii":       fetch_cnn_sentiment() or {},
    }


def _to_float(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "", ".") else None
    except (TypeError, ValueError):
        return None
