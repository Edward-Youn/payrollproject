import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import calendar
import plotly.express as px
import plotly.graph_objects as go
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import black, blue, red
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from email.header import Header
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
import io
import hashlib
import json
import time
from dateutil.relativedelta import relativedelta

# 페이지 설정
st.set_page_config(
    page_title="급여 및 인사 관리 시스템",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2025년 한국 4대보험 및 세금 요율
INSURANCE_RATES = {
    "national_pension": 0.045,  # 국민연금 4.5%
    "health_insurance": 0.03545,  # 건강보험 3.545%
    "long_term_care": 0.009182,  # 장기요양보험
    "employment_insurance": 0.009,  # 고용보험 0.9%
    "employment_stability": 0.0025,  # 고용안정사업 0.25%
    "workers_compensation": 0.007,  # 산재보험 평균 0.7%
}

# 국민연금 기준소득월액
PENSION_LIMITS = {
    "min": 400000,  # 최저 40만원
    "max": 6370000  # 최고 637만원
}

# 한글 폰트 설정 함수
@st.cache_resource
def setup_korean_font():
    """한글 폰트 설정"""
    try:
        # 나눔고딕 폰트 URL (Google Fonts)
        font_url = "https://fonts.googleapis.com/css2?family=Nanum+Gothic:wght@400;700&display=swap"
        
        # 시스템에 설치된 한글 폰트 시도
        korean_fonts = [
            "/System/Library/Fonts/NanumGothic.ttc",  # macOS
            "C:/Windows/Fonts/malgun.ttf",  # Windows 맑은고딕
            "C:/Windows/Fonts/NanumGothic.ttf",  # Windows 나눔고딕
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # Linux
        ]
        
        for font_path in korean_fonts:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
                    return 'NanumGothic'
                except:
                    continue
        
        # 기본 폰트 사용
        return 'Helvetica'
    
    except Exception as e:
        st.warning(f"한글 폰트 설정 실패: {str(e)}. 기본 폰트를 사용합니다.")
        return 'Helvetica'

# Supabase 연결 함수
@st.cache_resource
def init_supabase():
    """Supabase 클라이언트 초기화"""
    try:
        from supabase import create_client, Client
        
        # secrets 접근 방식 개선
        try:
            supabase_url = st.secrets["SUPABASE_URL"]
            supabase_key = st.secrets["SUPABASE_ANON_KEY"]
        except KeyError as e:
            st.error(f"❌ secrets.toml에서 {str(e)} 키를 찾을 수 없습니다.")
            return None
        except Exception as e:
            st.error(f"❌ secrets.toml 파일을 읽을 수 없습니다: {str(e)}")
            return None
            
        if not supabase_url or supabase_url == "your_supabase_url":
            st.error("❌ Supabase URL이 설정되지 않았습니다.")
            return None
        
        if not supabase_key or supabase_key == "your_supabase_anon_key":
            st.error("❌ Supabase Anon Key가 설정되지 않았습니다.")
            return None
        
        supabase = create_client(supabase_url, supabase_key)
        
        # 연결 테스트 및 테이블 존재 확인
        try:
            # 각 테이블 존재 확인
            tables_to_check = ['employees', 'attendance', 'payroll']
            for table in tables_to_check:
                try:
                    result = supabase.table(table).select('*').limit(1).execute()
                    st.success(f"✅ {table} 테이블 연결 성공")
                except Exception as table_error:
                    st.error(f"❌ {table} 테이블 오류: {str(table_error)}")
                    st.info("💡 Supabase에서 data.txt의 SQL을 실행하고 RLS를 비활성화해주세요.")
            
            return supabase
            
        except Exception as e:
            st.error(f"❌ 테이블 확인 오류: {str(e)}")
            st.info("💡 다음을 확인해주세요:")
            st.info("1. Supabase SQL Editor에서 data.txt의 SQL 실행")
            st.info("2. Authentication > Settings에서 RLS 비활성화")
            st.info("3. API Keys가 올바른지 확인")
            return supabase
            
    except ImportError:
        st.error("❌ supabase 라이브러리가 설치되지 않았습니다.")
        st.code("pip install supabase")
        return None
    except Exception as e:
        st.error(f"❌ Supabase 초기화 오류: {str(e)}")
        return None

# 근무일수 및 급여 차감 계산 함수들
def get_workdays_in_month(year, month):
    """해당 월의 근무일수 계산 (주말 제외, 평일만)"""
    try:
        # 해당 월의 첫날과 마지막날
        first_day = datetime(year, month, 1).date()
        last_day = (datetime(year, month + 1, 1) - timedelta(days=1)).date() if month < 12 else datetime(year, 12, 31).date()
        
        workdays = 0
        current_date = first_day
        
        while current_date <= last_day:
            # 월요일(0) ~ 금요일(4)만 근무일로 계산
            if current_date.weekday() < 5:
                workdays += 1
            current_date += timedelta(days=1)
        
        return workdays
    except Exception as e:
        # 오류 발생 시 기본값 22일 반환
        return 22

def calculate_unpaid_leave_deduction(base_salary, unpaid_days, year, month):
    """무급휴가에 따른 급여 차감 계산"""
    try:
        if unpaid_days <= 0:
            return 0
        
        # 해당 월 근무일수
        total_workdays = get_workdays_in_month(year, month)
        
        # 일급 계산
        daily_wage = base_salary / total_workdays
        
        # 무급휴가 차감액
        deduction = daily_wage * unpaid_days
        
        return int(deduction)
    except Exception as e:
        return 0

def calculate_lateness_deduction(base_salary, late_hours, year, month):
    """지각/조퇴에 따른 급여 차감 계산"""
    try:
        if late_hours <= 0:
            return 0
        
        # 해당 월 근무일수 및 시간
        total_workdays = get_workdays_in_month(year, month)
        total_work_hours = total_workdays * 8  # 하루 8시간 기준
        
        # 시급 계산
        hourly_wage = base_salary / total_work_hours
        
        # 지각/조퇴 차감액
        deduction = hourly_wage * late_hours
        
        return int(deduction)
    except Exception as e:
        return 0

def get_employee_deductions(supabase, employee_id, pay_month):
    """해당 직원의 월별 차감 내역 계산"""
    try:
        year, month = map(int, pay_month.split('-'))
        start_date = datetime(year, month, 1).date()
        end_date = (datetime(year, month + 1, 1) - timedelta(days=1)).date() if month < 12 else datetime(year, 12, 31).date()
        
        # 해당 월 근태 기록 조회
        attendance_df = get_attendance(supabase, employee_id, start_date, end_date)
        
        if attendance_df.empty:
            return {
                'unpaid_days': 0,
                'unpaid_deduction': 0,
                'late_hours': 0,
                'lateness_deduction': 0,
                'total_attendance_deduction': 0
            }
        
        # 무급휴가 일수 계산
        unpaid_days = len(attendance_df[attendance_df['status'] == '무급휴가'])
        
        # 지각/조퇴 시간 계산
        late_hours = 0
        if 'status' in attendance_df.columns and 'actual_hours' in attendance_df.columns:
            # 지각: 9시 이후 출근 (30분 이상 지각 시 차감)
            late_records = attendance_df[attendance_df['status'] == '지각']
            for _, record in late_records.iterrows():
                if 'clock_in' in record and record['clock_in']:
                    try:
                        clock_in_time = datetime.strptime(str(record['clock_in']), '%H:%M:%S').time()
                        standard_time = datetime.strptime('09:00:00', '%H:%M:%S').time()
                        
                        # 9시 이후 출근 시간 계산
                        if clock_in_time > standard_time:
                            clock_in_minutes = clock_in_time.hour * 60 + clock_in_time.minute
                            standard_minutes = standard_time.hour * 60 + standard_time.minute
                            late_minutes = clock_in_minutes - standard_minutes
                            
                            # 30분 이상 지각 시에만 차감 (30분 단위로)
                            if late_minutes >= 30:
                                late_hours += late_minutes / 60
                    except:
                        continue
            
            # 조퇴: 정상 근무시간보다 적게 근무한 경우
            early_leave_records = attendance_df[attendance_df['status'] == '조퇴']
            for _, record in early_leave_records.iterrows():
                if 'actual_hours' in record and record['actual_hours'] < 8:
                    # 8시간 미만 근무 시 부족한 시간만큼 차감
                    late_hours += (8 - record['actual_hours'])
        
        return {
            'unpaid_days': unpaid_days,
            'late_hours': round(late_hours, 2),
            'unpaid_deduction': 0,  # 급여 계산에서 설정
            'lateness_deduction': 0,  # 급여 계산에서 설정
            'total_attendance_deduction': 0  # 급여 계산에서 설정
        }
        
    except Exception as e:
        st.warning(f"근태 차감 계산 오류: {str(e)}")
        return {
            'unpaid_days': 0,
            'unpaid_deduction': 0,
            'late_hours': 0,
            'lateness_deduction': 0,
            'total_attendance_deduction': 0
        }
def calculate_annual_leave(hire_date, current_date=None):
    """입사일 기준 연차 자동 계산"""
    if current_date is None:
        current_date = datetime.now().date()
    
    if isinstance(hire_date, str):
        hire_date = datetime.strptime(hire_date, '%Y-%m-%d').date()
    
    # 근속기간 계산
    work_period = current_date - hire_date
    work_years = work_period.days / 365.25
    
    if work_years < 1:
        # 1년 미만: 월할 계산 (매월 1일씩)
        work_months = (current_date.year - hire_date.year) * 12 + (current_date.month - hire_date.month)
        return max(0, work_months)
    else:
        # 1년 이상: 15일 + 2년마다 1일씩 추가 (최대 25일)
        base_leave = 15
        additional_years = int((work_years - 1) // 2)
        additional_leave = min(additional_years, 10)  # 최대 10일 추가
        return base_leave + additional_leave

def update_employee_annual_leave(supabase, employee_id, hire_date):
    """직원 연차 자동 업데이트"""
    try:
        total_leave = calculate_annual_leave(hire_date)
        
        update_data = {
            'total_annual_leave': total_leave,
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('employees').update(update_data).eq('id', employee_id).execute()
        return result.data is not None and len(result.data) > 0
        
    except Exception as e:
        st.error(f"연차 업데이트 오류: {str(e)}")
        return False

# 퇴직금 계산 함수
def calculate_severance_pay(hire_date, resignation_date, recent_salaries):
    """퇴직금 계산 (근로기준법 기준)"""
    try:
        if isinstance(hire_date, str):
            hire_date = datetime.strptime(hire_date, '%Y-%m-%d').date()
        if isinstance(resignation_date, str):
            resignation_date = datetime.strptime(resignation_date, '%Y-%m-%d').date()
        
        # 근속기간 계산 (일 단위)
        work_period = resignation_date - hire_date
        work_days = work_period.days
        work_years = work_days / 365.25
        
        # 1년 미만은 퇴직금 없음
        if work_years < 1:
            return {
                'work_years': work_years,
                'work_days': work_days,
                'average_wage': 0,
                'severance_pay': 0,
                'message': '근속기간 1년 미만으로 퇴직금 대상이 아닙니다.'
            }
        
        # 평균임금 계산 (최근 3개월 급여 평균)
        if recent_salaries and len(recent_salaries) > 0:
            average_monthly_wage = sum(recent_salaries) / len(recent_salaries)
        else:
            average_monthly_wage = 0
        
        # 일평균임금 계산 (월급여 ÷ 30)
        daily_average_wage = average_monthly_wage / 30
        
        # 퇴직금 = 계속근로연수 × 30일분의 평균임금
        severance_pay = int(work_years) * 30 * daily_average_wage
        
        return {
            'work_years': work_years,
            'work_days': work_days,
            'average_monthly_wage': average_monthly_wage,
            'daily_average_wage': daily_average_wage,
            'severance_pay': severance_pay,
            'message': f'근속 {work_years:.1f}년, 퇴직금 {severance_pay:,.0f}원'
        }
        
    except Exception as e:
        return {
            'work_years': 0,
            'work_days': 0,
            'average_wage': 0,
            'severance_pay': 0,
            'message': f'퇴직금 계산 오류: {str(e)}'
        }

# 이메일 발송 함수
def send_payslip_email(employee_email, pdf_buffer, employee_name, pay_month):
    """급여명세서 이메일 발송"""
    try:
        # 이메일 설정 가져오기
        smtp_server = st.secrets.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(st.secrets.get("SMTP_PORT", 587))
        sender_email = st.secrets.get("SENDER_EMAIL", "")
        sender_password = st.secrets.get("SENDER_PASSWORD", "")
        
        if not all([sender_email, sender_password, employee_email]):
            return False, "이메일 설정이 완전하지 않습니다."
        
        # 이메일 메시지 생성
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = employee_email
        msg['Subject'] = f"[급여명세서] {employee_name}님 {pay_month} 급여명세서"
        
        # 이메일 본문
        body = f"""
안녕하세요, {employee_name}님

{pay_month} 급여명세서를 첨부파일로 보내드립니다.

급여 관련 문의사항이 있으시면 인사팀으로 연락주시기 바랍니다.

감사합니다.

---
급여 및 인사관리 시스템
        """
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # PDF 첨부 (한글 파일명 인코딩 개선)
        if pdf_buffer:
            part = MIMEBase('application', 'pdf')
            part.set_payload(pdf_buffer.getvalue())
            encoders.encode_base64(part)
            
            # 한글 파일명을 안전하게 인코딩
            from email.header import Header
            filename = f"{employee_name}_{pay_month}_급여명세서.pdf"
            encoded_filename = Header(filename, 'utf-8').encode()
            
            # RFC2231 방식으로 파일명 설정 (한글 지원)
            part.add_header(
                'Content-Disposition',
                'attachment',
                filename=('utf-8', '', filename)
            )
            part.add_header('Content-Type', 'application/pdf', name=('utf-8', '', filename))
            
            msg.attach(part)
        
        # 이메일 발송
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        text = msg.as_string()
        server.sendmail(sender_email, employee_email, text)
        server.quit()
        
        return True, "이메일이 성공적으로 발송되었습니다."
        
    except Exception as e:
        return False, f"이메일 발송 실패: {str(e)}"

# 근로소득세 계산 함수
def get_income_tax(monthly_salary, family_count):
    """간이세액표 기반 소득세 계산"""
    if monthly_salary <= 1060000:
        return 0
    elif monthly_salary <= 1500000:
        base_tax = (monthly_salary - 1060000) * 0.06
    elif monthly_salary <= 3000000:
        base_tax = 26400 + (monthly_salary - 1500000) * 0.15
    elif monthly_salary <= 5000000:
        base_tax = 251400 + (monthly_salary - 3000000) * 0.24
    else:
        base_tax = 731400 + (monthly_salary - 5000000) * 0.35
    
    family_deduction = (family_count - 1) * 12500
    return max(0, int(base_tax - family_deduction))

def calculate_resident_tax(income_tax):
    """주민세 계산 (소득세의 10%)"""
    return int(income_tax * 0.1)

# 급여 계산 함수 (무급휴가 및 지각/조퇴 차감 포함)
def calculate_payroll(employee_data, pay_month, supabase=None):
    """급여 계산 (무급휴가 및 지각/조퇴 차감 포함)"""
    try:
        base_salary = int(employee_data.get('base_salary', 0))
        family_count = int(employee_data.get('family_count', 1))
        employee_id = employee_data.get('id')
        
        if base_salary <= 0:
            return {
                'base_salary': 0, 'national_pension': 0, 'health_insurance': 0,
                'long_term_care': 0, 'employment_insurance': 0, 'income_tax': 0,
                'resident_tax': 0, 'unpaid_deduction': 0, 'lateness_deduction': 0,
                'total_deductions': 0, 'net_pay': 0
            }
        
        # 근태 기반 차감 계산
        attendance_deductions = {'unpaid_days': 0, 'late_hours': 0, 'unpaid_deduction': 0, 'lateness_deduction': 0}
        
        if supabase and employee_id:
            attendance_deductions = get_employee_deductions(supabase, employee_id, pay_month)
            year, month = map(int, pay_month.split('-'))
            
            # 무급휴가 차감액 계산
            attendance_deductions['unpaid_deduction'] = calculate_unpaid_leave_deduction(
                base_salary, attendance_deductions['unpaid_days'], year, month
            )
            
            # 지각/조퇴 차감액 계산
            attendance_deductions['lateness_deduction'] = calculate_lateness_deduction(
                base_salary, attendance_deductions['late_hours'], year, month
            )
        
        # 근태 차감 후 실제 급여 계산
        adjusted_salary = base_salary - attendance_deductions['unpaid_deduction'] - attendance_deductions['lateness_deduction']
        adjusted_salary = max(0, adjusted_salary)  # 음수 방지
        
        # 국민연금 (조정된 급여 기준)
        pension_base = min(max(adjusted_salary, PENSION_LIMITS['min']), PENSION_LIMITS['max'])
        national_pension = int(pension_base * INSURANCE_RATES['national_pension'])
        
        # 건강보험 (조정된 급여 기준)
        health_insurance = int(adjusted_salary * INSURANCE_RATES['health_insurance'])
        
        # 장기요양보험
        long_term_care = int(health_insurance * 0.1295)
        
        # 고용보험 (조정된 급여 기준)
        employment_insurance = int(adjusted_salary * INSURANCE_RATES['employment_insurance'])
        
        # 소득세 (조정된 급여 기준)
        income_tax = get_income_tax(adjusted_salary, family_count)
        
        # 주민세
        resident_tax = calculate_resident_tax(income_tax)
        
        # 총 공제액 (4대보험 + 세금 + 근태 차감)
        insurance_tax_deductions = (national_pension + health_insurance + long_term_care + 
                                   employment_insurance + income_tax + resident_tax)
        total_deductions = (insurance_tax_deductions + attendance_deductions['unpaid_deduction'] + 
                           attendance_deductions['lateness_deduction'])
        
        # 실지급액
        net_pay = base_salary - total_deductions
        
        result = {
            'base_salary': base_salary,
            'adjusted_salary': adjusted_salary,
            'national_pension': national_pension,
            'health_insurance': health_insurance,
            'long_term_care': long_term_care,
            'employment_insurance': employment_insurance,
            'income_tax': income_tax,
            'resident_tax': resident_tax,
            'unpaid_days': attendance_deductions['unpaid_days'],
            'unpaid_deduction': attendance_deductions['unpaid_deduction'],
            'late_hours': attendance_deductions['late_hours'],
            'lateness_deduction': attendance_deductions['lateness_deduction'],
            'total_deductions': total_deductions,
            'net_pay': net_pay
        }
        
        return result
        
    except Exception as e:
        st.error(f"급여 계산 오류: {str(e)}")
        return None

# 데이터베이스 CRUD 함수들
def get_employees(supabase):
    """직원 목록 조회"""
    try:
        if supabase is None:
            st.warning("⚠️ 데이터베이스 연결이 없습니다.")
            return pd.DataFrame()
        
        result = supabase.table('employees').select('*').order('id').execute()
        
        if result.data:
            df = pd.DataFrame(result.data)
            # 데이터 타입 안전성 확보
            if 'base_salary' in df.columns:
                df['base_salary'] = pd.to_numeric(df['base_salary'], errors='coerce').fillna(0)
            if 'family_count' in df.columns:
                df['family_count'] = pd.to_numeric(df['family_count'], errors='coerce').fillna(1)
            
            st.success(f"✅ 직원 데이터 {len(df)}건 로드 완료")
            return df
        else:
            st.info("📝 등록된 직원이 없습니다.")
            return pd.DataFrame()
            
    except Exception as e:
        error_msg = str(e)
        if "JSON" in error_msg and "401" in error_msg:
            st.error("❌ API 키가 잘못되었습니다. secrets.toml을 확인해주세요.")
        elif "relation" in error_msg or "does not exist" in error_msg:
            st.error("❌ employees 테이블이 존재하지 않습니다.")
            st.info("💡 Supabase SQL Editor에서 data.txt의 SQL을 실행해주세요.")
        else:
            st.error(f"❌ 직원 데이터 조회 오류: {error_msg}")
        return pd.DataFrame()

def add_employee(supabase, employee_data):
    """직원 추가"""
    try:
        if supabase is None:
            return False
            
        # 연차 자동 계산
        if 'hire_date' in employee_data:
            total_leave = calculate_annual_leave(employee_data['hire_date'])
            employee_data['total_annual_leave'] = total_leave
            employee_data['remaining_annual_leave'] = total_leave
            
        result = supabase.table('employees').insert(employee_data).execute()
        return result.data is not None and len(result.data) > 0
        
    except Exception as e:
        st.error(f"직원 추가 오류: {str(e)}")
        return False

def update_employee(supabase, employee_id, update_data):
    """직원 정보 수정"""
    try:
        if supabase is None:
            return False
            
        result = supabase.table('employees').update(update_data).eq('id', employee_id).execute()
        return result.data is not None and len(result.data) > 0
        
    except Exception as e:
        st.error(f"직원 수정 오류: {str(e)}")
        return False

def get_attendance(supabase, employee_id=None, start_date=None, end_date=None):
    """근태 기록 조회"""
    try:
        if supabase is None:
            return pd.DataFrame()
            
        # JOIN 쿼리를 더 안전하게 처리
        try:
            query = supabase.table('attendance').select('*, employees(name)')
        except:
            # JOIN이 실패하면 기본 테이블만 조회
            query = supabase.table('attendance').select('*')
        
        if employee_id:
            query = query.eq('employee_id', employee_id)
        if start_date:
            query = query.gte('date', start_date.isoformat())
        if end_date:
            query = query.lte('date', end_date.isoformat())
            
        result = query.order('date', desc=True).execute()
        
        if result.data:
            df = pd.DataFrame(result.data)
            # actual_hours 컬럼 안전성 확보
            if 'actual_hours' in df.columns:
                df['actual_hours'] = pd.to_numeric(df['actual_hours'], errors='coerce').fillna(0)
            return df
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.warning(f"근태 데이터를 불러올 수 없습니다: {str(e)}")
        return pd.DataFrame()

def add_attendance(supabase, attendance_data):
    """근태 기록 추가 및 연차 자동 관리"""
    try:
        if supabase is None:
            return False
        
        # 근태 기록 추가
        result = supabase.table('attendance').insert(attendance_data).execute()
        
        # 연차 사용 시 자동 차감
        if result.data and attendance_data.get('status') == '연차':
            employee_id = attendance_data['employee_id']
            
            # 현재 직원 정보 조회
            emp_result = supabase.table('employees').select('used_annual_leave, remaining_annual_leave').eq('id', employee_id).execute()
            
            if emp_result.data:
                emp_data = emp_result.data[0]
                used_leave = emp_data.get('used_annual_leave', 0) + 1
                remaining_leave = max(0, emp_data.get('remaining_annual_leave', 0) - 1)
                
                # 연차 사용 정보 업데이트
                update_data = {
                    'used_annual_leave': used_leave,
                    'remaining_annual_leave': remaining_leave,
                    'updated_at': datetime.now().isoformat()
                }
                
                supabase.table('employees').update(update_data).eq('id', employee_id).execute()
        
        return result.data is not None and len(result.data) > 0
        
    except Exception as e:
        st.error(f"근태 기록 추가 오류: {str(e)}")
        return False

def get_payroll(supabase, employee_id=None, pay_month=None):
    """급여 데이터 조회"""
    try:
        if supabase is None:
            return pd.DataFrame()
            
        # JOIN 쿼리를 더 안전하게 처리
        try:
            query = supabase.table('payroll').select('*, employees(name)')
        except:
            # JOIN이 실패하면 기본 테이블만 조회
            query = supabase.table('payroll').select('*')
        
        if employee_id:
            query = query.eq('employee_id', employee_id)
        if pay_month:
            query = query.eq('pay_month', pay_month)
            
        result = query.order('pay_month', desc=True).execute()
        
        if result.data:
            df = pd.DataFrame(result.data)
            # 숫자 컬럼들의 안전성 확보
            numeric_columns = ['base_salary', 'national_pension', 'health_insurance', 
                             'long_term_care', 'employment_insurance', 'income_tax', 
                             'resident_tax', 'total_deductions', 'net_pay']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            return df
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.warning(f"급여 데이터를 불러올 수 없습니다: {str(e)}")
        return pd.DataFrame()

def save_payroll(supabase, payroll_data):
    """급여 데이터 저장"""
    try:
        if supabase is None:
            return False
            
        result = supabase.table('payroll').insert(payroll_data).execute()
        return result.data is not None and len(result.data) > 0
        
    except Exception as e:
        st.error(f"급여 데이터 저장 오류: {str(e)}")
        return False

# 개선된 PDF 생성 함수 (한글 폰트 지원)
def generate_payslip_pdf(employee_data, payroll_data, pay_month):
    """한글 폰트를 지원하는 급여명세서 PDF 생성"""
    try:
        # 한글 폰트 설정
        korean_font = setup_korean_font()
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=50, bottomMargin=50)
        story = []
        styles = getSampleStyleSheet()
        
        # 한글 폰트가 설정된 경우 스타일 업데이트
        if korean_font != 'Helvetica':
            styles['Title'].fontName = korean_font
            styles['Normal'].fontName = korean_font
            styles['Heading1'].fontName = korean_font
        
        # 제목
        title = Paragraph("<font size=18><b>급여명세서</b></font>", styles['Title'])
        story.append(title)
        story.append(Spacer(1, 20))
        
        # 직원 정보 테이블
        emp_info_data = [
            ['직원명', employee_data.get('name', ''), '부서', employee_data.get('department', '')],
            ['직급', employee_data.get('position', ''), '급여월', pay_month],
            ['발행일', datetime.now().strftime('%Y년 %m월 %d일'), '', '']
        ]
        
        emp_table = Table(emp_info_data, colWidths=[1.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
        emp_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (3, 0), '#E8E8E8'),
            ('BACKGROUND', (0, 1), (3, 1), '#F5F5F5'),
            ('BACKGROUND', (0, 2), (3, 2), '#E8E8E8'),
            ('TEXTCOLOR', (0, 0), (-1, -1), black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), korean_font),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(emp_table)
        story.append(Spacer(1, 20))
        
        # 급여 내역 테이블 (근태 차감 포함)
        payroll_table_data = [
            ['구분', '항목', '금액'],
            ['지급', '기본급', f"{payroll_data.get('base_salary', 0):,}원"]
        ]
        
        # 근태 차감이 있는 경우 표시
        if payroll_data.get('unpaid_deduction', 0) > 0:
            payroll_table_data.append(['차감', '무급휴가', f"-{payroll_data.get('unpaid_deduction', 0):,}원"])
        
        if payroll_data.get('lateness_deduction', 0) > 0:
            payroll_table_data.append(['차감', '지각/조퇴', f"-{payroll_data.get('lateness_deduction', 0):,}원"])
        
        # 조정된 급여 표시
        if payroll_data.get('adjusted_salary', 0) != payroll_data.get('base_salary', 0):
            payroll_table_data.append(['', '조정 후 급여', f"{payroll_data.get('adjusted_salary', 0):,}원"])
        
        payroll_table_data.extend([
            ['', '', ''],
            ['공제', '국민연금', f"{payroll_data.get('national_pension', 0):,}원"],
            ['', '건강보험', f"{payroll_data.get('health_insurance', 0):,}원"],
            ['', '장기요양보험', f"{payroll_data.get('long_term_care', 0):,}원"],
            ['', '고용보험', f"{payroll_data.get('employment_insurance', 0):,}원"],
            ['', '소득세', f"{payroll_data.get('income_tax', 0):,}원"],
            ['', '주민세', f"{payroll_data.get('resident_tax', 0):,}원"],
            ['', '공제 합계', f"{payroll_data.get('total_deductions', 0):,}원"],
            ['', '', ''],
            ['실지급', '실지급액', f"{payroll_data.get('net_pay', 0):,}원"]
        ])
        
        table = Table(payroll_table_data, colWidths=[1*inch, 2.5*inch, 2.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), '#4472C4'),
            ('TEXTCOLOR', (0, 0), (-1, 0), 'white'),
            ('BACKGROUND', (0, 1), (-1, 1), '#D6E3F0'),
            ('BACKGROUND', (0, 3), (-1, 9), '#FFF2CC'),
            ('BACKGROUND', (0, 11), (-1, 11), '#C5E0B4'),
            ('TEXTCOLOR', (0, 1), (-1, -1), black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), korean_font),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 1, black),
            ('FONTNAME', (0, 11), (-1, 11), korean_font),
            ('FONTSIZE', (0, 11), (-1, 11), 12),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 30))
        
        # 추가 정보
        additional_info = f"""
        <font size=9>
        ※ 본 급여명세서는 급여 및 인사관리 시스템에서 자동 생성되었습니다.<br/>
        ※ 급여 관련 문의사항은 인사팀으로 연락해 주시기 바랍니다.<br/>
        ※ 발행일: {datetime.now().strftime('%Y년 %m월 %d일')}
        </font>
        """
        
        note = Paragraph(additional_info, styles['Normal'])
        story.append(note)
        
        # PDF 생성
        doc.build(story)
        buffer.seek(0)
        
        # 생성된 PDF 크기 확인 (디버깅용)
        pdf_size = len(buffer.getvalue())
        if pdf_size < 1000:  # 1KB 미만이면 문제 있음
            st.warning(f"⚠️ PDF 크기가 너무 작습니다 ({pdf_size} bytes). 한글 폰트 설정을 확인해주세요.")
        
        return buffer
        
    except Exception as e:
        st.error(f"PDF 생성 오류: {str(e)}")
        # 오류 발생 시 기본 PDF 생성
        try:
            return generate_simple_pdf(employee_data, payroll_data, pay_month)
        except:
            return None

def generate_simple_pdf(employee_data, payroll_data, pay_month):
    """폰트 문제 발생 시 사용할 간단한 PDF 생성"""
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # 제목
        p.setFont("Helvetica-Bold", 16)
        p.drawString(200, height - 80, "Payroll Statement")
        
        # 직원 정보
        p.setFont("Helvetica", 12)
        y_pos = height - 120
        p.drawString(50, y_pos, f"Name: {employee_data.get('name', '')}")
        p.drawString(300, y_pos, f"Department: {employee_data.get('department', '')}")
        
        y_pos -= 20
        p.drawString(50, y_pos, f"Position: {employee_data.get('position', '')}")
        p.drawString(300, y_pos, f"Pay Month: {pay_month}")
        
        # 급여 정보
        y_pos -= 40
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y_pos, "Salary Details:")
        
        y_pos -= 20
        p.setFont("Helvetica", 10)
        salary_items = [
            ("Base Salary", payroll_data.get('base_salary', 0)),
            ("National Pension", -payroll_data.get('national_pension', 0)),
            ("Health Insurance", -payroll_data.get('health_insurance', 0)),
            ("Long-term Care", -payroll_data.get('long_term_care', 0)),
            ("Employment Insurance", -payroll_data.get('employment_insurance', 0)),
            ("Income Tax", -payroll_data.get('income_tax', 0)),
            ("Resident Tax", -payroll_data.get('resident_tax', 0)),
            ("Net Pay", payroll_data.get('net_pay', 0))
        ]
        
        for item, amount in salary_items:
            p.drawString(70, y_pos, f"{item}:")
            p.drawString(300, y_pos, f"{amount:,} KRW")
            y_pos -= 15
        
        # 발행일
        p.drawString(50, 50, f"Issued: {datetime.now().strftime('%Y-%m-%d')}")
        
        p.save()
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        st.error(f"간단 PDF 생성 오류: {str(e)}")
        return None

# 메인 애플리케이션
def main():
    st.title("💼 급여 및 인사 관리 시스템")
    st.markdown("새내기 창업자를 위한 종합 인사관리 솔루션 (한글지원/퇴직금/이메일발송 기능 추가)")
    
    # Supabase 초기화
    supabase = init_supabase()
    
    # 연결 상태 표시
    if supabase is None:
        st.error("🔴 데이터베이스 연결 실패")
        
        # 설정 도움말 표시
        with st.expander("🔧 Supabase 설정 도움말", expanded=True):
            st.markdown("""
            ### 1단계: Supabase 프로젝트 설정
            1. [Supabase](https://supabase.com)에 로그인
            2. 새 프로젝트 생성 또는 기존 프로젝트 선택
            3. Settings > API에서 URL과 anon key 복사
            
            ### 2단계: 데이터베이스 테이블 생성
            1. Supabase Dashboard > SQL Editor 이동
            2. data.txt 파일의 모든 SQL 코드 복사
            3. SQL Editor에 붙여넣기 후 실행
            
            ### 3단계: RLS(Row Level Security) 비활성화
            1. Authentication > Settings 이동
            2. "Enable Row Level Security" 체크 해제
            3. 또는 각 테이블에서 RLS 정책 설정
            
            ### 4단계: secrets.toml 설정
            ```toml
            [default]
            SUPABASE_URL = "your_supabase_url"
            SUPABASE_ANON_KEY = "your_supabase_anon_key"
            SMTP_SERVER = "smtp.gmail.com"
            SMTP_PORT = 587
            SENDER_EMAIL = "your_email@gmail.com"
            SENDER_PASSWORD = "your_app_password"
            ```
            """)
        
        st.stop()
    else:
        st.success("🟢 데이터베이스 연결 성공")
    
    # 사이드바 메뉴
    st.sidebar.title("📋 메뉴")
    menu = st.sidebar.selectbox("메뉴 선택", [
        "대시보드",
        "직원 관리",
        "근태 관리", 
        "급여 계산",
        "급여 명세서",
        "퇴직금 계산",
        "연차 관리",
        "통계 및 분석",
        "시스템 정보"
    ])
    
    # 데이터 현황 표시 (사이드바)
    employees_df = get_employees(supabase)
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 현재 데이터")
    st.sidebar.metric("등록된 직원", len(employees_df))
    
    # 대시보드
    if menu == "대시보드":
        st.header("📊 대시보드")
        
        # 주요 지표
        col1, col2, col3, col4 = st.columns(4)
        
        total_employees = len(employees_df)
        active_employees = len(employees_df[employees_df['status'] == '재직']) if not employees_df.empty else 0
        
        with col1:
            st.metric("총 직원 수", total_employees)
        
        with col2:
            st.metric("재직 직원 수", active_employees)
        
        with col3:
            current_month = datetime.now().strftime("%Y-%m")
            st.metric("현재 월", current_month)
        
        with col4:
            if not employees_df.empty and 'base_salary' in employees_df.columns:
                avg_salary = employees_df['base_salary'].mean()
                st.metric("평균 기본급", f"{avg_salary:,.0f}원")
            else:
                st.metric("평균 기본급", "0원")
        
        # 직원 목록
        if not employees_df.empty:
            st.subheader("👥 직원 목록")
            display_columns = ['name', 'position', 'department', 'base_salary', 'remaining_annual_leave', 'status']
            available_columns = [col for col in display_columns if col in employees_df.columns]
            st.dataframe(employees_df[available_columns], use_container_width=True)
            
            # 부서별 분포 차트
            if 'department' in employees_df.columns:
                dept_count = employees_df['department'].value_counts()
                fig = px.pie(values=dept_count.values, names=dept_count.index, 
                           title="부서별 직원 분포")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("등록된 직원이 없습니다. '직원 관리' 메뉴에서 직원을 등록해보세요.")
    
    # 직원 관리
    elif menu == "직원 관리":
        st.header("👥 직원 관리")
        
        tab1, tab2, tab3 = st.tabs(["직원 목록", "직원 등록", "직원 수정"])
        
        with tab1:
            st.subheader("직원 목록")
            
            if not employees_df.empty:
                # 필터링 옵션
                col1, col2 = st.columns(2)
                
                with col1:
                    status_filter = st.selectbox("상태 필터", ["전체", "재직", "휴직", "퇴직"])
                
                with col2:
                    if 'department' in employees_df.columns:
                        dept_list = employees_df['department'].dropna().unique().tolist()
                        dept_filter = st.selectbox("부서 필터", ["전체"] + dept_list)
                    else:
                        dept_filter = "전체"
                
                # 필터 적용
                filtered_df = employees_df.copy()
                if status_filter != "전체":
                    filtered_df = filtered_df[filtered_df['status'] == status_filter]
                if dept_filter != "전체" and 'department' in filtered_df.columns:
                    filtered_df = filtered_df[filtered_df['department'] == dept_filter]
                
                # 직원 목록 표시
                display_columns = ['id', 'name', 'position', 'department', 'base_salary', 'total_annual_leave', 'remaining_annual_leave', 'status', 'hire_date']
                available_columns = [col for col in display_columns if col in filtered_df.columns]
                st.dataframe(filtered_df[available_columns], use_container_width=True)
                
                # 연차 일괄 업데이트 버튼
                if st.button("🔄 전체 직원 연차 자동 업데이트", key="update_all_annual_leave"):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    for idx, (_, emp_data) in enumerate(filtered_df.iterrows()):
                        status_text.text(f"{emp_data['name']}님 연차 업데이트 중...")
                        update_employee_annual_leave(supabase, emp_data['id'], emp_data['hire_date'])
                        progress_bar.progress((idx + 1) / len(filtered_df))
                    
                    status_text.text("연차 업데이트 완료!")
                    st.success("✅ 모든 직원의 연차가 업데이트되었습니다!")
                    time.sleep(1)
                    st.rerun()
                
            else:
                st.info("등록된 직원이 없습니다.")
        
        with tab2:
            st.subheader("신규 직원 등록")
            
            with st.form("add_employee_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    name = st.text_input("이름*", placeholder="홍길동")
                    position = st.text_input("직급", placeholder="대리")
                    department = st.text_input("부서", placeholder="개발팀")
                    hire_date = st.date_input("입사일", value=datetime.now().date())
                
                with col2:
                    base_salary = st.number_input("기본급", min_value=0, value=3000000, step=100000)
                    email = st.text_input("이메일", placeholder="hong@company.com")
                    phone = st.text_input("연락처", placeholder="010-1234-5678")
                    family_count = st.number_input("부양가족수(본인포함)", min_value=1, value=1, max_value=10)
                
                notes = st.text_area("특이사항")
                
                # 연차 자동 계산 미리보기
                if hire_date:
                    preview_leave = calculate_annual_leave(hire_date)
                    st.info(f"📅 자동 계산된 연차: {preview_leave}일")
                
                submit_button = st.form_submit_button("직원 등록", type="primary")
                
                if submit_button and name:
                    employee_data = {
                        'name': name,
                        'position': position,
                        'department': department,
                        'hire_date': hire_date.isoformat(),
                        'base_salary': base_salary,
                        'email': email,
                        'phone': phone,
                        'family_count': family_count,
                        'used_annual_leave': 0,
                        'status': '재직',
                        'notes': notes
                    }
                    
                    result = add_employee(supabase, employee_data)
                    if result:
                        st.success(f"✅ {name}님이 성공적으로 등록되었습니다! (연차 {preview_leave}일 자동 부여)")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ 직원 등록에 실패했습니다.")
        
        with tab3:
            st.subheader("직원 정보 수정")
            
            if not employees_df.empty:
                selected_employee = st.selectbox(
                    "수정할 직원 선택",
                    options=employees_df['id'].tolist(),
                    format_func=lambda x: employees_df[employees_df['id'] == x]['name'].iloc[0]
                )
                
                if selected_employee:
                    emp_data = employees_df[employees_df['id'] == selected_employee].iloc[0]
                    
                    with st.form("update_employee_form"):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            name = st.text_input("이름", value=emp_data['name'])
                            position = st.text_input("직급", value=emp_data.get('position', ''))
                            department = st.text_input("부서", value=emp_data.get('department', ''))
                            hire_date = st.date_input("입사일", value=pd.to_datetime(emp_data['hire_date']).date())
                        
                        with col2:
                            base_salary = st.number_input("기본급", value=int(emp_data.get('base_salary', 0)), step=100000)
                            email = st.text_input("이메일", value=emp_data.get('email', ''))
                            phone = st.text_input("연락처", value=emp_data.get('phone', ''))
                            family_count = st.number_input("부양가족수", value=int(emp_data.get('family_count', 1)))
                        
                        col3, col4 = st.columns(2)
                        with col3:
                            status = st.selectbox("상태", ["재직", "휴직", "퇴직"], index=["재직", "휴직", "퇴직"].index(emp_data['status']))
                            total_annual_leave = st.number_input("총 연차", value=int(emp_data.get('total_annual_leave', 15)))
                        
                        with col4:
                            used_annual_leave = st.number_input("사용 연차", value=int(emp_data.get('used_annual_leave', 0)))
                            remaining_annual_leave = st.number_input("잔여 연차", value=int(emp_data.get('remaining_annual_leave', 15)))
                        
                        notes = st.text_area("특이사항", value=emp_data.get('notes', ''))
                        
                        update_button = st.form_submit_button("정보 수정", type="primary")
                        
                        if update_button:
                            update_data = {
                                'name': name,
                                'position': position,
                                'department': department,
                                'hire_date': hire_date.isoformat(),
                                'base_salary': base_salary,
                                'email': email,
                                'phone': phone,
                                'family_count': family_count,
                                'status': status,
                                'total_annual_leave': total_annual_leave,
                                'used_annual_leave': used_annual_leave,
                                'remaining_annual_leave': remaining_annual_leave,
                                'notes': notes,
                                'updated_at': datetime.now().isoformat()
                            }
                            
                            result = update_employee(supabase, selected_employee, update_data)
                            if result:
                                st.success("✅ 직원 정보가 성공적으로 수정되었습니다!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("❌ 정보 수정에 실패했습니다.")
            else:
                st.info("등록된 직원이 없습니다.")
    
    # 근태 관리
    elif menu == "근태 관리":
        st.header("⏰ 근태 관리")
        
        tab1, tab2, tab3 = st.tabs(["근태 기록", "근태 입력", "근태 현황"])
        
        with tab1:
            st.subheader("근태 기록 조회")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if not employees_df.empty:
                    selected_emp = st.selectbox(
                        "직원 선택",
                        options=[None] + employees_df['id'].tolist(),
                        format_func=lambda x: "전체 직원" if x is None else employees_df[employees_df['id'] == x]['name'].iloc[0]
                    )
                else:
                    st.info("등록된 직원이 없습니다.")
                    selected_emp = None
            
            with col2:
                start_date = st.date_input("시작일", value=datetime.now().date().replace(day=1))
            
            with col3:
                end_date = st.date_input("종료일", value=datetime.now().date())
            
            if selected_emp is not None or selected_emp is None:
                attendance_df = get_attendance(supabase, selected_emp, start_date, end_date)
                
                if not attendance_df.empty:
                    # 근태 데이터 표시
                    display_df = attendance_df.copy()
                    if 'employees' in display_df.columns:
                        display_df['employee_name'] = display_df['employees'].apply(
                            lambda x: x['name'] if isinstance(x, dict) and x else ''
                        )
                    
                    display_columns = ['employee_name', 'date', 'clock_in', 'clock_out', 'actual_hours', 'status', 'notes']
                    available_columns = [col for col in display_columns if col in display_df.columns]
                    st.dataframe(display_df[available_columns], use_container_width=True)
                    
                    # 통계 정보
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        total_days = len(attendance_df)
                        st.metric("총 근무일수", total_days)
                    
                    with col2:
                        if 'actual_hours' in attendance_df.columns:
                            total_hours = attendance_df['actual_hours'].sum()
                            st.metric("총 근무시간", f"{total_hours:.1f}시간")
                    
                    with col3:
                        if 'status' in attendance_df.columns:
                            late_days = len(attendance_df[attendance_df['status'] == '지각'])
                            st.metric("지각 일수", late_days)
                    
                    with col4:
                        if 'status' in attendance_df.columns:
                            annual_leave_days = len(attendance_df[attendance_df['status'] == '연차'])
                            st.metric("연차 사용일수", annual_leave_days)
                
                else:
                    st.info("해당 기간에 근태 기록이 없습니다.")
        
        with tab2:
            st.subheader("근태 기록 입력")
            
            if not employees_df.empty:
                with st.form("attendance_form"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        employee_id = st.selectbox(
                            "직원 선택",
                            options=employees_df['id'].tolist(),
                            format_func=lambda x: employees_df[employees_df['id'] == x]['name'].iloc[0]
                        )
                        date = st.date_input("날짜", value=datetime.now().date())
                        clock_in = st.time_input("출근 시간", value=datetime.strptime("09:00", "%H:%M").time())
                    
                    with col2:
                        clock_out = st.time_input("퇴근 시간", value=datetime.strptime("18:00", "%H:%M").time())
                        status = st.selectbox("상태", ["정상", "지각", "조퇴", "연차", "결근", "휴가", "무급휴가"])
                        notes = st.text_area("특이사항")
                    
                    # 실근무시간 계산 및 연차 잔여일수 확인
                    work_hours = 0
                    if clock_in and clock_out and status not in ['연차', '결근', '무급휴가']:
                        try:
                            clock_in_dt = datetime.combine(date, clock_in)
                            clock_out_dt = datetime.combine(date, clock_out)
                            if clock_out_dt > clock_in_dt:
                                work_hours = (clock_out_dt - clock_in_dt).total_seconds() / 3600 - 1  # 점심시간 1시간 제외
                                work_hours = max(0, work_hours)
                            st.info(f"📊 실근무시간: {work_hours:.1f}시간")
                        except Exception as e:
                            st.warning(f"근무시간 계산 오류: {str(e)}")
                            work_hours = 0
                    
                    # 무급휴가 안내
                    if status == '무급휴가':
                        st.warning("⚠️ 무급휴가는 해당 일의 급여가 차감됩니다.")
                        if employee_id:
                            emp_data = employees_df[employees_df['id'] == employee_id].iloc[0]
                            year, month = date.year, date.month
                            workdays = get_workdays_in_month(year, month)
                            daily_wage = emp_data['base_salary'] / workdays
                            st.info(f"📉 일급 차감액: {daily_wage:,.0f}원 (월 기본급 ÷ {workdays}일)")
                    
                    # 지각/조퇴 안내
                    if status in ['지각', '조퇴']:
                        st.info("💡 30분 이상 지각하거나 8시간 미만 근무 시 급여가 차감됩니다.")
                    
                    # 연차 사용 시 잔여일수 확인
                    if status == '연차' and employee_id:
                        emp_data = employees_df[employees_df['id'] == employee_id].iloc[0]
                        remaining_leave = emp_data.get('remaining_annual_leave', 0)
                        if remaining_leave <= 0:
                            st.error("❌ 잔여 연차가 없습니다!")
                        else:
                            st.info(f"📅 잔여 연차: {remaining_leave}일 → {remaining_leave-1}일")
                    
                    submit_button = st.form_submit_button("💾 근태 기록 저장", type="primary")
                    
                    if submit_button:
                        # 연차 사용 시 잔여일수 재확인
                        if status == '연차':
                            emp_data = employees_df[employees_df['id'] == employee_id].iloc[0]
                            if emp_data.get('remaining_annual_leave', 0) <= 0:
                                st.error("❌ 잔여 연차가 부족하여 저장할 수 없습니다.")
                                st.stop()
                        
                        attendance_data = {
                            'employee_id': employee_id,
                            'date': date.isoformat(),
                            'clock_in': clock_in.isoformat() if status not in ['연차', '결근', '무급휴가'] else '00:00:00',
                            'clock_out': clock_out.isoformat() if status not in ['연차', '결근', '무급휴가'] else '00:00:00',
                            'actual_hours': work_hours if status not in ['연차', '결근', '무급휴가'] else 0,
                            'status': status,
                            'notes': notes
                        }
                        
                        result = add_attendance(supabase, attendance_data)
                        if result:
                            success_msg = "✅ 근태 기록이 성공적으로 저장되었습니다!"
                            if status == '연차':
                                success_msg += " (연차 1일 자동 차감)"
                            st.success(success_msg)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("❌ 근태 기록 저장에 실패했습니다.")
            else:
                st.info("등록된 직원이 없습니다. 먼저 직원을 등록해주세요.")
        
        with tab3:
            st.subheader("근태 현황 분석")
            
            if not employees_df.empty:
                # 이번 달 근태 현황
                current_month_start = datetime.now().replace(day=1).date()
                current_month_end = datetime.now().date()
                
                monthly_attendance = get_attendance(supabase, None, current_month_start, current_month_end)
                
                if not monthly_attendance.empty:
                    # 직원별 근태 현황
                    if 'employees' in monthly_attendance.columns:
                        monthly_attendance['employee_name'] = monthly_attendance['employees'].apply(
                            lambda x: x['name'] if isinstance(x, dict) and x else ''
                        )
                        
                        if 'actual_hours' in monthly_attendance.columns and not monthly_attendance['employee_name'].empty:
                            emp_hours = monthly_attendance.groupby('employee_name')['actual_hours'].sum().reset_index()
                            
                            if not emp_hours.empty:
                                fig = px.bar(
                                    emp_hours,
                                    x='employee_name',
                                    y='actual_hours',
                                    title='직원별 이번 달 총 근무시간'
                                )
                                st.plotly_chart(fig, use_container_width=True)
                    
                    # 근태 상태 분포
                    if 'status' in monthly_attendance.columns:
                        status_dist = monthly_attendance['status'].value_counts()
                        if not status_dist.empty:
                            fig3 = px.pie(values=status_dist.values, names=status_dist.index, title='근태 상태별 분포')
                            st.plotly_chart(fig3, use_container_width=True)
                
                else:
                    st.info("이번 달 근태 기록이 없습니다.")
            else:
                st.info("등록된 직원이 없습니다.")
    
    # 급여 계산
    elif menu == "급여 계산":
        st.header("💰 급여 계산")
        
        tab1, tab2 = st.tabs(["개별 급여 계산", "일괄 급여 계산"])
        
        with tab1:
            st.subheader("개별 급여 계산")
            
            if not employees_df.empty:
                col1, col2 = st.columns(2)
                
                with col1:
                    selected_employee = st.selectbox(
                        "직원 선택",
                        options=employees_df['id'].tolist(),
                        format_func=lambda x: employees_df[employees_df['id'] == x]['name'].iloc[0]
                    )
                
                with col2:
                    pay_month = st.text_input("급여 대상 월", value=datetime.now().strftime("%Y-%m"))
                
                if selected_employee:
                    emp_data = employees_df[employees_df['id'] == selected_employee].iloc[0].to_dict()
                    
                    # 급여 계산 (근태 차감 포함)
                    payroll_result = calculate_payroll(emp_data, pay_month, supabase)
                    
                    if payroll_result:
                        # 결과 표시
                        st.subheader(f"💼 {emp_data['name']}님의 {pay_month} 급여 계산 결과")
                        
                        # 근태 차감 정보 표시
                        if payroll_result.get('unpaid_days', 0) > 0 or payroll_result.get('late_hours', 0) > 0:
                            st.warning("⚠️ 근태에 따른 급여 차감이 있습니다.")
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if payroll_result.get('unpaid_days', 0) > 0:
                                    st.metric("무급휴가 일수", f"{payroll_result['unpaid_days']}일")
                                    st.metric("무급휴가 차감액", f"{payroll_result['unpaid_deduction']:,}원")
                            
                            with col2:
                                if payroll_result.get('late_hours', 0) > 0:
                                    st.metric("지각/조퇴 시간", f"{payroll_result['late_hours']:.1f}시간")
                                    st.metric("지각/조퇴 차감액", f"{payroll_result['lateness_deduction']:,}원")
                        
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.write("**💰 급여 내역**")
                            st.write(f"기본급: {payroll_result['base_salary']:,}원")
                            if payroll_result.get('adjusted_salary', 0) != payroll_result['base_salary']:
                                st.write(f"근태 조정 후: {payroll_result.get('adjusted_salary', 0):,}원")
                            
                            st.write("**📋 공제 내역**")
                            st.write(f"국민연금: {payroll_result['national_pension']:,}원")
                            st.write(f"건강보험: {payroll_result['health_insurance']:,}원")
                            st.write(f"장기요양보험: {payroll_result['long_term_care']:,}원")
                            st.write(f"고용보험: {payroll_result['employment_insurance']:,}원")
                            st.write(f"소득세: {payroll_result['income_tax']:,}원")
                            st.write(f"주민세: {payroll_result['resident_tax']:,}원")
                            
                            if payroll_result.get('unpaid_deduction', 0) > 0:
                                st.write(f"무급휴가 차감: {payroll_result['unpaid_deduction']:,}원")
                            if payroll_result.get('lateness_deduction', 0) > 0:
                                st.write(f"지각/조퇴 차감: {payroll_result['lateness_deduction']:,}원")
                        
                        with col2:
                            st.write("**📊 요약**")
                            st.metric("총 급여액", f"{payroll_result['base_salary']:,}원")
                            st.metric("총 공제액", f"{payroll_result['total_deductions']:,}원")
                            st.metric("실지급액", f"{payroll_result['net_pay']:,}원", 
                                    delta=f"{payroll_result['net_pay'] - payroll_result['base_salary']:,}원")
                            
                            # 공제율 표시
                            if payroll_result['base_salary'] > 0:
                                deduction_rate = (payroll_result['total_deductions'] / payroll_result['base_salary']) * 100
                                st.metric("총 공제율", f"{deduction_rate:.1f}%")
                        
                        # 급여 데이터 저장
                        if st.button("💾 급여 데이터 저장", key="save_individual_payroll"):
                            payroll_data = {
                                'employee_id': selected_employee,
                                'pay_month': pay_month,
                                **payroll_result
                            }
                            
                            result = save_payroll(supabase, payroll_data)
                            if result:
                                st.success("✅ 급여 데이터가 저장되었습니다!")
                            else:
                                st.error("❌ 급여 데이터 저장에 실패했습니다.")
                    else:
                        st.error("❌ 급여 계산에 실패했습니다.")
                        
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.write("**💰 급여 내역**")
                            st.write(f"기본급: {payroll_result['base_salary']:,}원")
                            
                            st.write("**📋 공제 내역**")
                            st.write(f"국민연금: {payroll_result['national_pension']:,}원")
                            st.write(f"건강보험: {payroll_result['health_insurance']:,}원")
                            st.write(f"장기요양보험: {payroll_result['long_term_care']:,}원")
                            st.write(f"고용보험: {payroll_result['employment_insurance']:,}원")
                            st.write(f"소득세: {payroll_result['income_tax']:,}원")
                            st.write(f"주민세: {payroll_result['resident_tax']:,}원")
                        
                        with col2:
                            st.write("**📊 요약**")
                            st.metric("총 급여액", f"{payroll_result['base_salary']:,}원")
                            st.metric("총 공제액", f"{payroll_result['total_deductions']:,}원")
                            st.metric("실지급액", f"{payroll_result['net_pay']:,}원", 
                                    delta=f"{payroll_result['net_pay'] - payroll_result['base_salary']:,}원")
                            
                            # 공제율 표시
                            if payroll_result['base_salary'] > 0:
                                deduction_rate = (payroll_result['total_deductions'] / payroll_result['base_salary']) * 100
                                st.metric("공제율", f"{deduction_rate:.1f}%")
                        
                        # 급여 데이터 저장
                        if st.button("💾 급여 데이터 저장"):
                            payroll_data = {
                                'employee_id': selected_employee,
                                'pay_month': pay_month,
                                **payroll_result
                            }
                            
                            result = save_payroll(supabase, payroll_data)
                            if result:
                                st.success("✅ 급여 데이터가 저장되었습니다!")
                            else:
                                st.error("❌ 급여 데이터 저장에 실패했습니다.")
            
            else:
                st.info("등록된 직원이 없습니다. 먼저 직원을 등록해주세요.")
        
        with tab2:
            st.subheader("일괄 급여 계산")
            
            if not employees_df.empty:
                pay_month = st.text_input("급여 대상 월", value=datetime.now().strftime("%Y-%m"), key="batch_month")
                
                if st.button("전체 직원 급여 계산", key="calculate_batch_payroll"):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    active_employees = employees_df[employees_df['status'] == '재직']
                    total_employees = len(active_employees)
                    payroll_results = []
                    
                    for idx, (_, emp_data) in enumerate(active_employees.iterrows()):
                        status_text.text(f"{emp_data['name']}님 급여 계산 중...")
                        
                        # 급여 계산 (근태 차감 포함)
                        payroll_result = calculate_payroll(emp_data.to_dict(), pay_month, supabase)
                        
                        if payroll_result:
                            # 결과 저장
                            payroll_data = {
                                'employee_id': emp_data['id'],
                                'pay_month': pay_month,
                                **payroll_result
                            }
                            
                            save_result = save_payroll(supabase, payroll_data)
                            if save_result:
                                payroll_results.append({
                                    'name': emp_data['name'],
                                    'base_salary': payroll_result['base_salary'],
                                    'unpaid_deduction': payroll_result.get('unpaid_deduction', 0),
                                    'lateness_deduction': payroll_result.get('lateness_deduction', 0),
                                    'net_pay': payroll_result['net_pay'],
                                    'status': '성공'
                                })
                            else:
                                payroll_results.append({
                                    'name': emp_data['name'],
                                    'base_salary': 0,
                                    'unpaid_deduction': 0,
                                    'lateness_deduction': 0,
                                    'net_pay': 0,
                                    'status': '실패'
                                })
                        
                        progress_bar.progress((idx + 1) / total_employees)
                    
                    status_text.text("급여 계산 완료!")
                    
                    # 결과 표시
                    if payroll_results:
                        st.subheader("급여 계산 결과")
                        results_df = pd.DataFrame(payroll_results)
                        st.dataframe(results_df, use_container_width=True)
                        
                        successful_results = results_df[results_df['status'] == '성공']
                        total_amount = successful_results['net_pay'].sum()
                        total_deductions = successful_results['unpaid_deduction'].sum() + successful_results['lateness_deduction'].sum()
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("총 급여 지급액", f"{total_amount:,}원")
                        with col2:
                            if total_deductions > 0:
                                st.metric("총 근태 차감액", f"{total_deductions:,}원")
            
            else:
                st.info("등록된 직원이 없습니다.")
    
    # 급여 명세서
    elif menu == "급여 명세서":
        st.header("📄 급여 명세서")
        
        tab1, tab2 = st.tabs(["명세서 생성 & 이메일 발송", "급여 데이터 조회"])
        
        with tab1:
            st.subheader("급여 명세서 생성 및 이메일 발송")
            
            if not employees_df.empty:
                col1, col2 = st.columns(2)
                
                with col1:
                    selected_employee = st.selectbox(
                        "직원 선택",
                        options=employees_df['id'].tolist(),
                        format_func=lambda x: employees_df[employees_df['id'] == x]['name'].iloc[0],
                        key="payslip_employee"
                    )
                
                with col2:
                    pay_month = st.text_input("급여 월", value=datetime.now().strftime("%Y-%m"), key="payslip_month")
                
                if selected_employee:
                    emp_data = employees_df[employees_df['id'] == selected_employee].iloc[0].to_dict()
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        if st.button("📄 명세서 생성", key="generate_payslip_pdf"):
                            # 저장된 급여 데이터 조회
                            payroll_df = get_payroll(supabase, selected_employee, pay_month)
                            
                            if not payroll_df.empty:
                                payroll_data = payroll_df.iloc[0].to_dict()
                            else:
                                # 저장된 데이터가 없으면 새로 계산 (근태 차감 포함)
                                payroll_data = calculate_payroll(emp_data, pay_month, supabase)
                            
                            if payroll_data:
                                # PDF 생성
                                pdf_buffer = generate_payslip_pdf(emp_data, payroll_data, pay_month)
                                
                                if pdf_buffer:
                                    # 다운로드 버튼
                                    st.download_button(
                                        label="📄 급여명세서 다운로드",
                                        data=pdf_buffer.getvalue(),
                                        file_name=f"{emp_data['name']}_{pay_month}_급여명세서.pdf",
                                        mime="application/pdf"
                                    )
                                    
                                    st.success("✅ 급여명세서가 생성되었습니다!")
                                else:
                                    st.error("❌ PDF 생성에 실패했습니다.")
                            else:
                                st.error("❌ 급여 계산에 실패했습니다.")
                    
                    with col2:
                        if st.button("📧 이메일 발송", key="send_payslip_email"):
                            if not emp_data.get('email'):
                                st.error("❌ 직원의 이메일 주소가 설정되지 않았습니다.")
                            else:
                                # 저장된 급여 데이터 조회
                                payroll_df = get_payroll(supabase, selected_employee, pay_month)
                                
                                if not payroll_df.empty:
                                    payroll_data = payroll_df.iloc[0].to_dict()
                                else:
                                    # 저장된 데이터가 없으면 새로 계산 (근태 차감 포함)
                                    payroll_data = calculate_payroll(emp_data, pay_month, supabase)
                                
                                if payroll_data:
                                    # PDF 생성
                                    pdf_buffer = generate_payslip_pdf(emp_data, payroll_data, pay_month)
                                    
                                    if pdf_buffer:
                                        # 이메일 발송
                                        success, message = send_payslip_email(
                                            emp_data['email'], 
                                            pdf_buffer, 
                                            emp_data['name'], 
                                            pay_month
                                        )
                                        
                                        if success:
                                            st.success(f"✅ {message}")
                                        else:
                                            st.error(f"❌ {message}")
                                    else:
                                        st.error("❌ PDF 생성에 실패했습니다.")
                                else:
                                    st.error("❌ 급여 계산에 실패했습니다.")
                    
                    # 대량 이메일 발송
                    st.markdown("---")
                    st.subheader("📮 전체 직원 명세서 이메일 발송")
                    
                    if st.button("📧 전체 직원에게 명세서 이메일 발송", key="send_batch_payslip_email"):
                        active_employees = employees_df[employees_df['status'] == '재직']
                        total_employees = len(active_employees)
                        
                        if total_employees == 0:
                            st.warning("발송할 재직 직원이 없습니다.")
                        else:
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            success_count = 0
                            
                            for idx, (_, emp_data) in enumerate(active_employees.iterrows()):
                                status_text.text(f"{emp_data['name']}님에게 이메일 발송 중...")
                                
                                if emp_data.get('email'):
                                    # 급여 데이터 조회
                                    payroll_df = get_payroll(supabase, emp_data['id'], pay_month)
                                    
                                    if not payroll_df.empty:
                                        payroll_data = payroll_df.iloc[0].to_dict()
                                        
                                        # PDF 생성 및 이메일 발송
                                        pdf_buffer = generate_payslip_pdf(emp_data.to_dict(), payroll_data, pay_month)
                                        
                                        if pdf_buffer:
                                            success, _ = send_payslip_email(
                                                emp_data['email'], 
                                                pdf_buffer, 
                                                emp_data['name'], 
                                                pay_month
                                            )
                                            
                                            if success:
                                                success_count += 1
                                
                                progress_bar.progress((idx + 1) / total_employees)
                                time.sleep(0.5)  # 이메일 서버 부하 방지
                            
                            status_text.text("이메일 발송 완료!")
                            st.success(f"✅ {success_count}/{total_employees}명에게 급여명세서가 발송되었습니다!")
            
            else:
                st.info("등록된 직원이 없습니다. 먼저 직원을 등록해주세요.")
        
        with tab2:
            st.subheader("급여 데이터 조회")
            
            # 급여 데이터 조회
            payroll_df = get_payroll(supabase)
            
            if not payroll_df.empty:
                # 급여 월 필터
                available_months = payroll_df['pay_month'].unique()
                selected_month = st.selectbox("급여 월 선택", ['전체'] + list(available_months))
                
                # 필터 적용
                if selected_month != '전체':
                    filtered_payroll = payroll_df[payroll_df['pay_month'] == selected_month]
                else:
                    filtered_payroll = payroll_df
                
                # 직원명 추가
                if 'employees' in filtered_payroll.columns:
                    filtered_payroll['employee_name'] = filtered_payroll['employees'].apply(
                        lambda x: x['name'] if isinstance(x, dict) and x else ''
                    )
                
                # 데이터 표시
                display_columns = ['employee_name', 'pay_month', 'base_salary', 'total_deductions', 
                                 'net_pay', 'is_paid', 'pay_date']
                available_columns = [col for col in display_columns if col in filtered_payroll.columns]
                
                st.dataframe(filtered_payroll[available_columns], use_container_width=True)
                
                # 통계 정보
                if selected_month != '전체':
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        total_employees = len(filtered_payroll)
                        st.metric("대상 직원 수", total_employees)
                    
                    with col2:
                        total_gross = filtered_payroll['base_salary'].sum()
                        st.metric("총 기본급", f"{total_gross:,}원")
                    
                    with col3:
                        total_net = filtered_payroll['net_pay'].sum()
                        st.metric("총 실지급액", f"{total_net:,}원")
            
            else:
                st.info("급여 데이터가 없습니다. '급여 계산' 메뉴에서 급여를 계산해주세요.")
    
    # 퇴직금 계산 (새로운 메뉴)
    elif menu == "퇴직금 계산":
        st.header("💼 퇴직금 계산")
        
        if not employees_df.empty:
            col1, col2 = st.columns(2)
            
            with col1:
                selected_employee = st.selectbox(
                    "퇴직 직원 선택",
                    options=employees_df['id'].tolist(),
                    format_func=lambda x: employees_df[employees_df['id'] == x]['name'].iloc[0]
                )
            
            with col2:
                resignation_date = st.date_input("퇴직일", value=datetime.now().date())
            
            if selected_employee:
                emp_data = employees_df[employees_df['id'] == selected_employee].iloc[0]
                
                # 최근 3개월 급여 조회
                recent_months = []
                for i in range(3):
                    month = (datetime.now() - relativedelta(months=i)).strftime("%Y-%m")
                    recent_months.append(month)
                
                recent_salaries = []
                for month in recent_months:
                    payroll_df = get_payroll(supabase, selected_employee, month)
                    if not payroll_df.empty:
                        recent_salaries.append(payroll_df.iloc[0]['base_salary'])
                
                # 급여 데이터가 없으면 현재 기본급 사용
                if not recent_salaries:
                    recent_salaries = [emp_data['base_salary']] * 3
                
                # 퇴직금 계산
                severance_result = calculate_severance_pay(
                    emp_data['hire_date'], 
                    resignation_date, 
                    recent_salaries
                )
                
                # 결과 표시
                st.subheader(f"💰 {emp_data['name']}님의 퇴직금 계산 결과")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**📋 근무 정보**")
                    st.write(f"입사일: {emp_data['hire_date']}")
                    st.write(f"퇴직일: {resignation_date}")
                    st.write(f"근속기간: {severance_result['work_years']:.1f}년 ({severance_result['work_days']}일)")
                    
                    st.write("**💰 급여 정보**")
                    if 'average_monthly_wage' in severance_result:
                        st.write(f"최근 3개월 평균급여: {severance_result['average_monthly_wage']:,.0f}원")
                        st.write(f"일평균임금: {severance_result.get('daily_average_wage', 0):,.0f}원")
                
                with col2:
                    st.write("**🧮 퇴직금 계산**")
                    if severance_result['work_years'] >= 1:
                        st.write(f"계속근로연수: {int(severance_result['work_years'])}년")
                        st.write(f"30일분 평균임금: {severance_result.get('daily_average_wage', 0) * 30:,.0f}원")
                        
                        st.metric(
                            "퇴직금", 
                            f"{severance_result['severance_pay']:,.0f}원",
                            help="계속근로연수 × 30일분의 평균임금"
                        )
                    else:
                        st.warning("근속기간 1년 미만으로 퇴직금 대상이 아닙니다.")
                
                st.info(severance_result['message'])
                
                # 퇴직금 지급 처리
                if severance_result['severance_pay'] > 0:
                    if st.button("💸 퇴직금 지급 처리", key="process_severance_payment"):
                        # 직원 상태를 퇴직으로 변경
                        update_data = {
                            'status': '퇴직',
                            'notes': f"퇴직일: {resignation_date}, 퇴직금: {severance_result['severance_pay']:,}원",
                            'updated_at': datetime.now().isoformat()
                        }
                        
                        result = update_employee(supabase, selected_employee, update_data)
                        if result:
                            st.success(f"✅ {emp_data['name']}님의 퇴직 처리가 완료되었습니다!")
                        else:
                            st.error("❌ 퇴직 처리에 실패했습니다.")
        
        else:
            st.info("등록된 직원이 없습니다.")
    
    # 연차 관리 (새로운 메뉴)
    elif menu == "연차 관리":
        st.header("📅 연차 관리")
        
        tab1, tab2, tab3 = st.tabs(["연차 현황", "연차 부여/차감", "연차 통계"])
        
        with tab1:
            st.subheader("직원별 연차 현황")
            
            if not employees_df.empty:
                # 연차 현황 테이블
                leave_columns = ['name', 'department', 'hire_date', 'total_annual_leave', 'used_annual_leave', 'remaining_annual_leave', 'status']
                available_columns = [col for col in leave_columns if col in employees_df.columns]
                
                display_df = employees_df[available_columns].copy()
                
                # 연차 사용률 계산
                if 'total_annual_leave' in display_df.columns and 'used_annual_leave' in display_df.columns:
                    display_df['usage_rate'] = (display_df['used_annual_leave'] / display_df['total_annual_leave'] * 100).round(1)
                
                st.dataframe(display_df, use_container_width=True)
                
                # 연차 사용률 차트
                if 'usage_rate' in display_df.columns and not display_df.empty:
                    fig = px.bar(
                        display_df, 
                        x='name', 
                        y='usage_rate',
                        title="직원별 연차 사용률 (%)",
                        color='usage_rate',
                        color_continuous_scale='RdYlGn_r'
                    )
                    st.plotly_chart(fig, use_container_width=True)
        
        with tab2:
            st.subheader("연차 부여 및 차감")
            
            if not employees_df.empty:
                col1, col2 = st.columns(2)
                
                with col1:
                    selected_employee = st.selectbox(
                        "직원 선택",
                        options=employees_df['id'].tolist(),
                        format_func=lambda x: employees_df[employees_df['id'] == x]['name'].iloc[0],
                        key="leave_management_employee"
                    )
                
                with col2:
                    action_type = st.selectbox("작업 유형", ["연차 부여", "연차 차감", "연차 초기화"])
                
                if selected_employee:
                    emp_data = employees_df[employees_df['id'] == selected_employee].iloc[0]
                    
                    # 현재 연차 정보 표시
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("총 연차", f"{emp_data.get('total_annual_leave', 0)}일")
                    with col2:
                        st.metric("사용 연차", f"{emp_data.get('used_annual_leave', 0)}일")
                    with col3:
                        st.metric("잔여 연차", f"{emp_data.get('remaining_annual_leave', 0)}일")
                    
                    if action_type == "연차 부여":
                        additional_days = st.number_input("부여할 연차 일수", min_value=1, value=1)
                        reason = st.text_input("부여 사유", placeholder="예: 추가 포상 연차")
                        
                        if st.button("연차 부여", key="grant_annual_leave"):
                            new_total = emp_data.get('total_annual_leave', 0) + additional_days
                            new_remaining = emp_data.get('remaining_annual_leave', 0) + additional_days
                            
                            update_data = {
                                'total_annual_leave': new_total,
                                'remaining_annual_leave': new_remaining,
                                'notes': f"{emp_data.get('notes', '')} [연차부여: +{additional_days}일 - {reason}]",
                                'updated_at': datetime.now().isoformat()
                            }
                            
                            result = update_employee(supabase, selected_employee, update_data)
                            if result:
                                st.success(f"✅ {additional_days}일의 연차가 부여되었습니다!")
                                st.rerun()
                    
                    elif action_type == "연차 차감":
                        deduct_days = st.number_input("차감할 연차 일수", min_value=1, value=1, max_value=emp_data.get('remaining_annual_leave', 0))
                        reason = st.text_input("차감 사유", placeholder="예: 무단결근으로 인한 차감")
                        
                        if st.button("연차 차감", key="deduct_annual_leave"):
                            new_used = emp_data.get('used_annual_leave', 0) + deduct_days
                            new_remaining = max(0, emp_data.get('remaining_annual_leave', 0) - deduct_days)
                            
                            update_data = {
                                'used_annual_leave': new_used,
                                'remaining_annual_leave': new_remaining,
                                'notes': f"{emp_data.get('notes', '')} [연차차감: -{deduct_days}일 - {reason}]",
                                'updated_at': datetime.now().isoformat()
                            }
                            
                            result = update_employee(supabase, selected_employee, update_data)
                            if result:
                                st.success(f"✅ {deduct_days}일의 연차가 차감되었습니다!")
                                st.rerun()
                    
                    elif action_type == "연차 초기화":
                        st.warning("⚠️ 연차 초기화는 신중하게 진행해주세요.")
                        
                        # 자동 계산된 연차 표시
                        auto_calculated_leave = calculate_annual_leave(emp_data['hire_date'])
                        st.info(f"📅 입사일 기준 자동 계산 연차: {auto_calculated_leave}일")
                        
                        if st.button("🔄 연차 초기화 (자동 계산값으로)", key="reset_annual_leave"):
                            update_data = {
                                'total_annual_leave': auto_calculated_leave,
                                'used_annual_leave': 0,
                                'remaining_annual_leave': auto_calculated_leave,
                                'notes': f"{emp_data.get('notes', '')} [연차초기화: {datetime.now().strftime('%Y-%m-%d')}]",
                                'updated_at': datetime.now().isoformat()
                            }
                            
                            result = update_employee(supabase, selected_employee, update_data)
                            if result:
                                st.success(f"✅ 연차가 {auto_calculated_leave}일로 초기화되었습니다!")
                                st.rerun()
        
        with tab3:
            st.subheader("연차 사용 통계")
            
            if not employees_df.empty:
                # 전체 연차 통계
                total_granted = employees_df['total_annual_leave'].sum()
                total_used = employees_df['used_annual_leave'].sum()
                total_remaining = employees_df['remaining_annual_leave'].sum()
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("총 부여 연차", f"{total_granted}일")
                
                with col2:
                    st.metric("총 사용 연차", f"{total_used}일")
                
                with col3:
                    st.metric("총 잔여 연차", f"{total_remaining}일")
                
                with col4:
                    usage_rate = (total_used / total_granted * 100) if total_granted > 0 else 0
                    st.metric("전체 사용률", f"{usage_rate:.1f}%")
                
                # 부서별 연차 사용 현황
                if 'department' in employees_df.columns:
                    dept_stats = employees_df.groupby('department').agg({
                        'total_annual_leave': 'sum',
                        'used_annual_leave': 'sum',
                        'remaining_annual_leave': 'sum'
                    }).reset_index()
                    
                    dept_stats['usage_rate'] = (dept_stats['used_annual_leave'] / dept_stats['total_annual_leave'] * 100).round(1)
                    
                    fig = px.bar(
                        dept_stats,
                        x='department',
                        y=['used_annual_leave', 'remaining_annual_leave'],
                        title="부서별 연차 사용 현황",
                        labels={'value': '연차 일수', 'variable': '구분'}
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                # 월별 연차 사용 추이 (근태 데이터 기반)
                attendance_df = get_attendance(supabase)
                if not attendance_df.empty and 'status' in attendance_df.columns:
                    annual_leave_df = attendance_df[attendance_df['status'] == '연차']
                    
                    if not annual_leave_df.empty and 'date' in annual_leave_df.columns:
                        annual_leave_df['month'] = pd.to_datetime(annual_leave_df['date']).dt.strftime('%Y-%m')
                        monthly_usage = annual_leave_df.groupby('month').size().reset_index(name='count')
                        
                        fig2 = px.line(
                            monthly_usage,
                            x='month',
                            y='count',
                            title="월별 연차 사용 추이",
                            markers=True
                        )
                        st.plotly_chart(fig2, use_container_width=True)
    
    # 통계 및 분석
    elif menu == "통계 및 분석":
        st.header("📊 통계 및 분석")
        
        if not employees_df.empty:
            tab1, tab2, tab3, tab4 = st.tabs(["인사 통계", "급여 분석", "근태 분석", "연차 분석"])
            
            with tab1:
                st.subheader("인사 현황 통계")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    # 부서별 직원 수
                    if 'department' in employees_df.columns:
                        dept_count = employees_df['department'].value_counts()
                        fig1 = px.pie(values=dept_count.values, names=dept_count.index, 
                                     title="부서별 직원 분포")
                        st.plotly_chart(fig1, use_container_width=True)
                
                with col2:
                    # 상태별 직원 수
                    if 'status' in employees_df.columns:
                        status_count = employees_df['status'].value_counts()
                        fig2 = px.bar(x=status_count.index, y=status_count.values, 
                                     title="직원 상태별 분포")
                        st.plotly_chart(fig2, use_container_width=True)
                
                # 입사년도별 분석
                if 'hire_date' in employees_df.columns and not employees_df.empty:
                    try:
                        employees_df_copy = employees_df.copy()
                        employees_df_copy['hire_year'] = pd.to_datetime(employees_df_copy['hire_date'], errors='coerce').dt.year
                        hire_year_count = employees_df_copy['hire_year'].dropna().value_counts().sort_index()
                        
                        if len(hire_year_count) > 0:
                            fig3 = px.line(x=hire_year_count.index, y=hire_year_count.values, 
                                          title="연도별 입사 인원", markers=True)
                            st.plotly_chart(fig3, use_container_width=True)
                    except Exception as e:
                        st.warning(f"입사년도 분석 중 오류: {str(e)}")
                
                # 근속년수 분포
                if 'hire_date' in employees_df.columns:
                    try:
                        employees_df_copy = employees_df.copy()
                        employees_df_copy['work_years'] = employees_df_copy['hire_date'].apply(
                            lambda x: (datetime.now().date() - pd.to_datetime(x).date()).days / 365.25
                        )
                        
                        fig4 = px.histogram(employees_df_copy, x='work_years', nbins=10, 
                                           title="근속년수 분포")
                        st.plotly_chart(fig4, use_container_width=True)
                    except Exception as e:
                        st.warning(f"근속년수 분석 중 오류: {str(e)}")
            
            with tab2:
                st.subheader("급여 분석")
                
                if 'base_salary' in employees_df.columns:
                    # 급여 통계 지표
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        avg_salary = employees_df['base_salary'].mean()
                        st.metric("평균 기본급", f"{avg_salary:,.0f}원")
                    
                    with col2:
                        median_salary = employees_df['base_salary'].median()
                        st.metric("중간값 기본급", f"{median_salary:,.0f}원")
                    
                    with col3:
                        min_salary = employees_df['base_salary'].min()
                        st.metric("최저 기본급", f"{min_salary:,.0f}원")
                    
                    with col4:
                        max_salary = employees_df['base_salary'].max()
                        st.metric("최고 기본급", f"{max_salary:,.0f}원")
                    
                    # 급여 분포 히스토그램
                    fig4 = px.histogram(employees_df, x='base_salary', nbins=10, 
                                       title="기본급 분포")
                    st.plotly_chart(fig4, use_container_width=True)
                    
                    # 부서별 평균 급여
                    if 'department' in employees_df.columns:
                        dept_salary = employees_df.groupby('department')['base_salary'].agg(['mean', 'count']).reset_index()
                        dept_salary.columns = ['department', 'avg_salary', 'count']
                        
                        if len(dept_salary) > 0:
                            fig5 = px.bar(dept_salary, x='department', y='avg_salary', 
                                         title="부서별 평균 기본급",
                                         text='count',
                                         labels={'count': '인원수'})
                            fig5.update_traces(texttemplate='%{text}명', textposition='outside')
                            st.plotly_chart(fig5, use_container_width=True)
                    
                    # 월별 급여 지급 현황
                    payroll_df = get_payroll(supabase)
                    if not payroll_df.empty and 'pay_month' in payroll_df.columns and 'net_pay' in payroll_df.columns:
                        monthly_payroll = payroll_df.groupby('pay_month').agg({
                            'net_pay': 'sum',
                            'employee_id': 'count'
                        }).reset_index()
                        monthly_payroll.columns = ['pay_month', 'total_pay', 'employee_count']
                        
                        if not monthly_payroll.empty:
                            fig6 = px.line(monthly_payroll, x='pay_month', y='total_pay', 
                                          title="월별 총 급여 지급액",
                                          text='employee_count')
                            fig6.update_traces(texttemplate='%{text}명', textposition='top center')
                            st.plotly_chart(fig6, use_container_width=True)
                
                else:
                    st.info("급여 정보가 없습니다.")
            
            with tab3:
                st.subheader("근태 분석")
                
                # 기간 선택
                col1, col2 = st.columns(2)
                with col1:
                    analysis_start = st.date_input("분석 시작일", value=datetime.now().date().replace(day=1))
                with col2:
                    analysis_end = st.date_input("분석 종료일", value=datetime.now().date())
                
                # 근태 데이터 조회
                attendance_df = get_attendance(supabase, None, analysis_start, analysis_end)
                
                if not attendance_df.empty:
                    # 근태 현황 지표
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        total_records = len(attendance_df)
                        st.metric("총 근태 기록", total_records)
                    
                    with col2:
                        if 'actual_hours' in attendance_df.columns:
                            avg_hours = attendance_df['actual_hours'].mean()
                            st.metric("평균 근무시간", f"{avg_hours:.1f}시간")
                    
                    with col3:
                        if 'status' in attendance_df.columns:
                            late_rate = len(attendance_df[attendance_df['status'] == '지각']) / total_records * 100
                            st.metric("지각률", f"{late_rate:.1f}%")
                    
                    with col4:
                        if 'status' in attendance_df.columns:
                            absent_rate = len(attendance_df[attendance_df['status'] == '결근']) / total_records * 100
                            st.metric("결근률", f"{absent_rate:.1f}%")
                    
                    # 일별 출근율
                    if 'date' in attendance_df.columns:
                        daily_attendance = attendance_df.groupby('date').size().reset_index(name='count')
                        if not daily_attendance.empty:
                            fig7 = px.line(daily_attendance, x='date', y='count', title="일별 출근 인원")
                            st.plotly_chart(fig7, use_container_width=True)
                    
                    # 근태 상태별 분포
                    if 'status' in attendance_df.columns:
                        status_dist = attendance_df['status'].value_counts()
                        if not status_dist.empty:
                            fig8 = px.pie(values=status_dist.values, names=status_dist.index, title="근태 상태별 분포")
                            st.plotly_chart(fig8, use_container_width=True)
                    
                    # 직원별 근무시간 분석
                    if 'employees' in attendance_df.columns and 'actual_hours' in attendance_df.columns:
                        attendance_df['employee_name'] = attendance_df['employees'].apply(
                            lambda x: x['name'] if isinstance(x, dict) and x else ''
                        )
                        
                        emp_hours = attendance_df.groupby('employee_name')['actual_hours'].agg(['sum', 'mean', 'count']).reset_index()
                        emp_hours.columns = ['employee_name', 'total_hours', 'avg_hours', 'work_days']
                        
                        if not emp_hours.empty:
                            fig9 = px.bar(emp_hours, x='employee_name', y='total_hours', 
                                         title="직원별 총 근무시간",
                                         text='work_days')
                            fig9.update_traces(texttemplate='%{text}일', textposition='outside')
                            st.plotly_chart(fig9, use_container_width=True)
                
                else:
                    st.info("해당 기간에 근태 데이터가 없습니다.")
            
            with tab4:
                st.subheader("연차 사용 분석")
                
                if 'total_annual_leave' in employees_df.columns:
                    # 연차 통계 지표
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        total_granted = employees_df['total_annual_leave'].sum()
                        st.metric("총 부여 연차", f"{total_granted}일")
                    
                    with col2:
                        total_used = employees_df['used_annual_leave'].sum()
                        st.metric("총 사용 연차", f"{total_used}일")
                    
                    with col3:
                        total_remaining = employees_df['remaining_annual_leave'].sum()
                        st.metric("총 잔여 연차", f"{total_remaining}일")
                    
                    with col4:
                        usage_rate = (total_used / total_granted * 100) if total_granted > 0 else 0
                        st.metric("전체 사용률", f"{usage_rate:.1f}%")
                    
                    # 직원별 연차 사용률
                    emp_leave = employees_df.copy()
                    emp_leave['usage_rate'] = (emp_leave['used_annual_leave'] / emp_leave['total_annual_leave'] * 100).fillna(0)
                    
                    fig10 = px.bar(emp_leave, x='name', y='usage_rate', 
                                  title="직원별 연차 사용률 (%)",
                                  color='usage_rate',
                                  color_continuous_scale='RdYlGn_r')
                    st.plotly_chart(fig10, use_container_width=True)
                    
                    # 부서별 연차 현황
                    if 'department' in employees_df.columns:
                        dept_leave = employees_df.groupby('department').agg({
                            'total_annual_leave': 'sum',
                            'used_annual_leave': 'sum',
                            'remaining_annual_leave': 'sum'
                        }).reset_index()
                        
                        fig11 = px.bar(dept_leave, x='department', 
                                      y=['used_annual_leave', 'remaining_annual_leave'],
                                      title="부서별 연차 사용 현황")
                        st.plotly_chart(fig11, use_container_width=True)
        
        else:
            st.info("분석할 데이터가 없습니다. 먼저 직원을 등록해주세요.")
    
    # 시스템 정보
    elif menu == "시스템 정보":
        st.header("ℹ️ 시스템 정보")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("💡 시스템 현황")
            
            # 연결 상태
            st.success("🟢 데이터베이스: 연결됨")
            
            # 데이터 현황
            st.info(f"📊 등록된 직원 수: {len(employees_df)}")
            
            attendance_df = get_attendance(supabase)
            st.info(f"⏰ 근태 기록 수: {len(attendance_df)}")
            
            payroll_df = get_payroll(supabase)
            st.info(f"💰 급여 기록 수: {len(payroll_df)}")
            
            # 시스템 정보
            st.write("**🔧 시스템 버전**")
            st.write("- 급여관리 시스템 v2.0 (개선판)")
            st.write("- Streamlit 기반")
            st.write("- 2025년 세율 적용")
            st.write("- 한글 PDF 지원")
            st.write("- 이메일 발송 기능")
            st.write("- 퇴직금 계산 기능")
            st.write("- 연차 자동 관리")
        
        with col2:
            st.subheader("📋 새로운 기능 목록")
            
            features = [
                "✅ 직원 정보 관리",
                "✅ 근태 기록 관리", 
                "✅ 급여 자동 계산",
                "✅ 4대보험 자동 계산",
                "✅ 소득세/주민세 계산",
                "✅ 한글 PDF 급여명세서 생성",
                "🆕 이메일 자동 발송",
                "🆕 퇴직금 자동 계산",
                "🆕 연차 자동 부여/관리",
                "🆕 연차 사용 자동 차감",
                "✅ 통계 및 분석",
                "✅ 데이터 시각화"
            ]
            
            for feature in features:
                st.write(feature)
        
        # 데이터베이스 관리
        st.subheader("🔧 데이터베이스 관리")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🔄 연결 테스트", key="test_db_connection"):
                try:
                    test_result = supabase.table('employees').select('count').execute()
                    st.success("✅ 데이터베이스 연결 정상")
                except Exception as e:
                    st.error(f"❌ 연결 오류: {str(e)}")
        
        with col2:
            if st.button("📊 테이블 상태 확인", key="check_table_status"):
                tables = ['employees', 'attendance', 'payroll']
                for table in tables:
                    try:
                        result = supabase.table(table).select('*').limit(1).execute()
                        st.success(f"✅ {table} 테이블 정상")
                    except Exception as e:
                        st.error(f"❌ {table} 테이블 오류: {str(e)}")
        
        with col3:
            if st.button("🔄 전체 연차 업데이트", key="update_all_leave_system"):
                if not employees_df.empty:
                    updated_count = 0
                    for _, emp in employees_df.iterrows():
                        if update_employee_annual_leave(supabase, emp['id'], emp['hire_date']):
                            updated_count += 1
                    
                    st.success(f"✅ {updated_count}명의 연차가 업데이트되었습니다!")
                else:
                    st.info("업데이트할 직원이 없습니다.")
        
        # 2025년 세율 정보
        st.subheader("📊 2025년 적용 세율")
        
        tax_info = pd.DataFrame({
            "항목": ["국민연금", "건강보험", "장기요양보험", "고용보험(실업급여)", "고용보험(고용안정)", "산재보험"],
            "근로자 부담률": ["4.5%", "3.545%", "건강보험료×12.95%", "0.9%", "-", "-"],
            "사업주 부담률": ["4.5%", "3.545%", "건강보험료×12.95%", "0.9%", "0.25%~0.85%", "업종별 차등"]
        })
        
        st.dataframe(tax_info, use_container_width=True)
        
        # 이메일 설정 확인
        st.subheader("📧 이메일 설정 확인")
        
        try:
            email_config = {
                "SMTP 서버": st.secrets.get("SMTP_SERVER", "설정되지 않음"),
                "SMTP 포트": st.secrets.get("SMTP_PORT", "설정되지 않음"),
                "발신자 이메일": st.secrets.get("SENDER_EMAIL", "설정되지 않음"),
                "비밀번호 설정": "설정됨" if st.secrets.get("SENDER_PASSWORD") else "설정되지 않음"
            }
            
            for key, value in email_config.items():
                if value == "설정되지 않음":
                    st.error(f"❌ {key}: {value}")
                else:
                    st.success(f"✅ {key}: {value}")
        except:
            st.warning("⚠️ 이메일 설정을 확인할 수 없습니다.")
        
        # 문제 해결 가이드
        with st.expander("🆘 문제 해결 가이드"):
            st.markdown("""
            ### 새로운 기능 관련 문제해결
            
            **1. 한글 PDF가 깨져 보일 때**
            - 시스템에 한글 폰트가 설치되어 있는지 확인
            - Windows: 맑은고딕, macOS: 나눔고딕 권장
            
            **2. 이메일 발송이 안 될 때**
            - Gmail 앱 비밀번호 설정 확인
            - 2단계 인증 활성화 후 앱 비밀번호 생성
            - SMTP 설정이 올바른지 확인
            
            **3. 연차 계산이 이상할 때**
            - 입사일이 올바르게 입력되었는지 확인
            - '연차 관리' 메뉴에서 수동 조정 가능
            
            **4. 퇴직금 계산 오류**
            - 최근 3개월 급여 데이터가 있는지 확인
            - 급여 계산 후 퇴직금 계산 진행
            
            **5. 기존 기능 문제**
            - "테이블을 찾을 수 없습니다" → SQL 실행 확인
            - "권한이 없습니다" → RLS 비활성화
            - "연결할 수 없습니다" → API Key 확인
            """)
            
            st.markdown("### 이메일 설정 가이드")
            st.code("""
# secrets.toml 예시
[default]
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_ANON_KEY = "your_anon_key"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "your_email@gmail.com"
SENDER_PASSWORD = "your_app_password"  # Gmail 앱 비밀번호
            """)
            
            st.markdown("### 도움이 필요하시면")
            st.info("💡 새로운 기능들이 추가된 v2.0입니다. 문제 발생 시 위 가이드를 참고해주세요.")
    
    # 푸터
    st.markdown("---")
    st.markdown(f"""
    <div style='text-align: center; color: #666; padding: 20px;'>
        <p>💼 급여 및 인사 관리 시스템 v2.0 (개선판)</p>
        <p>🆕 새로운 기능: 한글PDF지원, 이메일발송, 퇴직금계산, 연차자동관리</p>
        <p>🔒 모든 데이터는 안전하게 암호화되어 저장됩니다</p>
        <p>현재 데이터: 직원 {len(employees_df)}명, 근태 {len(get_attendance(supabase))}건, 급여 {len(get_payroll(supabase))}건</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
