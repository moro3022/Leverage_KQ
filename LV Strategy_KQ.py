import FinanceDataReader as fdr
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
import json
import gspread
import holidays
import pytz
import numpy as np 
from oauth2client.service_account import ServiceAccountCredentials

# ==============================================================================
# Google Sheets 연동 관련 함수
# 향후 Google Sheets에서 데이터를 읽어오기 위한 클라이언트 설정
# ==============================================================================
def get_google_sheet_client(): # 기존 함수명 유지 (추후 필요시 변경 권장: get_google_sheet_client)
    """
    Google Sheets API에 연결하고 첫 번째 워크시트 객체를 반환합니다.
    Streamlit secrets에 GOOGLE_SHEETS_CREDS 인증 정보가 필요합니다.
    """
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(st.secrets["GOOGLE_SHEETS_CREDS"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1rNV0OQM9gnRDZPTVYf_Bf0zyNXuhR6S6Zv48sJFvhUE").get_worksheet(0)
    return sheet # 시트 객체를 반환하도록 임시로 추가 (함수 사용 방식에 따라 변경 가능)

# ==============================================================================
# 헬퍼 함수 정의 (UI 출력 및 데이터 처리 보조)
# ==============================================================================

def format_date(d):
    return d.strftime("%m-%d %a").replace("Mon", "월").replace("Tue", "화").replace("Wed", "수").replace("Thu", "목").replace("Fri", "금")

def get_color(strategy):
    return {"레버리지": "#5BA17B", "인버스": "#F27366", "현금보유": "#9E9E9E", "오버나잇": "#F9B544"}.get(strategy, "#333")

def get_disparity_bar(value, strategy):
    percent = min(max((value - 98) * 100 / (106 - 98), 0), 100)
    bar_color = get_color(strategy) # 전략에 맞는 색상 사용
    return f"""<div style='width:100%; background:#eee; height:6px; border-radius:3px;'><div style='width:{percent:.1f}%; background:{bar_color}; height:6px; border-radius:3px;'></div></div>"""

def get_condition_badges(volume_cond, low_cond):
    html_parts = []
    # 뱃지 기본 스타일 정의: 연한 회색 배경, 어두운 글자색, 둥근 모서리 등
    base_badge_style = "background-color:#F0F0F0; color:#303030; padding:2px 6px; border-radius:8px; font-size:12px;"
    
    if volume_cond:
        html_parts.append(f"<span style='{base_badge_style} margin-right:4px;'>거래량</span>") # 거래량 조건 충족 시 뱃지 추가
    if low_cond:
        html_parts.append(f"<span style='{base_badge_style}'>저가</span>") # 저가 조건 충족 시 뱃지 추가
    if not volume_cond and not low_cond:
        # '조건 없음' 뱃지 스타일 (더 밝은 회색 배경, 살짝 옅은 텍스트)
        inactive_badge_style = "background-color:#FAFAFA; color:#A0A0A0; padding:2px 6px; border-radius:8px; font-size:12px;"
        inactive_badge_style += " box-shadow: 0 1px 2px rgba(0,0,0,0.05);" # 그림자는 더 연하게
        html_parts.append(f"<span style='{inactive_badge_style}'>해당없음</span>")
    
    return "".join(html_parts) # 생성된 뱃지 HTML 문자열들을 합쳐서 반환

def next_business_day(date):
    # datetime 객체인 경우 date로 변환
    if isinstance(date, datetime):
        date = date.date()
    
    # 한국 공휴일 객체 생성
    kr_holidays = holidays.SouthKorea()
    next_day = date + timedelta(days=1)
    
    # 주말(토요일=5, 일요일=6)이거나 공휴일인 경우 다음날로 이동
    while (next_day.weekday() >= 5 or 
           next_day in kr_holidays or 
           (next_day.month == 12 and next_day.day == 31)):  # 매년 12월 31일 휴장
        next_day += timedelta(days=1)
    
    return next_day


# ==============================================================================
# 전략 리스트 HTML 생성 함수
# ==============================================================================
def create_strategy_list_html(recent_df, prev_day_df, prev2_day_df):
    
    # 1. 오버나잇(Overnight) 전략 조건 계산 (기존과 동일)
    UR = float(prev_day_df["High"]) - float(prev_day_df["Open"])
    LR_today = float(prev_day_df["Open"]) - float(prev_day_df["Low"])
    LR_yesterday = float(prev2_day_df["Open"]) - float(prev2_day_df["Low"])
    is_overnight_condition_met = UR > max(LR_today, LR_yesterday)

    if is_overnight_condition_met:
        border_and_text_color = "#F9B544" 
    else:
        border_and_text_color = "#A0A0A0" 
    
    부등호 = ">" if is_overnight_condition_met else "&le;"
    reason_text = f"UR {UR:.0f} {부등호} LR MAX({LR_today:.0f}, {LR_yesterday:.0f})"
    badge_style = f"background-color:transparent; color:{border_and_text_color}; font-size:13px; padding:4px 10px; border-radius:15px; border: 1px solid {border_and_text_color};"

    list_header_html = f'''
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding: 0 8px;">
        <div style="font-size:18px; font-weight:bold;">전략리스트</div>
        <span style="{badge_style}">{reason_text}</span>
    </div>
    '''

    rows_html = ""

    # 🎯 수정: 실제 거래일 기준 최근 6일 고정 표시
    # recent_df에서 마지막 6개 행 추출 (이미 거래일만 포함됨)
    display_days = min(6, len(recent_df) - 1)  # 최대 6일, prev_row 참조 위해 -1
    start_idx = len(recent_df) - display_days
    
    for i in reversed(range(start_idx, len(recent_df))):
        row = recent_df.iloc[i]
        
        # prev_row 안전하게 참조
        if i > 0:
            prev_row = recent_df.iloc[i-1]
        else:
            prev_row = row  # 첫 행인 경우 자기 자신 참조 (안전장치)
        
        card_style = "padding:14px 16px; background:#fff; border-radius:12px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,0.06);"
        
        # 가장 최근 데이터에만 강조 표시
        if i == len(recent_df) - 1: 
            card_style += f" border-left:4px solid {get_color(row['판단'])};"

        # 다음 영업일 계산
        strategy_date = next_business_day(row.name)
    
        rows_html += f"""\
        <div style="{card_style}">\
            <div style="display:flex; justify-content:space-between; align-items:center;">\
                <div style="display:flex; align-items:center; gap:8px;">\
                    <div style="font-size:16px; font-weight:500;">{format_date(strategy_date)}</div>\
                </div>\
                <div style="background:{get_color(row['판단'])}; color:white; padding:4px 10px; border-radius:12px; font-size:13px;">{row['판단']}</div>\
            </div>\
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-top:6px;">\
                <div style="font-size:18px; font-weight:bold; color:#ffffff;">종가</div>\
                <div style="font-size:14px; color:#666;">{row['Disparity']:.2f}</div>\
            </div>\
            <div style="margin-top:6px;">\
                {get_disparity_bar(row["Disparity"], row["판단"])}\
            </div>\
            <div style="font-size:14px; color:#999; margin-top:8px;">\
                {get_condition_badges(float(row["Volume"]) < float(row["Volume_MA3"]), float(row["Low"]) > float(prev_row["Low"]))}\
            </div>\
        </div>\
"""
    return f"<div>{list_header_html}{rows_html}</div>"

# ==============================================================================
# 코스닥150 레버리지 전략 계산 함수
# ==============================================================================
def calculate_kosdaq_strategy(df_kosdaq, df_leverage):

    # 20일 이동평균 및 이격도 계산
    df_kosdaq["Close_MA20"] = df_kosdaq["Close"].rolling(20).mean().fillna(method='ffill')
    df_kosdaq["Disparity"] = (df_kosdaq["Close"] / df_kosdaq["Close_MA20"]) * 100
    df_kosdaq.dropna(inplace=True)
    
    # 포지션 컬럼 초기화
    df_kosdaq["포지션"] = "현금"
    
    # 순차적으로 포지션 계산 (초기값: 현금)
    for i in range(1, len(df_kosdaq)):
        prev_position = df_kosdaq.iloc[i-1]["포지션"]
        
        # 직전 10개 영업일의 max(close - open) 계산 (하락일은 0 처리)
        close_open_diffs = []
        for j in range(max(0, i-10), i):
            close_val = float(df_kosdaq.iloc[j]["Close"])
            open_val = float(df_kosdaq.iloc[j]["Open"])
            diff = max(0, close_val - open_val)  # 하락일은 0
            close_open_diffs.append(diff)
        
        max_close_open_10 = max(close_open_diffs) if close_open_diffs else 0

        # K(B), K(S) 계산
        prev_high = float(df_kosdaq.iloc[i-1]["High"])
        prev_low = float(df_kosdaq.iloc[i-1]["Low"])
        today_open = float(df_kosdaq.iloc[i]["Open"])
        today_high = float(df_kosdaq.iloc[i]["High"])
        today_low = float(df_kosdaq.iloc[i]["Low"])
        
        K_B = np.ceil(today_open + min((prev_high - prev_low) * 0.4, max_close_open_10))
        K_S = np.floor(today_open - (prev_high - prev_low) * 0.3)
        
        # 전일 이격도 가져오기 (매도 조건에 필요)
        # 날짜 매칭으로 전일 이격도 찾기
        current_date = df_kosdaq.index[i]
        prev_date = df_kosdaq.index[i-1]
        
        # 전일 이격도 (코스닥150 & 레버리지)
        try:
            prev_kosdaq_disparity = float(df_kosdaq.iloc[i-1]["Disparity"])
        except:
            prev_kosdaq_disparity = 999  # 이격도 없으면 매도 불가
            
        try:
            # 레버리지 데이터에서 같은 날짜의 전일 이격도 찾기
            if prev_date in df_leverage.index:
                prev_leverage_disparity = float(df_leverage.loc[prev_date, "Disparity"])
            else:
                prev_leverage_disparity = 999
        except:
            prev_leverage_disparity = 999
        
        # 매수 조건: 전일 현금 & K(S)가 당일 고가~저가 범위 내
        can_buy = (today_low <= K_B <= today_high)
        
        # 매도 조건: 전일 보유 & K(B)가 당일 고가~저가 범위 내 & 양쪽 전일 이격도 106 이하
        can_sell = (
            (today_low <= K_S <= today_high) and
            (prev_kosdaq_disparity <= 106) and
            (prev_leverage_disparity <= 106)
        )
        
        if prev_position == "현금" and can_buy:
            df_kosdaq.at[df_kosdaq.index[i], "포지션"] = "보유"
        elif prev_position == "보유" and can_sell:
            df_kosdaq.at[df_kosdaq.index[i], "포지션"] = "현금"
        else:
            df_kosdaq.at[df_kosdaq.index[i], "포지션"] = prev_position
    
    return df_kosdaq

# ==============================================================================
# 메인 애플리케이션 로직 시작
# ==============================================================================

# 4-1. 전역 폰트 설정을 위한 CSS 주입
st.markdown("""
<style>
    html, body, [class*="st-"] {
        font-family: 'Noto Sans KR', sans-serif !important;
    }
</style>
""", unsafe_allow_html=True)

    
# === 1. 설정값 정의 ===
LEVERAGE_TICKER = "122630"  # KODEX 레버리지
INVERSE_TICKER = "252670"   # KODEX 인버스
KOSDAQ_LEVERAGE_TICKER = "233740"  # KODEX 코스닥150 레버리지

# 데이터 조회 기간 설정 (오늘 기준 과거 40일 ~ 미래 1일)
today = datetime.now()
start_date = today - timedelta(days=60)
end_date = today + timedelta(days=1)

# === 2. 데이터 로드 및 전처리 ===
df_leverage = fdr.DataReader(LEVERAGE_TICKER, start_date, end_date)
df_inverse = fdr.DataReader(INVERSE_TICKER, start_date, end_date)
df_kosdaq = fdr.DataReader(KOSDAQ_LEVERAGE_TICKER, start_date, end_date)


# 레버리지 데이터를 메인으로 사용 (기존 로직 유지)
df = df_leverage.copy()

# 다운로드된 데이터프레임의 컬럼이 MultiIndex일 경우 단일 레벨로 평탄화
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
if isinstance(df_inverse.columns, pd.MultiIndex):
    df_inverse.columns = df_inverse.columns.get_level_values(0)
if isinstance(df_kosdaq.columns, pd.MultiIndex):
    df_kosdaq.columns = df_kosdaq.columns.get_level_values(0)

# 데이터 유효성 검사: 데이터가 없거나 전략 계산에 필요한 최소 일수 미만일 경우 오류 메시지 출력
if df.empty or len(df) < 22: # 최소 20일 이동평균 + 추가 데이터 필요
    st.error("❌ 데이터가 부족하거나 불러오지 못했습니다. 날짜 범위를 확인해 주세요.")
else: # 데이터가 충분히 있을 경우에만 실행
    # 3일 이동평균 거래량 계산 
    df["Volume_MA3"] = df["Volume"].rolling(3).mean().fillna(method='ffill')
    # 20일 이동평균 종가 계산 
    df["Close_MA20"] = df["Close"].rolling(20).mean().fillna(method='ffill')
    # 이격도 계산: (현재 종가 / 20일 이동평균 종가) * 100
    df["Disparity"] = (df["Close"] / df["Close_MA20"]) * 100
    df.dropna(inplace=True) # 모든 계산 후 발생할 수 있는 추가적인 NaN 값 포함 행 제거

    # 코스닥150 레버리지 전략 계산
    df_kosdaq = calculate_kosdaq_strategy(df_kosdaq, df_leverage)

    # === 3. 핵심 전략 로직 (전략 판단 및 액션 결정) ===
    # 최근 14일치 데이터를 복사하여 전략 판단에 사용 (충분한 과거 데이터 확보)
    recent = df.tail(20).copy()
    
    # 3-1. 기본 전략 판단 (레버리지, 인버스, 현금보유)
    for i in range(1, len(recent)):
        row = recent.iloc[i] # 현재 일자의 데이터
        prev_row = recent.iloc[i - 1] # 이전 일자의 데이터
        disparity_r = float(row["Disparity"])
        prev_disparity = float(prev_row["Disparity"])
        d = "현금보유" # 기본 판단값
        
        # 조건1 (거래량 감소) 또는 조건2 (저가 상승) 충족 시
        if float(row["Volume"]) < float(row["Volume_MA3"]) or float(row["Low"]) > float(prev_row["Low"]):
            if disparity_r < 98 or disparity_r > 106: # 이격도 기준에 따라 '레버리지'
                d = "레버리지"
            else: # 이외는 '현금보유'
                d = "현금보유"
        elif disparity_r < 101: # 조건1,2 미충족 시 이격도 기준 및 추가 인버스 진입 조건 확인
            # 인버스 진입 조건: ABS(당일 이격도 - 전날 이격도) < 0.5
            disparity_change = disparity_r - prev_disparity
            if abs(disparity_change) >= 0.5:
                d = "인버스"
            else:
                d = "현금보유" # 인버스 진입 조건 미충족 시 현금보유
        recent.at[recent.index[i], "판단"] = d # 계산된 판단값을 DataFrame에 저장

    # 오버나잇 전략 적용 (기존 '현금보유' 판단에 오버나잇 조건 충족 시 '오버나잇'으로 변경)
    # prev_day, prev2_day 정의가 필요한 부분
    # 주의: create_strategy_list_html에 전달되는 prev_day, prev2_day는
    # main 로직의 df.iloc[-1], df.iloc[-2]와 다름.
    # main 로직에서 사용되는 prev_day, prev2_day는 여기에서 정의되어야 합니다.
    prev_day = df.iloc[-1]   # 메인 출력부에서 사용될 오늘(가장 최신) 데이터
    prev2_day = df.iloc[-2]  # 메인 출력부에서 사용될 어제 데이터

    # 오버나잇 전략 적용 - 첫 번째 블록 (최근 6일)
    for i in range(len(recent) - 6, len(recent) - 1):
        if recent.iloc[i]["판단"] == "현금보유":
            # ✅ 전일(i-1) 판단 확인
            if i > 0:
                day_before_decision = recent.iloc[i - 1]["판단"]
                
                # ✅ 전일이 레버리지가 아닐 때만 오버나잇 체크
                if day_before_decision != "레버리지":
                    today_row = recent.iloc[i + 1]
                    yesterday_row = recent.iloc[i]

                    UR = float(today_row["High"]) - float(today_row["Open"])
                    LR_today = float(today_row["Open"]) - float(today_row["Low"])
                    LR_yesterday = float(yesterday_row["Open"]) - float(yesterday_row["Low"])
                    
                    if UR > max(LR_today, LR_yesterday):
                        recent.at[recent.index[i], "판단"] = "오버나잇"

# 오버나잇 전략 적용 (기존 '현금보유' 판단에 오버나잇 조건 충족 시 '오버나잇'으로 변경)
    # 🎯 수정: 루프 범위를 `range(1, 6)`으로 변경하고 변수명을 조정했습니다.
    if len(recent) < 3:
        st.warning("데이터가 충분하지 않습니다.")
    else:
        max_check_days = min(6, len(recent) - 2)  # 최대 6일, 하지만 데이터 길이 고려

        for i in range(1, max_check_days + 1):  # 데이터가 있는 만큼만 검토
            if i + 1 >= len(recent):
                break
            
            if recent.iloc[i]["판단"] == "현금보유":

                day_before_decision = recent.iloc[i - 1]["판단"]
                
                if day_before_decision != "레버리지":
                    today_row = recent.iloc[i + 1]
                    yesterday_row = recent.iloc[i]

                    UR = float(today_row["High"]) - float(today_row["Open"])
                    LR_today = float(today_row["Open"]) - float(today_row["Low"])
                    LR_yesterday = float(yesterday_row["Open"]) - float(yesterday_row["Low"])

                    if UR > max(LR_today, LR_yesterday):
                        recent.at[recent.index[i], "판단"] = "오버나잇"

    # 3-3. 전일/당일 전략 기반 최종 액션(매수/매도) 판단
    prev_decision = recent.iloc[-2]["판단"] # 전일의 최종 전략 판단
    decision = recent.iloc[-1]["판단"] # 당일의 최종 전략 판단 (UI 출력에 사용될 최종 판단)

    # 3-3-1. '오버나잇'을 '레버리지' 포지션으로 간주하여 액션 판단 간소화
    effective_prev_position = "레버리지" if prev_decision in ["레버리지", "오버나잇"] else prev_decision
    effective_today_position = "레버리지" if decision in ["레버리지", "오버나잇"] else decision

    # 3-3-2. 전일-당일 포지션 조합에 따른 매수/매도 액션 매핑 테이블
    action_map = {
        ("현금보유", "레버리지"): ("레버리지", "없음"),
        ("현금보유", "인버스"): ("인버스", "없음"),
        ("레버리지", "현금보유"): ("없음", "레버리지"),
        ("인버스", "현금보유"): ("없음", "인버스"),
        ("레버리지", "인버스"): ("인버스", "레버리지"),
        ("인버스", "레버리지"): ("레버리지", "인버스"),
    }

    # 3-3-3. 매핑 테이블에서 현재 상황에 맞는 매수/매도 액션 조회
    매수액션, 매도액션 = action_map.get((effective_prev_position, effective_today_position), ("없음", "없음"))
    
    # 3-3-4. 예외 처리: 전일 '레버리지'이고 당일 '오버나잇'일 경우 (포지션 유지 의미)
    if prev_decision == "레버리지" and decision == "오버나잇":
        매수액션, 매도액션 = ("레버리지", "레버리지") # '레버리지' 포지션 유지

    # 3-4. 현재 전략 신호의 연속 일수 계산
    signal_streak = 0
    if len(recent) > 1:
        today_signal = recent['판단'].iloc[-1]
        signal_streak = 1 # 오늘을 포함
        for i in range(len(recent) - 2, -1, -1): # 마지막에서 두 번째 날부터 역순으로 탐색
            if recent['판단'].iloc[i] == today_signal:
                signal_streak += 1
            else:
                break # 다른 신호가 나오면 중단

# === 4. Streamlit UI 구성 및 출력 ===

# 4-2. 오버나잇 조건 변경시 오버나잇으로 헤더 표기
def get_header_card_display_vars(recent, prev_day, prev2_day, decision, prev_decision, signal_streak, 매수액션, 매도액션, action_map):
    display_date_row = prev2_day
    display_prev_date_row = prev2_day
    display_decision = decision
    display_signal_streak = signal_streak
    display_매수액션 = 매수액션
    display_매도액션 = 매도액션

    # 조건: 최근일(오늘)의 전날 (recent.iloc[-2])이 "오버나잇"인 경우
    if recent.iloc[-2]["판단"] == "오버나잇":
        display_date_row = recent.iloc[-2]
        display_prev_date_row = recent.iloc[-3]
        display_decision = recent.iloc[-2]["판단"]

        # 신호 지속일 재계산
        temp_signal_streak = 0
        if len(recent) >= 3:
            target_signal = recent.iloc[-2]["판단"]
            temp_signal_streak = 1
            for k in range(len(recent) - 3, -1, -1): 
                if recent.iloc[k]["판단"] == target_signal:
                    temp_signal_streak += 1
                else:
                    break
        display_signal_streak = temp_signal_streak

        # 매수/매도 액션 재계산
        effective_prev_position_alt = "레버리지" if display_prev_date_row["판단"] in ["레버리지", "오버나잇"] else display_prev_date_row["판단"]
        effective_today_position_alt = "레버리지" if display_date_row["판단"] in ["레버리지", "오버나잇"] else display_date_row["판단"]

        display_매수액션, display_매도액션 = action_map.get((effective_prev_position_alt, effective_today_position_alt), ("없음", "없음"))
        
        if display_prev_date_row["판단"] == "레버리지" and display_date_row["판단"] == "오버나잇":
            display_매수액션, display_매도액션 = ("레버리지", "레버리지")
            
    return display_date_row, display_prev_date_row, display_decision, display_signal_streak, display_매수액션, display_매도액션

# 4-3. 상단 헤더 카드 출력: 오늘 날짜, 최종 전략, 신호 지속일, 매수/매도 액션 요약

(display_date_row, display_prev_date_row, display_decision,
display_signal_streak, display_매수액션, display_매도액션) = \
    get_header_card_display_vars(recent, prev_day, prev2_day, decision, prev_decision, signal_streak, 매수액션, 매도액션, action_map)

# 헤더 날짜는 전략 판단 다음날로 표기
header_color = get_color(display_decision)
today = datetime.today().date() 
next_biz_day = next_business_day(today)
today_str = next_biz_day.strftime("%Y-%m-%d %A").replace("Monday","월요일").replace("Tuesday","화요일").replace("Wednesday","수요일").replace("Thursday","목요일").replace("Friday","금요일")

# 상단 헤더 카드 출력:
st.markdown(f"""
<div style="background-color:{header_color}; border-radius:16px; padding:20px; color:white; text-align:center; margin-bottom:20px;">
    <div style="font-size:16px; opacity:0.9; margin-bottom: 0;">{today_str}</div>
    <div style="font-size:32px; font-weight:bold; margin-top: 0;">{display_decision}</div>
    <div style="font-size:16px; font-weight:normal; opacity:0.8; margin-bottom:0;">({display_signal_streak}일째)</div>
    <hr style="border:none; border-top:1px solid #FFFFFF50; margin: 8px 0 12px 0;">
    <div style="display:flex; justify-content:space-around; text-align:center;">
        <div>
            <div style="font-size:14px; opacity:0.8;">매수</div>
            <div style="font-size:18px; font-weight:bold;">{display_매수액션}</div>
        </div>
        <div>
            <div style="font-size:14px; opacity:0.8;">매도</div>
            <div style="font-size:18px; font-weight:bold;">{display_매도액션}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# 4-4. 전략 리스트를 details 태그로 묶기
strategy_list_html = create_strategy_list_html(recent, prev_day, prev2_day)

combined_info_html = f"""
<details style='background-color: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 0; margin-bottom: 16px;'>
<summary style='background-color: #f8f9fa; padding: 12px 16px; font-weight: 600; cursor: pointer; list-style: none; font-size: 15px;'>
📊 전략리스트
</summary>
<div style="padding: 12px;">
    {strategy_list_html}
</div>
</details>
"""

st.markdown(combined_info_html, unsafe_allow_html=True)

# ==============================================================================
# 오버나잇 조건 수동 계산기 (간결 버전)
# ==============================================================================
st.write("")
# details 태그를 사용한 오버나잇 계산기

prev2_day = df.iloc[-2]

# HTML details 태그로 오버나잇 계산기 생성
if not df.empty and len(df) >= 2:
    calculator_lr_yesterday = float(prev2_day["Open"]) - float(prev2_day["Low"])

    # 오늘 데이터 기본값
    today_open = float(df.iloc[-1]["Open"])
    today_high = float(df.iloc[-1]["High"])
    today_low = float(df.iloc[-1]["Low"])

    # 계산
    ur = today_high - today_open
    lr_today = today_open - today_low
    lr_yesterday = calculator_lr_yesterday 

    부등호_calc = ">" if ur > max(lr_today, lr_yesterday) else "≤"
    calc_reason_text = f"UR {ur:,.0f}원 {부등호_calc} LR MAX({lr_today:,.0f}원, {lr_yesterday:,.0f}원)"

    # 결과에 따른 스타일 설정
    if ur > max(lr_today, lr_yesterday):
        result_color = "#28a745"  # 녹색
        result_status = "충족"
    else:
        result_color = "#fd7e14"  # 주황색
        result_status = "미충족"

    # HTML details 태그로 결과 표시
    calculator_details = f"""
    <details style='background-color: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 0;'>
    <summary style='background-color: #f8f9fa; padding: 12px 16px; font-weight: 600; cursor: pointer; list-style: none; font-size: 15px;'>
    📊 오버나잇 계산기 결과
    </summary>
    <div style='padding: 16px; font-size: 0.9rem; line-height: 1.8;'>
    <div style='color: {result_color}; font-weight: 600; margin-bottom: 8px;'>
    {result_status}: {calc_reason_text}
    </div>
    <div style='font-size: 0.8rem; color: #666;'>
    시가: {today_open:,.0f}원 | 고가: {today_high:,.0f}원 | 저가: {today_low:,.0f}원<br>
    UR: {ur:,.0f}원 | LR(오늘): {lr_today:,.0f}원 | LR(어제): {lr_yesterday:,.0f}원
    </div>
    </div>
    </details>
    """

    st.markdown(calculator_details, unsafe_allow_html=True)

else:
    # 데이터 부족 시 간단한 정보 표시
    info_details = f"""
    <details style='background-color: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 0; margin-top: 16px;'>
    <summary style='background-color: #f8f9fa; padding: 12px 16px; font-weight: 600; cursor: pointer; list-style: none; font-size: 15px;'>
    📊 오버나잇 계산기
    </summary>
    <div style='padding: 16px; font-size: 0.9rem; line-height: 1.8; color: #666;'>
    데이터가 부족합니다. 최소 2일의 데이터가 필요합니다.
    </div>
    </details>
    """
    
    st.markdown(info_details, unsafe_allow_html=True)


# ==============================================================================
# 코스닥150 레버리지 전략 섹션 (UI 출력 부분)
# ==============================================================================
st.write("")

# 코스닥150 레버리지 전략 섹션 수정
if not df_kosdaq.empty and len(df_kosdaq) >= 2:

    kst = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(kst)
    current_hour = now_kst.hour

    # 장 시작 전(00:00~08:59) 여부 확인
    is_before_market_open = current_hour < 9
    
    if is_before_market_open:
        # 🌙 장 시작 전: 전일 데이터로 오늘의 K_B, K_S 미리 계산
        kosdaq_yesterday = df_kosdaq.iloc[-1]   # 어제 (마지막 거래일)
        kosdaq_day_before = df_kosdaq.iloc[-2]  # 그저께
        leverage_yesterday = df.iloc[-1]
        leverage_day_before = df.iloc[-2]
        
        # 전일 이격도 (매도 조건용)
        prev_kosdaq_disparity = float(kosdaq_day_before["Disparity"])
        prev_leverage_disparity = float(leverage_day_before["Disparity"])

        
        # 오늘의 K_B, K_S 계산에 사용할 데이터
        prev_high = float(kosdaq_yesterday["High"])      # 어제 고가
        prev_low = float(kosdaq_yesterday["Low"])        # 어제 저가
        today_open = float(kosdaq_yesterday["Close"])    # 어제 종가를 예상 시가로 사용

        close_open_diffs = []
        start_idx = max(0, len(df_kosdaq) - 11)
        for j in range(start_idx, len(df_kosdaq) - 1):
            close_val = float(df_kosdaq.iloc[j]["Close"])
            open_val = float(df_kosdaq.iloc[j]["Open"])
            diff = max(0, close_val - open_val)
            close_open_diffs.append(diff)
        
        max_close_open_10 = max(close_open_diffs) if close_open_diffs else 0

        # 현재가는 어제 종가
        current_price = float(kosdaq_yesterday["Close"])
        today_high = float(kosdaq_yesterday["High"])     # 참고용
        today_low = float(kosdaq_yesterday["Low"])       # 참고용
        
        # 현재 포지션 정보
        current_position = kosdaq_yesterday["포지션"]
        prev_position = kosdaq_day_before["포지션"]
        
    else:
        # 📈 장 시작 후: 당일 시가 기준으로 K_B, K_S 계산
        kosdaq_today = df_kosdaq.iloc[-1]       # 오늘 (최신 데이터)
        kosdaq_yesterday = df_kosdaq.iloc[-2]   # 어제
        leverage_today = df.iloc[-1]
        leverage_yesterday = df.iloc[-2]
        
        # 전일 이격도 (매도 조건용)
        prev_kosdaq_disparity = float(kosdaq_yesterday["Disparity"])
        prev_leverage_disparity = float(leverage_yesterday["Disparity"])
        
        # 오늘의 K_B, K_S 계산에 사용할 데이터
        prev_high = float(kosdaq_yesterday["High"])      # 어제 고가
        prev_low = float(kosdaq_yesterday["Low"])        # 어제 저가
        today_open = float(kosdaq_today["Open"])         # 오늘 시가
        today_high = float(kosdaq_today["High"])         # 오늘 고가
        today_low = float(kosdaq_today["Low"])           # 오늘 저가
        current_price = float(kosdaq_today["Close"])     # 현재가
        
        # 🎯 추가: 직전 10개 영업일의 max(close - open) 계산
        close_open_diffs = []
        start_idx = max(0, len(df_kosdaq) - 11)  # 오늘 제외하고 과거 10개
        for j in range(start_idx, len(df_kosdaq) - 1):
            close_val = float(df_kosdaq.iloc[j]["Close"])
            open_val = float(df_kosdaq.iloc[j]["Open"])
            diff = max(0, close_val - open_val)
            close_open_diffs.append(diff)
        
        max_close_open_10 = max(close_open_diffs) if close_open_diffs else 0

        # 현재 포지션 정보
        current_position = kosdaq_today["포지션"]
        prev_position = kosdaq_yesterday["포지션"]

    
    # 공통: 이격도 충족 여부
    disparity_met = prev_kosdaq_disparity <= 106 and prev_leverage_disparity <= 106
    disparity_status = "✓ 충족" if disparity_met else "✗ 미충족"
    
    # K_B, K_S 계산
    prev_range = prev_high - prev_low
    range_multiplier_buy = prev_range * 0.4   # 매수용 (K_B)
    range_multiplier_sell = prev_range * 0.3  # 매도용 (K_S)
    
    K_B = np.ceil(today_open + min(range_multiplier_buy, max_close_open_10))   # 매수 기준가
    K_S = np.floor(today_open - range_multiplier_sell)  # 매도 기준가
    
    # 조건 충족 여부
    kb_met = (today_low <= K_B <= today_high) if not is_before_market_open else False
    ks_met = (today_low <= K_S <= today_high) if not is_before_market_open else False
    
    kb_status = "✓ 충족" if kb_met else "✗ 미충족" if not is_before_market_open else "⏳ 대기"
    ks_status = "✓ 충족" if ks_met else "✗ 미충족" if not is_before_market_open else "⏳ 대기"
    
    # 오늘 액션 판단
    today_action = "없음"
    if not is_before_market_open:
        if prev_position == "현금" and kb_met:
            today_action = "매수"
        elif prev_position == "보유" and ks_met and disparity_met:
            today_action = "매도"
    else:
        # 장 시작 전: 예상 액션
        if prev_position == "현금":
            today_action = "매수 대기"
        elif prev_position == "보유":
            if disparity_met:
                today_action = "매도 대기"
            else:
                today_action = "이격도 미충족"
    
    position_color = "#5BA17B" if current_position == "보유" else "#9E9E9E"
    
    # HTML 생성 시작
    kosdaq_html = f"""<details style='background-color: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 0; margin-top: 16px;'>
    <summary style='background-color: #f8f9fa; padding: 12px 16px; font-weight: 600; cursor: pointer; list-style: none; font-size: 15px;'>
    📈 코스닥 레버리지
    </summary>
    <div style='padding: 16px;'>
    <div style='background-color: {position_color}; color: white; border-radius: 8px; padding: 14px; text-align: center; margin-bottom: 12px;'>
        <div style='font-size: 14px; opacity: 0.9;'>현재 포지션</div>
        <div style='font-size: 20px; font-weight: bold; margin-top: 4px;'>{current_position}</div>
        <hr style='border: none; border-top: 1px solid #ffffff50; margin: 10px 0;'>
        <div style='font-size: 14px;'>오늘 액션: <strong>{today_action}</strong></div>
    </div>"""
    
    if prev_position == "현금":
        border_color = "#5BA17B" if kb_met else "#9E9E9E"
        kosdaq_html += f"""<div style='background-color: #f8f9fa; border-radius: 10px; padding: 16px; margin-bottom: 12px; border-left: 4px solid {border_color};'>
            <div style='display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px;'>
                <span style='font-size: 13px; color: #6c757d; font-weight: 500;'>K(B) 매수 기준</span>
                <span style='font-size: 20px; font-weight: 700; color: #212529;'>{K_B:,.0f}원</span>
            </div>
            <div style='font-size: 12px; color: #868e96; line-height: 1.6;'>
                {'예상 시가' if is_before_market_open else '당일 시가'}: {today_open:,.0f}원<br>
                조건1 (전일): {range_multiplier_buy:,.0f}원<br>
                조건2 (10일): {max_close_open_10:,.0f}원<br>
            </div>
            <div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid #dee2e6;'>
                <span style='font-size: 13px; font-weight: 600;'>{kb_status}</span>
            </div>
        </div>"""
    else:
        all_conditions_met = ks_met and disparity_met
        border_color = "#5BA17B" if all_conditions_met else "#9E9E9E"
        kosdaq_html += f"""<div style='background-color: #f8f9fa; border-radius: 10px; padding: 16px; margin-bottom: 12px; border-left: 4px solid {border_color};'>
            <div style='display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px;'>
                <span style='font-size: 13px; color: #6c757d; font-weight: 500;'>K(S) 매도 기준</span>
                <span style='font-size: 20px; font-weight: 700; color: #212529;'>{K_S:,.0f}원</span>
            </div>
            <div style='font-size: 12px; color: #868e96; line-height: 1.6; margin-bottom: 10px;'>
                {'예상 시가' if is_before_market_open else '당일 시가'}: {today_open:,.0f}원<br>
                전일 범위 ({prev_high:,.0f} - {prev_low:,.0f}) × 0.3 = {range_multiplier_sell:,.0f}원<br>
            </div>
            <div style='font-size: 12px; color: #adb5bd; line-height: 1.5;'>
                코스피 {prev_leverage_disparity:.2f} / 코스닥 {prev_kosdaq_disparity:.2f}
            </div>
            <div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid #dee2e6; display: flex; gap: 16px;'>
                <div>
                    <span style='font-size: 11px; color: #868e96;'>가격</span>
                    <span style='font-size: 13px; font-weight: 600; margin-left: 4px;'>{ks_status}</span>
                </div>
                <div>
                    <span style='font-size: 11px; color: #868e96;'>이격도</span>
                    <span style='font-size: 13px; font-weight: 600; margin-left: 4px;'>{disparity_status}</span>
                </div>
            </div>
        </div>"""
    
    kosdaq_html += """</div></details>"""
    
    st.markdown(kosdaq_html, unsafe_allow_html=True)
    
else:
    kosdaq_error_html = """<details style='background-color: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 0; margin-top: 16px;'><summary style='background-color: #f8f9fa; padding: 12px 16px; font-weight: 600; cursor: pointer; list-style: none; font-size: 15px;'>📈 코스닥 레버리지</summary><div style='padding: 16px; font-size: 0.9rem; color: #666;'>데이터가 부족합니다.</div></details>"""
    st.markdown(kosdaq_error_html, unsafe_allow_html=True)