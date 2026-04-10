# -*- coding: utf-8 -*-
"""
seed.yaml 기반 해외여행 추천용 LangChain 도구.
Open-Meteo(날씨), Frankfurter(환율), Nominatim(지오코딩), Wikipedia(요약) — 키 불필요 조합.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from langchain.tools import tool

USER_AGENT = "SeasonalTravelPlanner/1.0 (travel_tool; seed.yaml)"

# 날씨 1차 필터 (야외 활동 부담 — seed 수용 기준)
MEAN_DAILY_MAX_TOO_HOT_C = 35.0
MEAN_DAILY_MIN_TOO_COLD_C = -8.0

# 국가별 대략 일일 여행 비용(USD, 매우 거친 휴리스틱 — seed 비목표: 정확한 총비용)
COUNTRY_DAILY_USD_ROUGH: dict[str, tuple[float, float]] = {
    "thailand": (35, 90),
    "vietnam": (30, 80),
    "portugal": (70, 150),
    "spain": (75, 160),
    "france": (90, 200),
    "italy": (85, 190),
    "japan": (90, 220),
    "south korea": (70, 160),
    "korea": (70, 160),
    "switzerland": (150, 350),
    "norway": (140, 300),
    "greece": (65, 140),
    "australia": (100, 220),
    "new zealand": (95, 210),
    "united states": (100, 250),
    "usa": (100, 250),
    "united kingdom": (90, 200),
    "uk": (90, 200),
    "germany": (85, 180),
    "netherlands": (85, 175),
    "taiwan": (55, 120),
    "singapore": (80, 180),
    "indonesia": (40, 100),
    "morocco": (45, 100),
    "mexico": (45, 110),
    "canada": (90, 200),
}

# 계절별 후보 풀 (도시, 국가 영문) — 데모용 고정 풀
SEASON_CANDIDATE_POOL: dict[str, list[str]] = {
    "봄": [
        "Lisbon, Portugal",
        "Paris, France",
        "Kyoto, Japan",
        "Seville, Spain",
        "Taipei, Taiwan",
        "Athens, Greece",
    ],
    "여름": [
        "Reykjavik, Iceland",
        "Bergen, Norway",
        "Vancouver, Canada",
        "Edinburgh, United Kingdom",
        "Dublin, Ireland",
        "Helsinki, Finland",
    ],
    "가을": [
        "Munich, Germany",
        "Montreal, Canada",
        "Seoul, South Korea",
        "Prague, Czech Republic",
        "Vienna, Austria",
        "Portland, United States",
    ],
    "겨울": [
        "Bangkok, Thailand",
        "Ho Chi Minh City, Vietnam",
        "Cairo, Egypt",
        "Dubai, United Arab Emirates",
        "Sydney, Australia",
        "Auckland, New Zealand",
    ],
}


def _http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _geocode(query: str) -> dict[str, Any] | None:
    q = urllib.parse.quote(query)
    url = f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1"
    try:
        data = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if not data:
        return None
    row = data[0]
    return {
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "display_name": row.get("display_name", query),
    }


def _forecast_means(lat: float, lon: float, days: int = 7) -> tuple[float | None, float | None]:
    """7일 예보 일 최고/최저 평균 (Open-Meteo)."""
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        "&daily=temperature_2m_max,temperature_2m_min"
        f"&forecast_days={days}&timezone=auto"
    )
    try:
        data = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError):
        return None, None
    daily = data.get("daily") or {}
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    if not tmax or not tmin:
        return None, None
    ok = [x for x in tmax if x is not None]
    ok2 = [x for x in tmin if x is not None]
    if not ok or not ok2:
        return None, None
    return sum(ok) / len(ok), sum(ok2) / len(ok2)


@tool
def list_candidate_cities_for_season(season: str) -> str:
    """계절(봄/여름/가을/겨울)에 맞는 해외 후보 도시 목록을 반환합니다. 추천 워크플로의 첫 단계에서 사용합니다."""
    s = season.strip()
    for key in SEASON_CANDIDATE_POOL:
        if key in s or s in key:
            lines = SEASON_CANDIDATE_POOL[key]
            return (
                f"[계절 풀: {key}]\n"
                + "\n".join(lines)
                + "\n\n다음 도구 `filter_cities_by_weather_comfort`로 날씨 적합도를 필터링하세요."
            )
    return (
        f"알 수 없는 계절 표현: {season}. "
        f"다음 중 하나로 다시 요청하세요: {', '.join(SEASON_CANDIDATE_POOL.keys())}"
    )


@tool
def filter_cities_by_weather_comfort(season: str, cities_block: str) -> str:
    """
    후보 도시들에 대해 단기 기온 예보(향후 며칠)로 야외 활동 부담 여부를 판단합니다.
    cities_block: 줄바꿈으로 구분된 '도시, 국가' 목록 (예: Paris, France).
    너무 덥거나(일 평균 최고 기준) 너무 추우면 탈락으로 표시합니다.
    """
    lines = [ln.strip() for ln in cities_block.strip().splitlines() if ln.strip()]
    if not lines:
        return "도시 목록이 비어 있습니다. `list_candidate_cities_for_season` 결과를 붙여 넣으세요."

    rows: list[str] = []
    for line in lines:
        g = _geocode(line)
        if not g:
            rows.append(f"- {line} | 오류 | 지오코딩 실패 (표기를 영문 도시, 국가로 바꿔 보세요)")
            continue
        mean_max, mean_min = _forecast_means(g["lat"], g["lon"])
        if mean_max is None or mean_min is None:
            rows.append(f"- {line} | 오류 | 날씨 API 실패")
            continue
        reasons: list[str] = []
        status = "통과"
        if mean_max >= MEAN_DAILY_MAX_TOO_HOT_C:
            status = "탈락"
            reasons.append(f"평균 일 최고 {mean_max:.1f}°C ≥ {MEAN_DAILY_MAX_TOO_HOT_C}°C (무더위)")
        if mean_min <= MEAN_DAILY_MIN_TOO_COLD_C:
            status = "탈락"
            reasons.append(f"평균 일 최저 {mean_min:.1f}°C ≤ {MEAN_DAILY_MIN_TOO_COLD_C}°C (한파)")
        r = ", ".join(reasons) if reasons else "기온 범위 양호"
        rows.append(
            f"- {line} | {status} | 일평균 최고 {mean_max:.1f}°C / 일평균 최저 {mean_min:.1f}°C | {r}"
        )

    header = (
        f"[날씨 필터 · 계절 컨텍스트: {season}]\n"
        f"임계: 평균 일최고 ≥{MEAN_DAILY_MAX_TOO_HOT_C}°C 또는 평균 일최저 ≤{MEAN_DAILY_MIN_TOO_COLD_C}°C → 탈락\n\n"
    )
    return header + "\n".join(rows)


@tool
def get_exchange_rate(base_currency: str, target_currency: str) -> str:
    """Frankfurter(ECB) 기준 환율을 조회합니다. ISO 4217 코드(예: USD, KRW, EUR)."""
    b = base_currency.strip().upper()
    t = target_currency.strip().upper()
    if b == t:
        return f"1 {b} = 1 {t}"
    url = f"https://api.frankfurter.app/latest?from={b}&to={t}"
    try:
        data = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return f"환율 조회 실패: {b} → {t}. 통화 코드를 확인하세요."
    rates = data.get("rates") or {}
    rate = rates.get(t)
    if rate is None:
        return f"응답에 {t} 환율이 없습니다. 지원 통화인지 확인하세요."
    return f"1 {b} = {rate} {t} (Frankfurter, ECB)"


@tool
def estimate_budget_fit_for_country(
    budget_currency: str,
    budget_max: float,
    trip_days: int,
    country_query: str,
) -> str:
    """
    예산(통화·최대 금액)과 여행 일수로 국가 대략 비용 밴드와의 적합도를 텍스트로 반환합니다.
    정확한 총비용이 아니라 데모용 휴리스틱입니다(seed 비목표).
    """
    if budget_max <= 0 or trip_days <= 0:
        return "budget_max와 trip_days는 양수여야 합니다."
    cq = country_query.strip().lower()
    band = None
    for k, v in COUNTRY_DAILY_USD_ROUGH.items():
        if k in cq:
            band = v
            break
    if band is None:
        return (
            f"'{country_query}'에 대한 내장 비용 밴드가 없습니다. "
            "다른 주요 국가명(영문)으로 다시 시도하거나, 환율만 참고하세요."
        )
    low, high = band
    # 예산을 USD로 환산
    b = budget_currency.strip().upper()
    rate_to_usd = 1.0
    if b != "USD":
        url = f"https://api.frankfurter.app/latest?from={b}&to=USD"
        try:
            data = _http_get_json(url)
            r = (data.get("rates") or {}).get("USD")
            if r is None:
                return f"{b} → USD 환산 실패"
            rate_to_usd = r
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return f"{b} → USD 환산 실패"
    budget_usd = budget_max * rate_to_usd
    daily_budget = budget_usd / trip_days
    if daily_budget >= high * 1.1:
        verdict = "예산이 해당 국가 일반적인 일일 지출 상한보다 넉넉한 편입니다."
    elif daily_budget >= low:
        verdict = "예산이 국가 밴드(대략)와 비슷하거나 약간 여유 있습니다."
    else:
        verdict = "예산이 국가 평균 일일 지출 대비 다소 타이트할 수 있습니다(휴리스틱)."
    return (
        f"[{country_query}] 대략 일일 지출 밴드(USD): {low}–{high} / "
        f"일 예산(환산): 약 {daily_budget:.1f} USD ({verdict})"
    )


@tool
def get_wikipedia_travel_summary(place_name: str) -> str:
    """위키백과 영문 요약(도입부)을 가져와 관광 맥락을 제공합니다. 도시명 또는 랜드마크."""
    title = place_name.strip()
    if not title:
        return "장소명을 입력하세요."
    params = {
        "action": "query",
        "prop": "extracts",
        "exintro": "true",
        "explaintext": "true",
        "titles": title,
        "format": "json",
        "redirects": "1",
    }
    q = urllib.parse.urlencode(params)
    url = f"https://en.wikipedia.org/w/api.php?{q}"
    try:
        data = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return "Wikipedia 요청 실패."
    pages = (data.get("query") or {}).get("pages") or {}
    for _pid, page in pages.items():
        ext = page.get("extract")
        if ext:
            text = ext.strip().replace("\n", " ")
            if len(text) > 900:
                text = text[:900] + "…"
            return f"[{page.get('title', title)}]\n{text}"
    return f"'{title}'에 대한 영문 위키 요약을 찾지 못했습니다."


TRAVEL_TOOLS = [
    list_candidate_cities_for_season,
    filter_cities_by_weather_comfort,
    get_exchange_rate,
    estimate_budget_fit_for_country,
    get_wikipedia_travel_summary,
]

TRAVEL_SYSTEM_PROMPT = """당신은 한국어로 답하는 해외 여행 기획 도우미입니다 (seed: 계절·예산·스타일).

워크플로 (도구를 이 순서를 우선하세요):
1) `list_candidate_cities_for_season`으로 계절에 맞는 후보 도시 풀을 가져옵니다.
2) `filter_cities_by_weather_comfort`로 날씨(무더위/한파)에 부적합한 도시를 탈락시킵니다.
3) 남은 후보에 대해 `get_exchange_rate`와 `estimate_budget_fit_for_country`로 예산 적합도를 비교합니다.
4) 최종 추천 도시·코스를 설명할 때 `get_wikipedia_travel_summary`로 명소/배경을 보강합니다.

사용자 메시지 앞에 붙는 [사용자 설정] 블록(계절, 통화, 예산 상한, 스타일)을 반드시 반영하세요.
정확한 항공·호텔 가격이나 비자 판단은 하지 마세요(seed 비목표).
모델은 도구 결과를 근거로 요약하고, 분기(날씨 탈락 후 다른 도시로 진행)를 설명에 드러내세요."""