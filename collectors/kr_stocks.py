"""
한국 주식 가격·재무·수급 수집기

- yfinance 로 가격 (.KS / .KQ 자동 시도)
- pykrx 로 KOSPI/KOSDAQ 외인·기관·개인 순매수
- DART 전자공시 API 로 재무제표 + corp_code 조회 (DART_API_KEY 필요)

사용 예:
    from collectors import kr_stocks

    # 단일 종목 가격 + 정보
    bundle = kr_stocks.fetch([{"ticker": "005930", "market": "kr"}])

    # 특정 일자 KRX 투자자별 순매수 (KOSPI+KOSDAQ 통합)
    krx = kr_stocks.fetch_krx_trading("20260508")

    # 종목코드 -> DART corp_code (8자리)
    corp = kr_stocks.fetch_dart_corp_code("005930")  # -> "00126380"

    # DART 재무제표
    fs = kr_stocks.fetch_dart_financials(corp)
"""
import io
import json
import logging
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Any
import pandas as pd
import requests

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from pykrx import stock as pykrx_stock
except ImportError:
    pykrx_stock = None

from config import PRICE_HISTORY_DAYS, DART_API_KEY, REQUEST_TIMEOUT, DATA_DIR

log = logging.getLogger(__name__)

DART_FNLTT_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
DART_CORP_CACHE = DATA_DIR / "dart_corp_codes.json"

# 모듈 메모리 캐시 (프로세스 단위)
_CORP_CODE_CACHE: Optional[Dict[str, str]] = None


def _yf_price(code: str) -> tuple:
    """6자리 코드를 .KS → .KQ 순으로 시도."""
    if yf is None:
        return pd.DataFrame(), {}
    for suffix in (".KS", ".KQ"):
        try:
            tk = yf.Ticker(f"{code}{suffix}")
            hist = tk.history(period=f"{PRICE_HISTORY_DAYS}d", auto_adjust=True)
            if hist is not None and not hist.empty:
                info = {}
                try:
                    info = dict(tk.info or {})
                except Exception:
                    pass
                return hist, info
        except Exception as e:
            log.debug("KR yfinance %s%s 실패: %s", code, suffix, e)
    return pd.DataFrame(), {}


def fetch(universe: List[Dict]) -> Dict[str, dict]:
    """
    한국 종목 가격 + info 일괄 수집 (run.py 호환).
    DART 재무제표는 별도로 fetch_dart_financials() 로 호출한다.
    """
    if yf is None:
        log.warning("yfinance 미설치 - 빈 딕셔너리 반환")
        return {}

    out: Dict[str, dict] = {}
    for item in universe:
        code = item["ticker"]
        try:
            hist, info = _yf_price(code)
            out[code] = {
                "price": hist,
                "info": info,
                "dart": None,
            }
        except Exception as e:
            log.warning("KR 수집 실패 %s: %s", code, e)
            out[code] = {"price": pd.DataFrame(), "info": {}, "dart": None}

    if DART_API_KEY:
        log.info("DART_API_KEY 감지 - fetch_dart_financials() 별도 호출 가능")
    else:
        log.info("DART_API_KEY 없음 - 재무 데이터 스킵")

    log.info("KR 가격 수집 완료: %d / %d", len(out), len(universe))
    return out


def fetch_krx_trading(date: str) -> Optional[pd.DataFrame]:
    """
    KRX 투자자별 거래실적 (외인/기관/개인 순매수) - pykrx 사용.

    Args:
        date: YYYYMMDD 형식 (예: "20260508")
    Returns:
        DataFrame[index=종목코드, 외국인, 기관합계, 개인, 시장, ...] 또는 None
        KOSPI / KOSDAQ 두 시장을 합쳐서 반환한다.
    """
    if pykrx_stock is None:
        log.warning("pykrx 미설치 - KRX 수급 스킵")
        return None
    try:
        frames = []
        for market in ("KOSPI", "KOSDAQ"):
            try:
                df = pykrx_stock.get_market_trading_volume_by_ticker(date, market=market)
                if df is None or df.empty:
                    log.warning("KRX %s %s 응답 비어있음", market, date)
                    continue
                df = df.copy()
                df["시장"] = market
                frames.append(df)
            except Exception as e:
                log.warning("KRX %s %s 수집 실패: %s", market, date, e)

        if not frames:
            return None

        merged = pd.concat(frames, axis=0)
        log.info("KRX 투자자별 순매수 수집: %s, %d 행 (KOSPI+KOSDAQ)", date, len(merged))
        return merged
    except Exception as e:
        log.warning("KRX 수급 수집 실패 %s: %s", date, e)
        return None


def fetch_dart_corp_code(ticker: str, force_refresh: bool = False) -> Optional[str]:
    """
    종목코드(6자리) -> DART corp_code(8자리) 변환.

    DART 의 corpCode.xml 은 전체 매핑이 들어있는 ~5MB ZIP 파일이라
    최초 1회만 다운로드해서 data/dart_corp_codes.json 에 캐싱한다.

    Args:
        ticker: 6자리 종목코드 (예: "005930")
        force_refresh: True 면 캐시 무시하고 재다운로드
    Returns:
        8자리 corp_code 문자열 또는 None
    """
    if not DART_API_KEY:
        log.warning("DART_API_KEY 없음 - corp_code 조회 스킵 (ticker=%s)", ticker)
        return None

    mapping = _load_corp_code_mapping(force_refresh=force_refresh)
    if not mapping:
        return None

    code = mapping.get(ticker.zfill(6))
    if code is None:
        log.warning("DART corp_code 없음: ticker=%s", ticker)
    return code


def _load_corp_code_mapping(force_refresh: bool = False) -> Optional[Dict[str, str]]:
    """corp_code 매핑 dict 로드 (메모리 -> 디스크 캐시 -> DART 다운로드 순)."""
    global _CORP_CODE_CACHE

    if _CORP_CODE_CACHE is not None and not force_refresh:
        return _CORP_CODE_CACHE

    if not force_refresh and DART_CORP_CACHE.exists():
        try:
            with open(DART_CORP_CACHE, "r", encoding="utf-8") as f:
                _CORP_CODE_CACHE = json.load(f)
            log.info("DART corp_code 디스크 캐시 사용: %d 종목", len(_CORP_CODE_CACHE))
            return _CORP_CODE_CACHE
        except Exception as e:
            log.warning("DART corp_code 캐시 읽기 실패, 재다운로드: %s", e)

    mapping = _download_corp_codes()
    if mapping is None:
        return None

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DART_CORP_CACHE, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False)
    except Exception as e:
        log.warning("DART corp_code 캐시 저장 실패: %s", e)

    _CORP_CODE_CACHE = mapping
    return mapping


def _download_corp_codes() -> Optional[Dict[str, str]]:
    """DART corpCode.xml ZIP 다운로드 -> {stock_code: corp_code} dict."""
    try:
        r = requests.get(
            DART_CORP_CODE_URL,
            params={"crtfc_key": DART_API_KEY},
            timeout=REQUEST_TIMEOUT * 4,   # ZIP 파일이라 시간 더 줌
        )
        r.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            xml_name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
            if xml_name is None:
                log.warning("DART corpCode.xml 응답에 XML 파일 없음")
                return None
            xml_bytes = zf.read(xml_name)

        root = ET.fromstring(xml_bytes)
        mapping: Dict[str, str] = {}
        for item in root.iter("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            corp_code = (item.findtext("corp_code") or "").strip()
            if stock_code and corp_code:
                mapping[stock_code] = corp_code

        log.info("DART corp_code 다운로드 완료: %d 종목 (상장사 기준)", len(mapping))
        return mapping
    except Exception as e:
        log.warning("DART corpCode.xml 다운로드 실패: %s", e)
        return None


def fetch_dart_financials(
    corp_code: str,
    bsns_year: Optional[str] = None,
    reprt_code: str = "11011",
    fs_div: str = "CFS",
) -> Optional[Dict[str, Any]]:
    """
    DART 단일회사 전체 재무제표 조회.

    Args:
        corp_code: 8자리 DART 고유번호
        bsns_year: 사업연도 (예: "2025"). 미지정 시 전년도
        reprt_code: 사업보고서(11011) / 반기(11012) / 1분기(11013) / 3분기(11014)
        fs_div: CFS(연결) / OFS(별도)
    Returns:
        DART 응답 dict 또는 None
    """
    if not DART_API_KEY:
        log.warning("DART_API_KEY 없음 - 재무제표 스킵 (corp_code=%s)", corp_code)
        return None
    if bsns_year is None:
        from datetime import datetime
        bsns_year = str(datetime.utcnow().year - 1)

    try:
        params = {
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        }
        r = requests.get(
            DART_FNLTT_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        status = data.get("status")
        if status != "000":
            log.warning("DART 응답 오류 corp=%s status=%s msg=%s",
                        corp_code, status, data.get("message"))
            return None
        log.info("DART 재무 수집 완료: corp=%s year=%s reprt=%s rows=%d",
                 corp_code, bsns_year, reprt_code, len(data.get("list") or []))
        return data
    except Exception as e:
        log.warning("DART 재무 수집 실패 corp=%s: %s", corp_code, e)
        return None
