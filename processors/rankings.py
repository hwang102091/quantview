"""
6종 랭킹 생성기 (각 TOP 20) + data/rankings.json 저장.

랭킹 종류:
  1. buy_consensus  - ratings.json buy 비율 상위
  2. target_upgrade - 최근 30일 목표가 상향 건수 상위
  3. insider_buy    - Form 4 매수금액 상위
  4. foreign_buy    - 외인 순매수 상위 (KR: 억원, US: $M)
  5. guru_buy       - Dataroma 신규진입·비중확대 상위
  6. congress_buy   - 의회 매수 상위
"""
import json
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from config import DATA_DIR, DOCS_DATA_DIR

log = logging.getLogger(__name__)

TOP_N = 20


# ── 공개 API ───────────────────────────────────────────────────────────────

def generate_rankings(
    stocks: List[Dict],
    smart_money: Dict,
    ratings: Dict,
) -> Dict[str, List[Dict]]:
    """
    6종 랭킹 각 TOP 20 생성.

    Args:
        stocks      : score_stocks() 결과 (quant_score 포함)
        smart_money : smart_money.fetch() 결과
        ratings     : ratings.fetch() 결과

    Returns:
        {buy_consensus, target_upgrade, insider_buy,
         foreign_buy, guru_buy, congress_buy}
    """
    result = {
        "buy_consensus":  _rank_buy_consensus(stocks, ratings),
        "target_upgrade": _rank_target_upgrade(stocks, ratings),
        "insider_buy":    _rank_insider_buy(stocks, smart_money),
        "foreign_buy":    _rank_foreign_buy(stocks),
        "guru_buy":       _rank_guru_buy(stocks, smart_money),
        "congress_buy":   _rank_congress_buy(stocks, smart_money),
    }
    for k, v in result.items():
        log.info("랭킹 %s: %d건", k, len(v))
    return result


def save(rankings: Dict, updated_at: str) -> None:
    """data/rankings.json 및 docs/data/rankings.json 저장."""
    payload = {"updated_at": updated_at, "rankings": rankings}
    for d in (DATA_DIR, DOCS_DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)
        path = d / "rankings.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            log.info("rankings.json 저장: %s", path)
        except Exception as e:
            log.error("rankings.json 저장 실패 %s: %s", path, e)


# ── run.py 레거시 호환 진입점 ───────────────────────────────────────────────

def run(
    watchlist: List[Dict],
    signals: Dict[str, dict],
    target_size: int = 100,
) -> List[Dict]:
    """
    기존 run() 인터페이스 유지.
    signals dict 와 watchlist 를 합쳐 quant_score 기준 상위 반환.
    """
    scored: List[Dict] = []
    for item in watchlist:
        sig = signals.get(item["ticker"], {}) or {}
        record = dict(item)
        record["signals"] = sig
        record["score"] = item.get("quant_score") or _legacy_score(sig)
        scored.append(record)

    scored.sort(key=lambda x: x.get("score") or 0, reverse=True)
    result = scored[:target_size]
    log.info("랭킹(legacy) 완료: top %d / %d", len(result), len(scored))
    return result


# ── 개별 랭킹 함수 ─────────────────────────────────────────────────────────

def _rank_buy_consensus(stocks: List[Dict], ratings: Dict) -> List[Dict]:
    """buy 비율 상위 20."""
    rows: List[Dict] = []
    for s in stocks:
        r = ratings.get(s["ticker"]) or {}
        buy = _to_int(r.get("buy"))
        hold = _to_int(r.get("hold"))
        sell = _to_int(r.get("sell"))
        total = buy + hold + sell
        if total == 0:
            continue
        rows.append({
            "ticker": s["ticker"],
            "name": s.get("name"),
            "market": s.get("market"),
            "buy_ratio": round(buy / total * 100, 1),
            "buy": buy,
            "hold": hold,
            "sell": sell,
            "n_analysts": total,
            "target": r.get("target"),
            "quant_score": s.get("quant_score"),
        })
    rows.sort(key=lambda x: x["buy_ratio"], reverse=True)
    return rows[:TOP_N]


def _rank_target_upgrade(stocks: List[Dict], ratings: Dict) -> List[Dict]:
    """최근 30일 목표가 상향 건수 상위 20."""
    cutoff = (date.today() - timedelta(days=30)).isoformat()

    rows: List[Dict] = []
    for s in stocks:
        r = ratings.get(s["ticker"]) or {}
        rec_rows = r.get("rows") or []
        cnt = 0
        for rec in rec_rows:
            d = str(rec.get("Date") or rec.get("date") or "")[:10]
            action = str(rec.get("Action") or rec.get("action") or "").lower()
            if d >= cutoff and any(k in action for k in ("upgrade", "raised", "increase")):
                cnt += 1
        if cnt == 0:
            continue
        rows.append({
            "ticker": s["ticker"],
            "name": s.get("name"),
            "market": s.get("market"),
            "upgrade_count": cnt,
            "target": r.get("target"),
            "quant_score": s.get("quant_score"),
        })
    rows.sort(key=lambda x: x["upgrade_count"], reverse=True)
    return rows[:TOP_N]


def _rank_insider_buy(stocks: List[Dict], smart_money: Dict) -> List[Dict]:
    """Form 4 매수금액 상위 20."""
    form4 = smart_money.get("form4") or []

    ticker_val: Dict[str, float] = {}
    ticker_meta: Dict[str, Dict] = {}
    for row in form4:
        val = row.get("value_usd") or 0.0
        if val <= 0:
            continue
        for t in (row.get("tickers") or []):
            if not t:
                continue
            ticker_val[t] = ticker_val.get(t, 0) + val
            if t not in ticker_meta:
                ticker_meta[t] = {
                    "company": row.get("company"),
                    "filed_at": row.get("filed_at"),
                }

    stock_map = {s["ticker"]: s for s in stocks}
    rows: List[Dict] = []
    for t, val in ticker_val.items():
        s = stock_map.get(t) or {}
        meta = ticker_meta[t]
        rows.append({
            "ticker": t,
            "name": s.get("name") or meta.get("company"),
            "market": s.get("market", "us"),
            "insider_buy_usd": round(val),
            "filed_at": meta.get("filed_at"),
            "quant_score": s.get("quant_score"),
        })
    rows.sort(key=lambda x: x["insider_buy_usd"], reverse=True)
    return rows[:TOP_N]


def _rank_foreign_buy(stocks: List[Dict]) -> List[Dict]:
    """외인 순매수 상위 20 (KR: 억원, US: $M)."""
    rows: List[Dict] = []
    for s in stocks:
        fnet = s.get("foreign_net_buy")
        if fnet is None:
            continue
        market = s.get("market", "us")
        if market == "kr":
            display = round(fnet / 1e8, 2)
            unit = "억원"
        else:
            display = round(fnet / 1e6, 2)
            unit = "$M"
        rows.append({
            "ticker": s["ticker"],
            "name": s.get("name"),
            "market": market,
            "foreign_net_buy": display,
            "unit": unit,
            "quant_score": s.get("quant_score"),
        })
    rows.sort(key=lambda x: x["foreign_net_buy"], reverse=True)
    return rows[:TOP_N]


def _rank_guru_buy(stocks: List[Dict], smart_money: Dict) -> List[Dict]:
    """Dataroma 신규진입·비중확대 상위 20."""
    dataroma = smart_money.get("dataroma") or {}

    ticker_gurus: Dict[str, List[str]] = {}
    ticker_pct: Dict[str, float] = {}
    for mgr_code, mgr in dataroma.items():
        label = mgr.get("label", mgr_code)
        for h in (mgr.get("holdings") or []):
            act = (h.get("recent_activity") or "").strip().lower()
            if act not in ("buy", "add", "new"):
                continue
            t = h.get("ticker")
            if not t:
                continue
            ticker_gurus.setdefault(t, []).append(label)
            pct = h.get("percent_of_portfolio") or 0.0
            ticker_pct[t] = max(ticker_pct.get(t, 0.0), pct)

    stock_map = {s["ticker"]: s for s in stocks}
    rows: List[Dict] = []
    for t, gurus in ticker_gurus.items():
        s = stock_map.get(t) or {}
        rows.append({
            "ticker": t,
            "name": s.get("name", t),
            "market": s.get("market", "us"),
            "gurus": gurus,
            "guru_count": len(gurus),
            "max_portfolio_pct": ticker_pct.get(t),
            "quant_score": s.get("quant_score"),
        })
    rows.sort(
        key=lambda x: (x["guru_count"], x.get("max_portfolio_pct") or 0),
        reverse=True,
    )
    return rows[:TOP_N]


def _rank_congress_buy(stocks: List[Dict], smart_money: Dict) -> List[Dict]:
    """의회 매수 상위 20."""
    congress = smart_money.get("congress") or []
    buy_list = [
        r for r in congress
        if (r.get("transaction") or "").lower() in ("purchase", "buy")
        and r.get("ticker")
    ]

    ticker_txs: Dict[str, List[Dict]] = {}
    for r in buy_list:
        ticker_txs.setdefault(r["ticker"], []).append(r)

    stock_map = {s["ticker"]: s for s in stocks}
    rows: List[Dict] = []
    for t, txs in ticker_txs.items():
        s = stock_map.get(t) or {}
        rows.append({
            "ticker": t,
            "name": s.get("name", t),
            "market": s.get("market", "us"),
            "congress_buy_count": len(txs),
            "representatives": list(
                {r.get("representative") for r in txs if r.get("representative")}
            ),
            "latest_date": max((r.get("date") or "" for r in txs), default=None),
            "quant_score": s.get("quant_score"),
        })
    rows.sort(key=lambda x: x["congress_buy_count"], reverse=True)
    return rows[:TOP_N]


# ── 유틸 ─────────────────────────────────────────────────────────────────

def _to_int(v) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _legacy_score(sig: dict) -> float:
    """signals.run() 결과 기반 레거시 점수 (호환용)."""
    if not sig:
        return 0.0
    m3 = sig.get("momentum_3m")
    mom = max(0.0, min(100.0, (m3 or 0) + 50))
    trend = sum([
        40 if sig.get("above_ma50") else 0,
        30 if sig.get("above_ma200") else 0,
        30 if sig.get("golden_cross") else 0,
    ])
    vs = sig.get("vol_surge") or 1.0
    vol = max(0.0, min(100.0, (vs - 1.0) * 100))
    near = max(0.0, min(100.0, sig.get("near_52w_high") or 0))
    return round(
        0.30 * mom + 0.20 * trend + 0.10 * vol + 0.15 * near + 0.25 * 50.0, 2
    )
