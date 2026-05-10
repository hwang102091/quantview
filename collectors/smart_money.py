"""
스마트머니 추적 수집기

- Dataroma : 슈퍼인베스터 포트폴리오 (버핏 BRK 기준, 매니저 코드로 확장 가능)
- SEC EDGAR Form 4 : 내부자 거래 ($10만 이상 매수만)
- Quiver Quant : 미 의회 의원 거래 (최근 30일)

사용 예:
    from collectors import smart_money
    brk = smart_money.fetch_dataroma("BRK")
    f4  = smart_money.fetch_sec_form4()
    cg  = smart_money.fetch_congress_trading()
    bundle = smart_money.fetch()
"""
import logging
import re
from datetime import date, timedelta
from typing import Dict, Any, List, Optional
import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from config import REQUEST_TIMEOUT

log = logging.getLogger(__name__)

DATAROMA_URL = "https://www.dataroma.com/m/holdings.php"
SEC_FORM4_URL = "https://efts.sec.gov/LATEST/search-index"
QUIVER_CONGRESS_URL = "https://api.quiverquant.com/beta/live/congresstrading"

# 슈퍼인베스터 매니저 코드 (Dataroma).
SUPERINVESTORS = {
    "BRK": "Warren Buffett (Berkshire)",
    # 확장 예시: "BAUPOST": "Seth Klarman", "BAILGI": "Baillie Gifford"
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
}

# SEC EDGAR 는 식별 가능한 UA 를 요구 (이메일 포함 권장)
SEC_HEADERS = {
    "User-Agent": "quantview research contact@example.com",
    "Accept": "application/json",
}

INSIDER_BUY_THRESHOLD_USD = 100_000


def fetch_dataroma(manager_code: str = "BRK") -> Optional[List[Dict[str, Any]]]:
    """
    Dataroma 슈퍼인베스터 보유종목 파싱.

    Args:
        manager_code: BRK(버핏) / BAUPOST(클라먼) 등
    Returns:
        [{ticker, name, percent_of_portfolio, recent_activity, shares}, ...]
    """
    if BeautifulSoup is None:
        log.warning("beautifulsoup4 미설치 - Dataroma 스킵")
        return None
    try:
        r = requests.get(
            DATAROMA_URL,
            params={"m": manager_code, "typ": "A"},
            headers=DEFAULT_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # holdings 테이블: id="grid"
        table = soup.find("table", id="grid") or soup.find("table")
        if table is None:
            log.warning("Dataroma 테이블 못찾음 (manager=%s)", manager_code)
            return None

        rows: List[Dict[str, Any]] = []
        for tr in table.select("tbody tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 4:
                continue
            # 컬럼 위치: 보통 [#, 종목/티커, 활동, %포트폴리오, 최근가, 평단, 손익, 보유수량 ...]
            ticker_cell = cells[1] if len(cells) > 1 else ""
            m = re.match(r"^([A-Z\.]+)\s*-\s*(.*)$", ticker_cell)
            if m:
                ticker, name = m.group(1), m.group(2)
            else:
                ticker, name = ticker_cell.split(" ", 1) if " " in ticker_cell else (ticker_cell, "")
            rows.append({
                "ticker": ticker,
                "name": name,
                "recent_activity": cells[2] if len(cells) > 2 else None,
                "percent_of_portfolio": _to_float(cells[3].replace("%", "")) if len(cells) > 3 else None,
                "recent_price": _to_float(cells[4]) if len(cells) > 4 else None,
                "avg_cost": _to_float(cells[5]) if len(cells) > 5 else None,
                "shares": _to_int(cells[7]) if len(cells) > 7 else None,
            })
        log.info("Dataroma %s 수집: %d 종목", manager_code, len(rows))
        return rows
    except Exception as e:
        log.warning("Dataroma %s 수집 실패: %s", manager_code, e)
        return None


def fetch_sec_form4(target_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """
    SEC EDGAR Form 4 검색 - 매수 $10만 이상 필터.
    당일 결과 0건이면 최근 7일로 날짜 범위 자동 확장.
    """
    end_date = target_date or date.today()

    def _query(start: date, end: date) -> List[Dict[str, Any]]:
        params = {
            "q": '"form-type":"4"',
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
        }
        r = requests.get(
            SEC_FORM4_URL,
            params=params,
            headers=SEC_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        hits = (r.json().get("hits") or {}).get("hits") or []
        rows: List[Dict[str, Any]] = []
        for h in hits:
            src = h.get("_source") or {}
            value = _to_float(src.get("value")) or 0.0
            if value < INSIDER_BUY_THRESHOLD_USD:
                continue
            rows.append({
                "accession": h.get("_id"),
                "filed_at": src.get("file_date"),
                "company": src.get("display_names") or src.get("entity"),
                "form_type": src.get("form"),
                "value_usd": value,
                "tickers": src.get("tickers"),
            })
        return rows

    try:
        # 1차: 당일
        rows = _query(end_date, end_date)
        if rows:
            log.info("SEC Form 4 (%s) 수집: %d건 (매수 $%dk+)",
                     end_date.isoformat(), len(rows), INSIDER_BUY_THRESHOLD_USD // 1000)
            return rows

        # 2차: 최근 7일로 확장
        start_7d = end_date - timedelta(days=7)
        rows = _query(start_7d, end_date)
        log.info("SEC Form 4 (최근 7일 %s~%s) 수집: %d건 (매수 $%dk+)",
                 start_7d.isoformat(), end_date.isoformat(),
                 len(rows), INSIDER_BUY_THRESHOLD_USD // 1000)
        return rows
    except Exception as e:
        log.warning("SEC Form 4 수집 실패: %s", e)
        return []


def fetch_congress_trading(days: int = 30) -> List[Dict[str, Any]]:
    """
    Quiver Quant 의회 거래 - 최근 N일.
    인증 실패(401/403) 시 빈 리스트 반환 (전체 중단 없음).
    """
    cutoff = date.today() - timedelta(days=days)
    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-CSRFToken": "",
        "Referer": "https://www.quiverquant.com",
        "Accept": "application/json, */*",
    }
    try:
        r = requests.get(
            QUIVER_CONGRESS_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code in (401, 403):
            log.warning("Quiver Quant 인증 필요 (status=%s) - 빈 리스트 반환", r.status_code)
            return []
        r.raise_for_status()
        data = r.json()
        rows: List[Dict[str, Any]] = []
        for item in data if isinstance(data, list) else []:
            tx_date_str = item.get("TransactionDate") or item.get("Traded")
            try:
                from datetime import datetime as _dt
                tx_date = _dt.fromisoformat(tx_date_str[:10]).date()
            except Exception:
                continue
            if tx_date < cutoff:
                continue
            rows.append({
                "ticker": item.get("Ticker"),
                "representative": item.get("Representative") or item.get("Name"),
                "transaction": item.get("Transaction"),
                "amount": item.get("Amount") or item.get("Range"),
                "date": tx_date.isoformat(),
                "house": item.get("House"),
                "party": item.get("Party"),
            })
        log.info("Quiver Quant 의회 거래 수집: %d건 (최근 %d일)", len(rows), days)
        return rows
    except Exception as e:
        log.warning("Quiver Quant 수집 실패: %s - 빈 리스트 반환", e)
        return []


def fetch() -> Dict[str, Any]:
    """run.py 호환 진입점 - 통합 dict."""
    out: Dict[str, Any] = {
        "dataroma": {},
        "form4": [],
        "congress": [],
    }
    for code, label in SUPERINVESTORS.items():
        result = fetch_dataroma(code)
        if result is not None:
            out["dataroma"][code] = {"label": label, "holdings": result}
    out["form4"] = fetch_sec_form4()
    out["congress"] = fetch_congress_trading()
    return out


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        s = str(v).replace(",", "").replace("$", "").strip()
        return float(s) if s not in ("", ".", "-") else None
    except (TypeError, ValueError):
        return None


def _to_int(v) -> Optional[int]:
    f = _to_float(v)
    return int(f) if f is not None else None
