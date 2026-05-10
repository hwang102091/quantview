"""
퀀트 투자 대시보드 - 전역 설정 모듈
환경변수, 섹터별 필터 기준, 유니버스 레이어 정의를 관리한다.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트 경로
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
DOCS_DATA_DIR = ROOT_DIR / "docs" / "data"
UNIVERSE_DIR = ROOT_DIR / "universe"

# .env 로드
load_dotenv(ROOT_DIR / ".env")

# ============================================================
# API 키 (환경변수에서 로드)
# ============================================================
DART_API_KEY = os.getenv("DART_API_KEY", "")   # 한국 전자공시(DART)
FRED_API_KEY = os.getenv("FRED_API_KEY", "")   # 미국 거시경제(FRED)

# ============================================================
# 유니버스 레이어 정의
#   LAYER1 : 전체 유니버스 (기초 데이터 수집 대상)
#   LAYER2 : 관심 종목 1000개 (스크리너 1차 통과)
#   LAYER3 : 집중 종목 100개 (랭킹 상위, 시그널 분석 대상)
# ============================================================
LAYER1 = {
    "name": "전체 유니버스",
    "size": None,   # 제한 없음
    "description": "코스피·코스닥·NYSE·NASDAQ 전 종목 기초 데이터",
}

LAYER2 = {
    "name": "관심 종목",
    "size": 1000,
    "description": "기본 스크리너(시총·거래대금·재무) 통과 종목",
}

LAYER3 = {
    "name": "집중 종목",
    "size": 100,
    "description": "팩터 랭킹 상위 + 스마트머니 + 센티먼트 종합 점수 상위",
}

# ============================================================
# 섹터별 필터 기준
#   - 바이오·SMR(소형원전): 적자 허용, 시총 하한 낮춤
#   - 금융주: 부채비율 무관 (업 특성)
#   - 조선·건설: 부채비율 완화 (수주산업 특성)
#   - 기본: 일반 제조·서비스업 표준 기준
# ============================================================
SECTOR_FILTERS = {
    # 기본값 (별도 오버라이드 없을 때 적용)
    "default": {
        "min_market_cap_bn": 100,        # 시총 최소 1000억
        "min_turnover_bn": 1.0,          # 일평균 거래대금 최소 10억
        "max_debt_ratio": 200.0,         # 부채비율 200% 이하
        "require_profit": True,          # 흑자 요구
        "min_per": -50.0,
        "max_per": 80.0,
    },
    # 바이오: 적자 허용, 시총 하한 낮춤
    "bio": {
        "min_market_cap_bn": 30,
        "min_turnover_bn": 0.5,
        "max_debt_ratio": 250.0,
        "require_profit": False,
        "min_per": None,
        "max_per": None,
    },
    # SMR(소형 원전): 신흥 산업, 적자 허용, 시총 하한 낮춤
    "nuclear": {
        "min_market_cap_bn": 30,
        "min_turnover_bn": 0.5,
        "max_debt_ratio": 250.0,
        "require_profit": False,
        "min_per": None,
        "max_per": None,
    },
    # 금융주: 부채비율 제외 (자본구조 자체가 다름)
    "finance": {
        "min_market_cap_bn": 200,
        "min_turnover_bn": 1.0,
        "max_debt_ratio": None,          # 부채비율 필터 무시
        "require_profit": True,
        "min_per": 2.0,
        "max_per": 20.0,
    },
    # 조선: 수주산업 특성, 부채비율 완화
    "shipbuilding": {
        "min_market_cap_bn": 100,
        "min_turnover_bn": 1.0,
        "max_debt_ratio": 400.0,
        "require_profit": False,
        "min_per": None,
        "max_per": None,
    },
    # 건설: 부채비율 완화
    "construction": {
        "min_market_cap_bn": 100,
        "min_turnover_bn": 1.0,
        "max_debt_ratio": 350.0,
        "require_profit": False,
        "min_per": None,
        "max_per": None,
    },
    # 반도체
    "semi": {
        "min_market_cap_bn": 200,
        "min_turnover_bn": 2.0,
        "max_debt_ratio": 200.0,
        "require_profit": True,
        "min_per": -10.0,
        "max_per": 100.0,
    },
    # 2차전지
    "battery": {
        "min_market_cap_bn": 100,
        "min_turnover_bn": 1.0,
        "max_debt_ratio": 250.0,
        "require_profit": False,
        "min_per": None,
        "max_per": 150.0,
    },
    # 방산
    "defense": {
        "min_market_cap_bn": 100,
        "min_turnover_bn": 1.0,
        "max_debt_ratio": 250.0,
        "require_profit": True,
        "min_per": 2.0,
        "max_per": 60.0,
    },
    # IT/플랫폼/클라우드
    "it": {
        "min_market_cap_bn": 100,
        "min_turnover_bn": 1.0,
        "max_debt_ratio": 200.0,
        "require_profit": True,
        "min_per": -20.0,
        "max_per": 120.0,
    },
    "cloud": {
        "min_market_cap_bn": 100,
        "min_turnover_bn": 1.0,
        "max_debt_ratio": 200.0,
        "require_profit": True,
        "min_per": -20.0,
        "max_per": 150.0,
    },
    # 소비재
    "consumer": {
        "min_market_cap_bn": 100,
        "min_turnover_bn": 0.5,
        "max_debt_ratio": 200.0,
        "require_profit": True,
        "min_per": 3.0,
        "max_per": 50.0,
    },
    # 철강/화학
    "steel_chem": {
        "min_market_cap_bn": 100,
        "min_turnover_bn": 1.0,
        "max_debt_ratio": 250.0,
        "require_profit": False,
        "min_per": None,
        "max_per": None,
    },
    # 소재
    "materials": {
        "min_market_cap_bn": 100,
        "min_turnover_bn": 1.0,
        "max_debt_ratio": 250.0,
        "require_profit": False,
        "min_per": None,
        "max_per": None,
    },
    # 에너지(원유·가스)
    "energy": {
        "min_market_cap_bn": 100,
        "min_turnover_bn": 1.0,
        "max_debt_ratio": 250.0,
        "require_profit": False,
        "min_per": None,
        "max_per": None,
    },
}


def get_sector_filter(tag: str) -> dict:
    """섹터 태그로 필터 기준 딕셔너리 반환. 미정의 태그는 default."""
    return SECTOR_FILTERS.get(tag, SECTOR_FILTERS["default"])


# ============================================================
# 데이터 갱신 주기 / 기타
# ============================================================
PRICE_HISTORY_DAYS = 365 * 2     # 가격 히스토리 2년
REQUEST_TIMEOUT = 15             # HTTP 타임아웃(초)
MAX_WORKERS = 8                  # 병렬 수집 워커 수
