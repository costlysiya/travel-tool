# -*- coding: utf-8 -*-
"""
계절별 해외여행 추천 — Streamlit 배포용 진입점.
`travel_tools.py`는 LangChain 도구만 담고, UI는 이 파일에서만 다룹니다.

실행 (travel_tool 디렉터리에서):
  python -m streamlit run streamlit_app.py
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from travel_tools import TRAVEL_SYSTEM_PROMPT, TRAVEL_TOOLS

load_dotenv()

TRAVEL_STYLES = ["휴양", "도시관광", "자연·하이킹", "미식", "가족동반"]
SEASONS = ["봄", "여름", "가을", "겨울"]
DEFAULT_CURRENCY = "KRW"


def build_travel_agent():
    assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY를 환경 변수 또는 Streamlit Secrets에 설정하세요."
    llm = ChatOpenAI(model="gpt-5-mini")
    return create_agent(
        llm,
        TRAVEL_TOOLS,
        system_prompt=TRAVEL_SYSTEM_PROMPT,
    )


def _sidebar_context(
    season: str,
    currency: str,
    budget_max: float,
    styles: list[str],
    trip_days: int,
) -> str:
    st_text = ", ".join(styles) if styles else "(미선택)"
    return (
        f"[사용자 설정] 계절: {season} | 예산 상한: {budget_max} {currency.strip().upper()} | "
        f"여행 일수: {trip_days}일 | 스타일: {st_text}"
    )


class TravelAssistant:
    """사이드바 컨텍스트를 매 턴 메시지에 포함하는 ReAct 에이전트."""

    def __init__(self):
        self.agent = build_travel_agent()
        self.history: list = []

    def chat(self, user_input: str, context_block: str) -> str:
        combined = f"{context_block}\n\n사용자 질문: {user_input}"
        self.history.append(HumanMessage(content=combined))
        result = self.agent.invoke({"messages": self.history})
        ai_message = result["messages"][-1]
        self.history.append(ai_message)
        return ai_message.content or ""

    def reset(self) -> None:
        self.history.clear()


def run_streamlit():
    import streamlit as st

    st.set_page_config(page_title="계절별 해외여행 추천", page_icon="🧭", layout="wide")

    # 로컬 .env 이후에도 없으면 Streamlit Cloud Secrets 사용
    if not os.getenv("OPENAI_API_KEY"):
        try:
            if hasattr(st, "secrets") and st.secrets.get("OPENAI_API_KEY"):
                os.environ["OPENAI_API_KEY"] = str(st.secrets["OPENAI_API_KEY"])
        except (FileNotFoundError, KeyError, AttributeError):
            pass
    st.title("🧭 계절별 해외여행 추천 (ReAct)")
    st.caption("travel_tool · Open-Meteo / Frankfurter / Nominatim / Wikipedia · gpt-5-mini")

    if "travel_assistant" not in st.session_state:
        st.session_state.travel_assistant = TravelAssistant()
    if "travel_msgs" not in st.session_state:
        st.session_state.travel_msgs = []

    with st.sidebar:
        st.header("여행 조건")
        season = st.selectbox("계절", SEASONS, index=0)
        currency = st.text_input("예산 통화 (ISO 코드)", value=DEFAULT_CURRENCY, max_chars=5)
        budget_max = st.number_input("최대 예산 (해당 통화)", min_value=0.0, value=3_000_000.0, step=100_000.0)
        trip_days = st.number_input("여행 일수", min_value=1, max_value=60, value=7)
        styles = st.multiselect("여행 스타일 (고정 목록)", TRAVEL_STYLES, default=["도시관광"])

        ctx = _sidebar_context(season, currency, budget_max, styles, trip_days)

        st.divider()
        st.markdown(
            "**워크플로:** 후보 풀 → 날씨 필터 → 환율·예산 밴드 → 위키 요약\n"
            "**도구:** `list_candidate_cities_for_season`, `filter_cities_by_weather_comfort`, "
            "`get_exchange_rate`, `estimate_budget_fit_for_country`, `get_wikipedia_travel_summary`"
        )
        if st.button("대화 초기화"):
            st.session_state.travel_assistant.reset()
            st.session_state.travel_msgs = []
            st.rerun()

    col_main, col_info = st.columns([2, 1])
    with col_info:
        st.info(
            "사이드바 값은 매 메시지에 `[사용자 설정]`으로 주입됩니다. "
            "예: 「계절 추천 도시부터 알려줘」「날씨 괜찮은 곳만 골라줘」."
        )

    with col_main:
        for role, text in st.session_state.travel_msgs:
            with st.chat_message(role):
                st.markdown(text)

        prompt = st.chat_input("추천을 요청하거나, 단계별로 도시 후보·날씨·예산을 물어보세요.")
        if prompt:
            st.session_state.travel_msgs.append(("user", prompt))
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("에이전트·도구 실행 중…"):
                    try:
                        reply = st.session_state.travel_assistant.chat(prompt, ctx)
                    except Exception as e:
                        reply = f"오류: {e}"
                st.markdown(reply)
            st.session_state.travel_msgs.append(("assistant", reply))


if __name__ == "__main__":
    run_streamlit()
