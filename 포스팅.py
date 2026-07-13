import pandas as pd
import random
import os
import json
import subprocess
import sys
import atexit
import signal
import gspread
from google.oauth2.service_account import Credentials
import time
import pyperclip
import warnings
import threading
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import traceback
import datetime
import shutil
import re
from PIL import Image, ImageEnhance, ImageOps, ExifTags
import hashlib
import undetected_chromedriver as uc

# ============================================================
# _internal 경로 (포스팅.py/exe 위치 기준, cwd 무관)
# ============================================================
def _앱_루트_경로():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _internal_폴더_경로():
    root = _앱_루트_경로()
    if os.path.basename(root).lower() == '_internal':
        return root
    return os.path.join(root, '_internal')


def resource_path(relative_path):
    """포스팅.py(또는 exe) 기준 _internal 폴더 내 파일 경로 (없으면 생성)"""
    internal_path = _internal_폴더_경로()
    if not os.path.exists(internal_path):
        os.makedirs(internal_path)
    return os.path.join(internal_path, relative_path)


# ============================================================
# 설정.xlsx 읽기 - 프로그램 시작 시 기능 ON/OFF 적용
# _internal/설정.xlsx : 아이피교체, 상호제거기능, 사용아이디(*=전체)
# ============================================================
def _아이피교체_셀_파싱(raw):
    """아이피교체 셀: 0=OFF, 1=ON, IP주소=해당 IP PC만 작업 허용(교체 생략).
    반환: (ip_change_on_off: int, allowed_ip: str|None)
    """
    s = str(raw).strip()
    if s.lower() in ('nan', 'none', ''):
        return 1, None
    if re.fullmatch(r'(\d{1,3}\.){3}\d{1,3}', s):
        return 0, s
    try:
        v = int(float(s))
        if v == 0:
            return 0, None
        return 1, None
    except (ValueError, TypeError):
        pass
    return 1, None


def _설정파일_읽기():
    """_internal/설정.xlsx 를 읽어 설정값 반환. 읽기 실패 시 기본값 반환."""
    try:
        _path = resource_path('설정.xlsx')
        _df = pd.read_excel(_path)
        _col_ip   = '아이피교체'
        _col_biz  = '상호제거기능'
        _col_uid  = '사용아이디'
        _col_kw   = '지명키워드'
        _col_pt   = '발행시간고정'
        if _col_ip in _df.columns:
            _ip_val, _allowed_ip = _아이피교체_셀_파싱(_df[_col_ip].iloc[0])
        else:
            _ip_val, _allowed_ip = 1, None
        _biz_val  = int(_df[_col_biz].iloc[0])  if _col_biz in _df.columns else 1
        _uid_val  = str(_df[_col_uid].iloc[0]).strip() if _col_uid in _df.columns else ''
        if _uid_val.lower() in ('nan', 'none'):
            _uid_val = ''
        _kw_limit = 0
        if _col_kw in _df.columns:
            try:
                _kw_limit = int(_df[_col_kw].iloc[0])
            except Exception:
                _kw_limit = 0
        _pt_val = 0
        if _col_pt in _df.columns:
            try:
                _pt_val = int(_df[_col_pt].iloc[0])
            except Exception:
                _pt_val = 0
        _kw_limit_label = str(_kw_limit) if _kw_limit > 0 else '무제한'
        _ip_label = _allowed_ip if _allowed_ip else _ip_val
        print(f"[설정.xlsx] 경로: {_path}")
        print(f"[설정.xlsx] 아이피교체={_ip_label}, 상호제거기능={_biz_val}, 사용아이디='{_uid_val or '(비움)'}', 지명키워드한도={_kw_limit_label}, 발행시간고정={_pt_val}")
        return _ip_val, _allowed_ip, _biz_val, _uid_val, _kw_limit, _pt_val
    except Exception as _e:
        print(f"[설정.xlsx] 읽기 실패 ({_e}), 기본값 적용")
        return 1, None, 1, '', 0, 0

설정_아이피교체, 설정_작업_허용_아이피, 설정_상호제거기능, 설정_사용아이디, 설정_지명키워드_한도, 설정_발행시간고정 = _설정파일_읽기()

# undetected-chromedriver: 설치 Chrome 메이저와 드라이버 일치 (SessionNotCreated 방지)
# None이면 Windows에서 레지스트리(BLBeacon)로 자동. 자동 실패 시 예: UC_크롬_메이저_버전_수동 = 146
UC_크롬_메이저_버전_수동 = None


def 크롬_메이저_버전_읽기():
    """Windows 레지스트리에서 설치된 Google Chrome 메이저 버전(예: 146)을 읽습니다."""
    if os.name != "nt":
        return None
    import winreg

    paths = [
        (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Google\Chrome\BLBeacon"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Google\Chrome\BLBeacon"),
    ]
    for root, sub in paths:
        try:
            k = winreg.OpenKey(root, sub)
            try:
                ver, _ = winreg.QueryValueEx(k, "version")
            finally:
                winreg.CloseKey(k)
            if isinstance(ver, str) and ver.strip():
                return int(ver.split(".")[0])
        except OSError:
            continue
    return None


def uc_크롬_드라이버_생성(chrome_options):
    """uc.Chrome 생성. version_main으로 설치된 Chrome과 ChromeDriver 메이저를 맞춥니다."""
    version_main = UC_크롬_메이저_버전_수동
    if version_main is None:
        version_main = 크롬_메이저_버전_읽기()
    if version_main is not None:
        print(f"ChromeDriver 대상 Chrome 메이저 버전: {version_main}")
        driver = uc.Chrome(options=chrome_options, version_main=version_main)
    else:
        print(
            "Chrome 메이저 버전을 자동으로 읽지 못했습니다. "
            "UC_크롬_메이저_버전_수동에 숫자(예: 146)를 넣거나 Chrome을 최신으로 맞추세요."
        )
        driver = uc.Chrome(options=chrome_options)

    try:
        driver.set_window_position(0, 0)
    except Exception:
        pass
    try:
        import pyautogui
        time.sleep(10)
        pyautogui.click(20, 300)
    except Exception:
        pass

    return driver


def uc_포스팅_크롬_옵션_생성():
    """블로그 포스팅용 uc ChromeOptions"""
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument('--disable-popup-blocking')
    chrome_options.add_argument('--disable-notifications')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-new-tab')
    chrome_options.add_argument('--disable-background-timer-throttling')
    chrome_options.add_argument('--disable-backgrounding-occluded-windows')
    chrome_options.add_argument('--disable-renderer-backgrounding')
    return chrome_options

# Google Sheets 스프레드시트 ID
지명업체키워드_스프레드시트_ID = "1KvoFOLpCqUNllL3EW3S8IRmi2tOsqvlQ-Nz1pPGekc8"
아이디2_스프레드시트_ID = "1JioOQCAlWxCpQnsr43UcQt9gWvCGDeFYlwlmT-m8B6s"
작업관리_스프레드시트_ID = "1WJlDmrd3YT8eXY68BoGP04aVb2O-9uzS7RdiKeZOGOk"
포스팅작업요청_스프레드시트_ID = "19bcagh4m6a_7th4XJ1PLlhMtC0Xm_Zo7pV_WlX1C-w0"

# gspread DeprecationWarning 억제
warnings.filterwarnings("ignore", category=DeprecationWarning, module="gspread")

def gspread_authorize_with_timeout(creds, timeout=25):
    """
    gspread.authorize()를 타임아웃과 함께 실행하는 함수
    
    Args:
        creds: Google 인증 자격 증명
        timeout: 타임아웃 시간 (초), 기본값 25초
    
    Returns:
        gspread 클라이언트 객체
    
    Raises:
        TimeoutError: 타임아웃 발생 시
    """
    result = [None]
    exception = [None]
    
    def authorize_thread():
        try:
            result[0] = gspread.authorize(creds)
        except Exception as e:
            exception[0] = e
    
    thread = threading.Thread(target=authorize_thread)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        raise TimeoutError(f"gspread.authorize()가 {timeout}초 내에 완료되지 않았습니다.")
    
    if exception[0]:
        raise exception[0]
    
    return result[0]

def gspread_operation_with_timeout(operation, timeout=20, operation_name="작업"):
    """
    gspread 작업을 타임아웃과 함께 실행하는 함수
    
    Args:
        operation: 실행할 작업 (lambda 함수)
        timeout: 타임아웃 시간 (초), 기본값 20초
        operation_name: 작업 이름 (로그용)
    
    Returns:
        작업 결과
    
    Raises:
        TimeoutError: 타임아웃 발생 시
    """
    result = [None]
    exception = [None]
    
    def operation_thread():
        try:
            result[0] = operation()
        except Exception as e:
            exception[0] = e
    
    thread = threading.Thread(target=operation_thread)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        raise TimeoutError(f"gspread {operation_name}이(가) {timeout}초 내에 완료되지 않았습니다.")
    
    if exception[0]:
        raise exception[0]
    
    return result[0]

def 작업_로그_저장(로그_내용, 로그_타입="INFO"):
    """작업 로그를 날짜별 txt 파일에 저장"""
    try:
        현재_시간 = datetime.datetime.now()
        시간_문자열 = 현재_시간.strftime('%Y-%m-%d %H:%M:%S')
        로그_파일명 = f"작업로그_{현재_시간.strftime('%Y%m%d')}.txt"
        로그_파일_경로 = resource_path(로그_파일명)
        스레드명 = threading.current_thread().name
        로그_라인 = f"[{시간_문자열}] [{로그_타입}] [{스레드명}] {로그_내용}\n"
        with open(로그_파일_경로, "a", encoding="utf-8") as f:
            f.write(로그_라인)
        return True
    except Exception as e:
        print(f"로그 저장 중 오류 발생: {e}")
        return False


def 중요_작업_로그_저장(로그_내용):
    """중요 작업 로그 저장"""
    return 작업_로그_저장(로그_내용, "중요")


def 오류_로그_저장(로그_내용):
    """오류 로그 저장 - 현재 예외의 traceback 자동 포함"""
    import traceback as _tb
    tb = _tb.format_exc()
    if tb and tb.strip() not in ('NoneType: None', 'None'):
        로그_내용 = f"{로그_내용}\n{tb.strip()}"
    return 작업_로그_저장(로그_내용, "오류")


def 디버그_로그_저장(로그_내용):
    """상세 디버그 로그 저장 (버그 추적용)"""
    import traceback as _tb
    import inspect
    try:
        호출자 = inspect.stack()[1]
        위치 = f"{os.path.basename(호출자.filename)}:{호출자.lineno} {호출자.function}()"
    except Exception:
        위치 = "unknown"
    return 작업_로그_저장(f"[{위치}] {로그_내용}", "DEBUG")

def 이미지_중복_회피_변형(원본_이미지_경로, 출력_이미지_경로=None, 최대_재시도=5):
    """이미지를 중복 감지 회피를 위해 변형하는 함수 (안정성 강화, 재시도 로직 포함)"""
    재시도_횟수 = 0
    while 재시도_횟수 < 최대_재시도:
        임시_출력_경로 = None
        try:
            # 타겟키워드(지명키워드) 가져오기
            타겟키워드 = ""
            try:
                지명키워드_df = 지명키워드_df_가져오기()
                if not 지명키워드_df.empty and '지명키워드' in 지명키워드_df.columns:
                    타겟키워드 = str(지명키워드_df.iloc[0]['지명키워드']).strip()
                    # 파일명에 사용할 수 없는 문자 제거
                    타겟키워드 = 타겟키워드.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_').replace(' ', '_')
            except Exception as e:
                print(f"지명키워드 가져오기 실패: {e}")
                타겟키워드 = "image"
            
            # 출력 경로 생성: 원본파일명_타겟키워드_랜덤.jpg (동일 초 다중 처리 시 충돌 방지)
            원본_디렉 = os.path.dirname(os.path.abspath(원본_이미지_경로))
            원본_베이스 = os.path.splitext(os.path.basename(원본_이미지_경로))[0]
            키워드_접두 = (타겟키워드 or 'image').strip('_')
            랜덤_숫자 = random.randint(1000, 9999)
            if 출력_이미지_경로 is None:
                임시_출력_경로 = os.path.join(
                    원본_디렉,
                    f'{원본_베이스}_{키워드_접두}_{랜덤_숫자}.jpg',
                )
            else:
                base, _ = os.path.splitext(출력_이미지_경로)
                임시_출력_경로 = f'{base}_{키워드_접두}_{랜덤_숫자}.jpg'

            # 이미지 열기
            이미지 = Image.open(원본_이미지_경로)

            # EXIF Orientation을 픽셀에 반영 후 저장 (제거만 하면 90도 눕힘 현상)
            try:
                이미지 = ImageOps.exif_transpose(이미지)
            except Exception:
                pass

            # 안전 모드 변환: 모든 이미지를 RGB로 통일 (알파 제거)
            try:
                if 이미지.mode != 'RGB':
                    이미지 = 이미지.convert('RGB')
            except Exception:
                pass

            # EXIF 제거: PIL은 JPEG 저장 시 기본적으로 EXIF 재삽입을 하지 않으므로
            # 별도 조치 없이 저장 과정에서 사실상 제거됨. 추가 안전 처리로 info 초기화 시도.
            try:
                if hasattr(이미지, "info"):
                    이미지.info = {}
            except Exception:
                pass

            # 변형 타입 선택 (밝기/대비/색상/크롭만, 회전 미사용)
            가능한_변형 = ['brightness', 'contrast', 'color', 'crop']
            변형_타입 = random.choice(가능한_변형)
            변형_성공 = False

            try:
                if 변형_타입 == 'brightness':
                    enhancer = ImageEnhance.Brightness(이미지)
                    이미지 = enhancer.enhance(random.uniform(0.98, 1.02))
                    변형_성공 = True
                elif 변형_타입 == 'contrast':
                    enhancer = ImageEnhance.Contrast(이미지)
                    이미지 = enhancer.enhance(random.uniform(0.98, 1.02))
                    변형_성공 = True
                elif 변형_타입 == 'color':
                    enhancer = ImageEnhance.Color(이미지)
                    이미지 = enhancer.enhance(random.uniform(0.98, 1.02))
                    변형_성공 = True
                elif 변형_타입 == 'crop':
                    width, height = 이미지.size
                    crop_size = min(3, max(1, int(min(width, height) * 0.001)))  # 화면 대비 0.1% 내외
                    이미지 = 이미지.crop((crop_size, crop_size, width - crop_size, height - crop_size))
                    이미지 = 이미지.resize((width, height), Image.Resampling.LANCZOS)
                    변형_성공 = True
            except Exception as te:
                오류_로그_저장(f"이미지 변형 단계 오류({변형_타입}): {te}")
                변형_성공 = False

            # 변형 실패 시: 품질만 조정하여 저장 시도
            품질 = random.randint(82, 96)
            try:
                이미지.save(임시_출력_경로, 'JPEG', quality=품질, optimize=True)
            except Exception as se:
                # 저장 실패 시 한 번 더 보수적으로 시도
                try:
                    이미지 = 이미지.copy()
                    이미지.save(임시_출력_경로, 'JPEG', quality=90, optimize=True)
                except Exception as se2:
                    raise se2

            # 파일 존재 및 0바이트 체크
            if not os.path.exists(임시_출력_경로):
                raise Exception("이미지 저장 후 파일이 존재하지 않음")
            if os.path.getsize(임시_출력_경로) <= 0:
                # 0바이트 파일이면 삭제 후 실패 처리
                try:
                    os.remove(임시_출력_경로)
                except Exception:
                    pass
                raise Exception("이미지 저장 후 파일 크기가 0")

            작업_로그_저장(f"이미지 중복 회피 변형 완료 (시도 {재시도_횟수+1}): {원본_이미지_경로} -> {임시_출력_경로}")
            return 임시_출력_경로

        except Exception as e:
            # 실패 시 임시 출력 파일 정리
            try:
                if 임시_출력_경로 and os.path.exists(임시_출력_경로) and os.path.getsize(임시_출력_경로) == 0:
                    os.remove(임시_출력_경로)
            except Exception:
                pass

            재시도_횟수 += 1
            오류_로그_저장(f"이미지 중복 회피 변형 {재시도_횟수}번째 시도 실패: {e}")
            if 재시도_횟수 < 최대_재시도:
                print(f"이미지 변형 {재시도_횟수}번째 시도 실패, 2초 후 재시도...")
                time.sleep(2)
            else:
                print(f"이미지 변형 최대 재시도 횟수({최대_재시도}) 도달, 원본 사용")
                오류_로그_저장(f"이미지 중복 회피 변형 최대 재시도 횟수 도달: {원본_이미지_경로}")
                return 원본_이미지_경로

def 이미지_해시_변경(이미지_경로, 최대_재시도=3):
    """이미지의 해시값을 변경하기 위해 미세한 변형을 적용하는 함수 (재시도 로직 포함)"""
    재시도_횟수 = 0
    
    while 재시도_횟수 < 최대_재시도:
        try:
            # 현재 시간+원본 경로를 시드로 사용 (같은 초 다중 처리 시 파일명 충돌 방지)
            random.seed(int(time.time()) + 재시도_횟수 + (hash(이미지_경로) & 0xFFFFFF))
            
            # 변형된 이미지 생성
            변형된_경로 = 이미지_중복_회피_변형(이미지_경로)
            
            if 변형된_경로:
                작업_로그_저장(f"이미지 해시 변경 완료 (시도 {재시도_횟수+1}): {변형된_경로}")
                return 변형된_경로
            else:
                재시도_횟수 += 1
                if 재시도_횟수 < 최대_재시도:
                    print(f"이미지 해시 변경 {재시도_횟수}번째 시도 실패, 1초 후 재시도...")
                    time.sleep(1)
                else:
                    print(f"이미지 해시 변경 최대 재시도 횟수({최대_재시도}) 도달, 원본 사용")
                    오류_로그_저장(f"이미지 해시 변경 최대 재시도 횟수 도달, 원본 사용: {이미지_경로}")
                    return 이미지_경로
                
        except Exception as e:
            재시도_횟수 += 1
            오류_로그_저장(f"이미지 해시 변경 {재시도_횟수}번째 시도 실패: {e}")
            
            if 재시도_횟수 < 최대_재시도:
                print(f"이미지 해시 변경 {재시도_횟수}번째 시도 실패, 1초 후 재시도...")
                time.sleep(1)
            else:
                print(f"이미지 해시 변경 최대 재시도 횟수({최대_재시도}) 도달, 원본 사용")
                오류_로그_저장(f"이미지 해시 변경 최대 재시도 횟수 도달, 원본 사용: {이미지_경로}")
                return 이미지_경로

def 이미지_업로드_전_처리(이미지_경로, 최대_재시도=3):
    """이미지 업로드 전 중복 회피 처리를 수행하는 함수 (재시도 로직 포함)"""
    재시도_횟수 = 0
    
    while 재시도_횟수 < 최대_재시도:
        try:
            작업_로그_저장(f"이미지 업로드 전 처리 시작 (시도 {재시도_횟수+1}): {이미지_경로}")
            
            # 이미지가 존재하는지 확인
            if not os.path.exists(이미지_경로):
                오류_로그_저장(f"이미지 파일이 존재하지 않습니다: {이미지_경로}")
                return 이미지_경로
            
            # 중복 회피 변형 적용
            처리된_이미지_경로 = 이미지_해시_변경(이미지_경로)
            
            if 처리된_이미지_경로 and os.path.exists(처리된_이미지_경로):
                작업_로그_저장(f"이미지 업로드 전 처리 완료 (시도 {재시도_횟수+1}): {처리된_이미지_경로}")
                return 처리된_이미지_경로
            else:
                재시도_횟수 += 1
                if 재시도_횟수 < 최대_재시도:
                    print(f"이미지 업로드 전 처리 {재시도_횟수}번째 시도 실패, 1초 후 재시도...")
                    time.sleep(1)
                else:
                    print(f"이미지 업로드 전 처리 최대 재시도 횟수({최대_재시도}) 도달, 원본 사용")
                    오류_로그_저장(f"이미지 업로드 전 처리 최대 재시도 횟수 도달, 원본 사용: {이미지_경로}")
                    return 이미지_경로
                
        except Exception as e:
            재시도_횟수 += 1
            오류_로그_저장(f"이미지 업로드 전 처리 {재시도_횟수}번째 시도 실패: {e}")
            
            if 재시도_횟수 < 최대_재시도:
                print(f"이미지 업로드 전 처리 {재시도_횟수}번째 시도 실패, 1초 후 재시도...")
                time.sleep(1)
            else:
                print(f"이미지 업로드 전 처리 최대 재시도 횟수({최대_재시도}) 도달, 원본 사용")
                오류_로그_저장(f"이미지 업로드 전 처리 최대 재시도 횟수 도달, 원본 사용: {이미지_경로}")
                return 이미지_경로

def 다음_이미지_폴더_선택():
    """img2와 img3 폴더를 번갈아 사용하기 위한 함수"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        last_folder_file = os.path.join(script_dir, "last_img_folder.txt")
        
        # 마지막 사용 폴더 읽기
        if os.path.exists(last_folder_file):
            with open(last_folder_file, "r", encoding="utf-8") as f:
                last_folder = f.read().strip()
            
            # 다음 폴더 선택 (번갈아 사용)
            if last_folder == "img2":
                next_folder = "img3"
            elif last_folder == "img3":
                next_folder = "img2"
            else:
                # 잘못된 값이면 랜덤 선택
                next_folder = random.choice(["img2", "img3"])
        else:
            # 파일이 없으면 랜덤 선택
            next_folder = random.choice(["img2", "img3"])
        
        # 선택한 폴더 저장
        with open(last_folder_file, "w", encoding="utf-8") as f:
            f.write(next_folder)
        
        print(f"이미지 폴더 선택: {next_folder}")
        return next_folder
        
    except Exception as e:
        print(f"이미지 폴더 선택 중 오류: {e}")
        # 오류 발생 시 기본값 img2 사용
        return "img2"

def _used_images_파일_경로():
    """사용 이미지 기록 파일 (_internal/used_images.txt)"""
    new_path = resource_path('used_images.txt')
    # 예전 위치(프로젝트 루트)에 있으면 _internal로 이전
    try:
        old_path = os.path.join(_앱_루트_경로(), 'used_images.txt')
        if os.path.exists(old_path) and not os.path.exists(new_path):
            import shutil
            shutil.move(old_path, new_path)
            print(f"used_images.txt -> _internal 로 이전: {new_path}")
    except Exception as e:
        print(f"used_images.txt 이전 실패 (무시): {e}")
    return new_path


def _used_images_폴더_기록_초기화(폴더명):
    """해당 폴더 기록만 삭제 (다른 폴더 img/img2/img3 기록 유지)"""
    used_images_file = _used_images_파일_경로()
    if not os.path.exists(used_images_file):
        return
    try:
        remaining = []
        with open(used_images_file, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if not stripped or ':' not in stripped:
                    if stripped:
                        remaining.append(stripped + '\n')
                    continue
                rec_folder, _ = stripped.split(':', 1)
                if rec_folder != 폴더명:
                    remaining.append(stripped + '\n')
        with open(used_images_file, 'w', encoding='utf-8') as f:
            f.writelines(remaining)
    except Exception as e:
        print(f"이미지 사용 기록 초기화 오류 ({폴더명}): {e}")


def 사용한_이미지_기록(이미지_파일명, 폴더명):
    """사용한 이미지를 기록하는 함수"""
    try:
        used_images_file = _used_images_파일_경로()
        
        # 사용한 이미지 기록 (폴더명:파일명 형식)
        기록_내용 = f"{폴더명}:{이미지_파일명}\n"
        
        with open(used_images_file, "a", encoding="utf-8") as f:
            f.write(기록_내용)
        
    except Exception as e:
        print(f"사용한 이미지 기록 중 오류: {e}")

def 사용하지_않은_이미지_선택(img_dir, selected_folder):
    """사용하지 않은 이미지만 선택하는 함수"""
    try:
        used_images_file = _used_images_파일_경로()
        
        # 사용한 이미지 목록 읽기
        사용한_이미지_목록 = set()
        if os.path.exists(used_images_file):
            with open(used_images_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and ":" in line:
                        폴더명, 파일명 = line.split(":", 1)
                        if 폴더명 == selected_folder:
                            사용한_이미지_목록.add(파일명)
        
        # 폴더 내 모든 이미지 파일 가져오기
        모든_후보 = [f for f in os.listdir(img_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        
        # 사용하지 않은 이미지만 필터링
        미사용_후보 = [f for f in 모든_후보 if f not in 사용한_이미지_목록]
        
        # 사용하지 않은 이미지가 없으면 해당 폴더만 재사용 (리셋)
        if not 미사용_후보:
            print(f"{selected_folder} 폴더의 모든 이미지를 사용했습니다. 해당 폴더 사용 기록만 초기화합니다.")
            _used_images_폴더_기록_초기화(selected_folder)
            print(f"이미지 사용 기록 초기화 완료: {selected_folder}")
            # 모든 이미지를 다시 후보로 사용
            미사용_후보 = 모든_후보
        
        if 미사용_후보:
            선택된_파일 = random.choice(미사용_후보)
            # 사용한 이미지 기록
            사용한_이미지_기록(선택된_파일, selected_folder)
            return 선택된_파일
        else:
            return None
            
    except Exception as e:
        print(f"사용하지 않은 이미지 선택 중 오류: {e}")
        오류_로그_저장(f"사용하지 않은 이미지 선택 오류: {e}")
        return None

def _추천모델_가져오기(제목=None):
    """블로그제목.xlsx에서 현재 포스팅에 쓸 추천모델 반환"""
    try:
        path = resource_path('블로그제목.xlsx')
        if not os.path.exists(path):
            return None
        df = pd.read_excel(path)
        if '추천모델' not in df.columns:
            return None
        if 제목 and '생성된제목' in df.columns:
            matched = df[df['생성된제목'].astype(str).str.strip() == str(제목).strip()]
            if not matched.empty:
                모델 = str(matched.iloc[0]['추천모델']).strip()
                if 모델 and 모델.lower() != 'nan':
                    return 모델
        if len(df) > 0:
            모델 = str(df.iloc[0]['추천모델']).strip()
            if 모델 and 모델.lower() != 'nan':
                return 모델
    except Exception as e:
        print(f"추천모델 읽기 실패: {e}")
    return None


def _블로그_글유형_가져오기():
    """블로그제목.xlsx에서 현재 포스팅에 사용된 글유형 반환"""
    try:
        path = resource_path('블로그제목.xlsx')
        if not os.path.exists(path):
            return ''
        df = pd.read_excel(path)
        if df.empty or '유형' not in df.columns:
            return ''
        현재_kw = _현재_작업_지명키워드()
        row = _블로그제목_현재키워드_행_선택(df, 현재_kw)
        if row is None:
            v = str(df.iloc[0]['유형']).strip()
        else:
            v = str(row['유형']).strip()
        if v.lower() in ('nan', 'none', ''):
            return ''
        return v
    except Exception as e:
        print(f"글유형 읽기 실패: {e}")
        return ''


def _블로그_세부유형_가져오기():
    """블로그제목.xlsx에서 현재 포스팅에 사용된 FAQ 세부유형 반환"""
    try:
        path = resource_path('블로그제목.xlsx')
        if not os.path.exists(path):
            return ''
        df = pd.read_excel(path)
        if df.empty or '세부유형' not in df.columns:
            return ''
        현재_kw = _현재_작업_지명키워드()
        row = _블로그제목_현재키워드_행_선택(df, 현재_kw)
        if row is None:
            return ''
        v = str(row.get('세부유형', '')).strip()
        if v.lower() in ('nan', 'none', ''):
            return ''
        return v
    except Exception as e:
        print(f"세부유형 읽기 실패: {e}")
        return ''


def _하나노란1_이미지_선택(하나노란_값):
    """1번이미지/{하나노란}/ 폴더에서 미사용 이미지 1장 랜덤 선택. 경로 또는 None."""
    if not 하나노란_값 or str(하나노란_값).strip().lower() in ('', 'nan', 'none'):
        return None
    하나노란_값 = str(하나노란_값).strip()
    img_dir = resource_path(os.path.join('1번이미지', 하나노란_값))
    record_key = f'1번이미지/{하나노란_값}'
    if not os.path.isdir(img_dir):
        print(f"1번이미지 폴더 없음: {img_dir}")
        return None
    선택_파일 = 사용하지_않은_이미지_선택(img_dir, record_key)
    if not 선택_파일:
        print(f"1번이미지/{하나노란_값} 에 사용 가능한 이미지 없음")
        return None
    full_path = os.path.join(img_dir, 선택_파일)
    print(f"1번이미지/{하나노란_값} 에서 선택: {선택_파일}")
    return full_path


def _하나노란2_이미지_선택(하나노란_값):
    """하나노란2/{하나노란}/ 폴더에서 미사용 이미지 1장 랜덤 선택. 경로 또는 None."""
    if not 하나노란_값 or str(하나노란_값).strip().lower() in ('', 'nan', 'none'):
        return None
    하나노란_값 = str(하나노란_값).strip()
    img_dir = resource_path(os.path.join('하나노란2', 하나노란_값))
    record_key = f'하나노란2/{하나노란_값}'
    if not os.path.isdir(img_dir):
        print(f"하나노란2 폴더 없음: {img_dir}")
        return None
    선택_파일 = 사용하지_않은_이미지_선택(img_dir, record_key)
    if not 선택_파일:
        print(f"하나노란2/{하나노란_값} 에 사용 가능한 이미지 없음")
        return None
    full_path = os.path.join(img_dir, 선택_파일)
    print(f"하나노란2/{하나노란_값} 에서 선택: {선택_파일}")
    return full_path


def _폴더_사용_이미지_목록(record_key):
    """used_images.txt 에서 해당 폴더 키의 사용 파일명 set 반환"""
    used = set()
    used_images_file = _used_images_파일_경로()
    if not os.path.exists(used_images_file):
        return used
    try:
        with open(used_images_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and ':' in line:
                    folder, fname = line.split(':', 1)
                    if folder == record_key:
                        used.add(fname)
    except Exception:
        pass
    return used


def _2번이미지_세트_순번(경로):
    """파일명에서 세트 순번(1~3) 추출. _01~_03, 1.png 형식 모두 지원."""
    base = os.path.basename(str(경로))
    # 01_키워드_03.png / xxx_03_image_1234.jpg -> 끝쪽 _NN 이 세트 순번
    tail_nums = re.findall(
        r'(?:^|_)(0?[1-3])(?=\.(?:png|jpg|jpeg)$|_(?:image|modified|[^.]+)\.(?:png|jpg|jpeg)$)',
        base,
        re.I,
    )
    if tail_nums:
        return int(tail_nums[-1])
    tail_nums = re.findall(r'_(0?[1-3])(?=\.(?:png|jpg|jpeg)$)', base, re.I)
    if tail_nums:
        return int(tail_nums[-1])
    m = re.match(r'^(0?[1-3])\.(?:png|jpg|jpeg)$', base, re.I)
    if m:
        return int(m.group(1))
    return 999


def _2번이미지_세트_순서_정렬(경로_목록):
    """2번이미지 세트 경로를 1, 2, 3 순으로 정렬"""
    return sorted(경로_목록, key=lambda p: (_2번이미지_세트_순번(p), os.path.basename(str(p))))


def _2번이미지_세트_첨부_순서(경로_목록):
    """파일 대화상자 첨부 문자열 순서: 1 -> 2 -> 3"""
    by_seq = {}
    for p in 경로_목록:
        n = _2번이미지_세트_순번(p)
        if 1 <= n <= 3:
            by_seq[n] = p
    ordered = [by_seq[n] for n in (1, 2, 3) if n in by_seq]
    for p in 경로_목록:
        if p not in ordered:
            ordered.append(p)
    return ordered


def _2번이미지_세트_목록(img_dir):
    """{prefix}_01~03.ext 형태 3장 세트 목록 반환. 각 항목은 [파일1, 파일2, 파일3]"""
    groups = {}
    for fname in os.listdir(img_dir):
        if not fname.lower().endswith(('.png', '.jpg', '.jpeg')):
            continue
        m = re.match(r'^(.+)_(\d{2})\.(png|jpg|jpeg)$', fname, re.I)
        if not m:
            continue
        prefix, seq, ext = m.group(1), m.group(2), m.group(3).lower()
        key = f'{prefix}.{ext}'
        groups.setdefault(key, {})[seq] = fname
    sets = []
    for key, seq_map in groups.items():
        if all(seq in seq_map for seq in ('01', '02', '03')):
            sets.append([seq_map['01'], seq_map['02'], seq_map['03']])
    return sets


def _2번이미지_세트_선택():
    """_internal/2번이미지/ 에서 _01~_03 세트 1묶음(3장) 랜덤 선택. 경로 list 또는 None."""
    img_dir = resource_path('2번이미지')
    record_key = '2번이미지'
    if not os.path.isdir(img_dir):
        print(f'2번이미지 폴더 없음: {img_dir}')
        return None

    def _미사용_세트_고르기():
        used = _폴더_사용_이미지_목록(record_key)
        candidates = []
        for file_triple in _2번이미지_세트_목록(img_dir):
            if not any(name in used for name in file_triple):
                candidates.append(file_triple)
        return candidates

    candidates = _미사용_세트_고르기()
    if not candidates:
        all_sets = _2번이미지_세트_목록(img_dir)
        if all_sets:
            print(f'{record_key} 세트를 모두 사용했습니다. 사용 기록을 초기화합니다.')
            _used_images_폴더_기록_초기화(record_key)
            candidates = _미사용_세트_고르기()
    if not candidates:
        print('2번이미지 폴더에 사용 가능한 3장 세트 없음')
        return None

    chosen = random.choice(candidates)
    for fname in chosen:
        사용한_이미지_기록(fname, record_key)
    paths = _2번이미지_세트_순서_정렬([os.path.join(img_dir, fname) for fname in chosen])
    print(f'2번이미지 세트 선택: {", ".join(os.path.basename(p) for p in paths)}')
    return paths


def _2번이미지_3장_대상_하나노란(하나노란_값):
    """2번째 이미지 3장 세트 대상: 값이 '노란우산렌탈'이거나 문자열에 '노란우산렌탈' 포함"""
    v = str(하나노란_값 or '').strip()
    if not v or v.lower() in ('nan', 'none'):
        return False
    return v == '노란우산렌탈' or '노란우산렌탈' in v


def _파일선택_입력_문자열(파일경로_목록):
    """Windows 파일 열기 대화상자 파일명 입력란 문자열 (전체 경로 방식)"""
    if len(파일경로_목록) == 1:
        return os.path.abspath(파일경로_목록[0])
    return ' '.join(f'"{os.path.abspath(p)}"' for p in 파일경로_목록)


def _네이버_다중이미지_슬라이드_방식_선택(driver, timeout=15):
    """다중 이미지 업로드 후 사진 첨부 방식 팝업에서 슬라이드(3번째) 선택"""
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    try:
        wait = WebDriverWait(driver, timeout)
        popup = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, '.se-popup-image-type')))
        slide_label = None
        for selector in (
            '.se-popup-content ul li:nth-child(3) label',
            'li:nth-child(3) label',
        ):
            try:
                candidate = popup.find_element(By.CSS_SELECTOR, selector)
                if candidate.is_displayed():
                    slide_label = candidate
                    break
            except Exception:
                continue
        if slide_label is None:
            for label in popup.find_elements(By.CSS_SELECTOR, 'label'):
                text = (label.text or '').strip()
                if '슬라이드' in text and label.is_displayed():
                    slide_label = label
                    break
        if slide_label is None:
            print('다중 이미지: 슬라이드 방식 옵션을 찾지 못했습니다.')
            return False
        driver.execute_script('arguments[0].click();', slide_label)
        print('다중 이미지: 슬라이드 방식 선택')
        작업_로그_저장('다중 이미지 슬라이드 방식 선택')
        time.sleep(1)
        for confirm_sel in (
            '.se-popup-button-confirm',
            'button.se-popup-button-confirm',
            '.se-popup-image-type .se-popup-button-confirm',
        ):
            try:
                btn = driver.find_element(By.CSS_SELECTOR, confirm_sel)
                if btn.is_displayed():
                    driver.execute_script('arguments[0].click();', btn)
                    print('다중 이미지: 슬라이드 확인 버튼 클릭')
                    break
            except Exception:
                continue
        return True
    except Exception as e:
        print(f'다중 이미지 슬라이드 선택 오류: {e}')
        오류_로그_저장(f'다중 이미지 슬라이드 선택 오류: {e}')
        return False


def _블로그_이미지_파일선택_삽입(driver, 파일경로_목록, esc_후_재클릭=False, 첨부_문자열=None):
    """파일 선택 대화상자로 이미지 1장 또는 여러 장 삽입 (전체 경로 paste)"""
    import pyautogui
    import pygetwindow as gw

    if not 파일경로_목록:
        return False

    image_button = driver.find_element(By.CSS_SELECTOR, '.se-toolbar-item-image')
    image_button.click()
    if esc_후_재클릭:
        time.sleep(5)
        pyautogui.press('esc')
        time.sleep(3)
        image_button = driver.find_element(By.CSS_SELECTOR, '.se-toolbar-item-image')
        image_button.click()
    time.sleep(10)

    try:
        windows = gw.getWindowsWithTitle('열기')
        if windows:
            windows[0].activate()
            time.sleep(0.5)
    except Exception:
        pass

    pyautogui.hotkey('alt', 'n')
    time.sleep(1)
    pyperclip.copy(첨부_문자열 or _파일선택_입력_문자열(파일경로_목록))
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(10)
    pyautogui.press('enter')
    time.sleep(2)
    if len(파일경로_목록) > 1:
        _네이버_다중이미지_슬라이드_방식_선택(driver)
    time.sleep(30)
    return True


def _작업_하나노란_값(fallback=None):
    """작업큐 캐시 또는 인자에서 하나노란 값 반환"""
    if fallback and str(fallback).strip().lower() not in ('', 'nan', 'none'):
        return str(fallback).strip()
    try:
        df = 지명키워드_df_가져오기()
        if not df.empty and '하나노란' in df.columns:
            v = str(df.iloc[0]['하나노란']).strip()
            if v.lower() not in ('', 'nan', 'none'):
                return v
    except Exception:
        pass
    return None


def _img_폴더_해석(base_folder, 추천모델=None):
    """img2/img3에서 추천모델 하위 폴더 우선, 없으면 기본 폴더"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_path = os.path.join(script_dir, base_folder)
    if not os.path.isdir(base_path):
        return base_path, base_folder

    if 추천모델 and str(추천모델).strip():
        model = str(추천모델).strip()
        model_path = os.path.join(base_path, model)
        if os.path.isdir(model_path):
            has_images = any(
                os.path.isfile(os.path.join(model_path, f))
                and f.lower().endswith(('.png', '.jpg', '.jpeg'))
                for f in os.listdir(model_path)
            )
            if has_images:
                record_key = f"{base_folder}/{model}"
                print(f"이미지 폴더: {record_key}")
                return model_path, record_key
            print(f"모델 폴더 '{model}'에 이미지 없음 -> {base_folder} 기본 사용")
        else:
            print(f"모델 폴더 '{model}' 없음 -> {base_folder} 기본 사용")

    return base_path, base_folder

# Google Sheets 연동 함수들
def 구글_시트_연결():
    """Google Sheets에 연결하는 함수"""
    import socket
    import time
    
    # 서비스 계정 키 파일 경로
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    
    # 1. 파일 존재 여부 확인
    if not os.path.exists(키_파일_경로):
        print(f"오류: {키_파일_경로} 파일을 찾을 수 없습니다.")
        return None
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 2. 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 3. 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                # 5. 진행상황 출력
                if 시도_횟수 > 0:
                    print(f"구글 시트 연결 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 인증 범위 설정
                스코프 = [
                    'https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive'
                ]
                
                # 서비스 계정 인증
                인증 = Credentials.from_service_account_file(키_파일_경로, scopes=스코프)
                
                # gspread 클라이언트 생성
                클라이언트 = gspread_authorize_with_timeout(인증)
                
                if 시도_횟수 > 0:
                    print(f"구글 시트 연결 성공! (시도 {시도_횟수 + 1}회)")
                
                return 클라이언트
                
            except (socket.timeout, TimeoutError):
                # 4. socket.timeout 예외 발생 시 30초 대기 후 재시도
                print(f"연결 타임아웃 발생 (시도 {시도_횟수 + 1}/10). 30초 대기 후 재시도합니다...")
                if 시도_횟수 < 9:  # 마지막 시도가 아니면 대기
                    time.sleep(30)
                    
            except Exception as e:
                print(f"구글 시트 연결 중 오류 발생 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:  # 마지막 시도가 아니면 대기
                    time.sleep(5)
        
        print("구글 시트 연결 실패: 최대 재시도 횟수(10회)에 도달했습니다.")
        return None
        
    finally:
        # 6. 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def 구글_시트_읽기(스프레드시트_ID, 시트_이름="시트1"):
    """Google Sheets에서 데이터를 읽어오는 함수"""
    try:
        클라이언트 = 구글_시트_연결()
        if not 클라이언트:
            return None
            
        # 스프레드시트 열기
        스프레드시트 = gspread_operation_with_timeout(
            lambda: 클라이언트.open_by_key(스프레드시트_ID),
            timeout=20,
            operation_name="스프레드시트 열기"
        )
        
        # 시트 이름이 지정되지 않으면 첫 번째 시트 사용
        if 시트_이름 is None:
            시트 = gspread_operation_with_timeout(
                lambda: 스프레드시트.get_worksheet(0),
                timeout=20,
                operation_name="첫 번째 시트 가져오기"
            )
            print(f"첫 번째 시트 '{시트.title}'을 사용합니다.")
        else:
            try:
                시트 = gspread_operation_with_timeout(
                    lambda: 스프레드시트.worksheet(시트_이름),
                    timeout=20,
                    operation_name=f"시트 '{시트_이름}' 가져오기"
                )
                print(f"시트 '{시트_이름}'을 사용합니다.")
            except gspread.WorksheetNotFound:
                print(f"시트 '{시트_이름}'을 찾을 수 없습니다. 사용 가능한 시트 목록:")
                for i, ws in enumerate(스프레드시트.worksheets()):
                    print(f"  {i}: {ws.title}")
                # 첫 번째 시트로 fallback
                시트 = gspread_operation_with_timeout(
                    lambda: 스프레드시트.get_worksheet(0),
                    timeout=20,
                    operation_name="첫 번째 시트 가져오기(fallback)"
                )
                print(f"첫 번째 시트 '{시트.title}'을 사용합니다.")
        
        # 모든 데이터 가져오기 (헤더 포함)
        모든_값 = gspread_operation_with_timeout(
            lambda: 시트.get_all_values(),
            timeout=30,
            operation_name="모든 데이터 가져오기"
        )
        
        # 데이터가 비어있거나 헤더만 있는 경우 처리
        if not 모든_값 or len(모든_값) < 2:
            print("스프레드시트가 비어있거나 데이터가 없습니다.")
            return pd.DataFrame()
        
        # pandas DataFrame으로 변환 (첫 행을 헤더로 사용)
        df = pd.DataFrame(모든_값[1:], columns=모든_값[0])
        
        print(f"Google Sheets에서 {len(df)}개 행을 성공적으로 읽어왔습니다.")
        return df
        
    except Exception as e:
        print(f"Google Sheets 읽기 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None

def 구글_시트_특정_행_업데이트(스프레드시트_ID, 지명, 행_인덱스, 컬럼명, 새값, 시트_이름="시트1", 최대_재시도=3):
    """Google Sheets에서 특정 지명의 특정 행 인덱스에 해당하는 셀만 업데이트하는 함수"""
    import time
    
    for 시도_횟수 in range(최대_재시도):
        try:
            클라이언트 = 구글_시트_연결()
            if not 클라이언트:
                print(f"Google Sheets 연결 실패 (시도 {시도_횟수 + 1}/{최대_재시도})")
                if 시도_횟수 < 최대_재시도 - 1:
                    time.sleep(2)
                    continue
                return False
                
            # 스프레드시트 열기
            스프레드시트 = gspread_operation_with_timeout(
                lambda: 클라이언트.open_by_key(스프레드시트_ID),
                timeout=20,
                operation_name="스프레드시트 열기"
            )
            시트 = gspread_operation_with_timeout(
                lambda: 스프레드시트.worksheet(시트_이름),
                timeout=20,
                operation_name=f"시트 '{시트_이름}' 가져오기"
            )
            
            # 헤더 찾기
            헤더 = gspread_operation_with_timeout(
                lambda: 시트.row_values(1),
                timeout=20,
                operation_name="헤더 가져오기"
            )
            if 컬럼명 not in 헤더:
                print(f"컬럼 '{컬럼명}'을 찾을 수 없습니다.")
                return False
            
            컬럼_인덱스 = 헤더.index(컬럼명) + 1  # gspread는 1부터 시작
            행_번호 = 행_인덱스 + 2  # 헤더 다음부터 시작하므로 +2 (행_인덱스는 0부터 시작)
            
            # 업데이트 전 현재 값 확인
            현재_값 = gspread_operation_with_timeout(
                lambda: 시트.cell(행_번호, 컬럼_인덱스).value,
                timeout=20,
                operation_name="현재 값 가져오기"
            )
            print(f"업데이트 전 현재 값: {현재_값}")
            
            # 특정 셀 업데이트
            업데이트_값 = int(새값) if isinstance(새값, (int, float)) else str(새값)
            
            # 현재 값과 새 값이 같으면 업데이트 건너뛰기
            현재_값_숫자 = int(현재_값) if str(현재_값).isdigit() else 현재_값
            업데이트_값_숫자 = int(업데이트_값) if isinstance(업데이트_값, (int, float)) else 업데이트_값
            
            if str(현재_값_숫자) == str(업데이트_값_숫자):
                print(f"✅ 현재 값({현재_값})과 업데이트 값({업데이트_값})이 동일하여 업데이트를 건너뜁니다.")
                return True
            
            # 지명을 사용했으므로 +1 증가시켜야 함
            print(f"🔄 지명 사용으로 인한 업데이트: {현재_값} → {업데이트_값}")
            
            # 더 강력한 업데이트 방법 시도
            try:
                # 방법 1: update_cell 사용
                gspread_operation_with_timeout(
                    lambda: 시트.update_cell(행_번호, 컬럼_인덱스, 업데이트_값),
                    timeout=20,
                    operation_name="update_cell"
                )
                print(f"🔧 update_cell로 업데이트 시도: 행{행_번호}, 열{컬럼_인덱스}, 값{업데이트_값}")
            except Exception as e:
                print(f"❌ update_cell 실패: {e}")
                # 방법 2: batch_update 사용
                try:
                    gspread_operation_with_timeout(
                        lambda: 시트.batch_update([{
                            'range': f'{chr(64 + 컬럼_인덱스)}{행_번호}',
                            'values': [[업데이트_값]]
                        }]),
                        timeout=20,
                        operation_name="batch_update"
                    )
                    print(f"🔧 batch_update로 업데이트 시도: {chr(64 + 컬럼_인덱스)}{행_번호}, 값{업데이트_값}")
                except Exception as e2:
                    print(f"❌ batch_update도 실패: {e2}")
                    raise e2
            
            # 업데이트 후 값 검증
            time.sleep(2)
            업데이트_후_값 = gspread_operation_with_timeout(
                lambda: 시트.cell(행_번호, 컬럼_인덱스).value,
                timeout=20,
                operation_name="업데이트 후 값 확인"
            )
            print(f"업데이트 후 확인 값: {업데이트_후_값}")
            
            # 값 비교 시 타입 변환 고려
            예상_값_문자열 = str(업데이트_값)
            실제_값_문자열 = str(업데이트_후_값)
            
            print(f"🔍 디버깅: 업데이트_값={업데이트_값} (타입: {type(업데이트_값)})")
            print(f"🔍 디버깅: 업데이트_후_값={업데이트_후_값} (타입: {type(업데이트_후_값)})")
            print(f"🔍 디버깅: 예상_값_문자열='{예상_값_문자열}', 실제_값_문자열='{실제_값_문자열}'")
            print(f"🔍 디버깅: 비교 결과 = {실제_값_문자열 == 예상_값_문자열}")
            
            if 실제_값_문자열 == 예상_값_문자열:
                print(f"✅ Google Sheets에서 지명 '{지명}'의 '{컬럼명}' 값을 '{업데이트_값}'으로 성공적으로 업데이트했습니다.")
                return True
            else:
                print(f"❌ 업데이트 검증 실패: 예상값 '{예상_값_문자열}', 실제값 '{실제_값_문자열}'")
                print(f"❌ 업데이트가 실제로 반영되지 않았습니다. 재시도합니다.")
                if 시도_횟수 < 최대_재시도 - 1:
                    time.sleep(3)
                    continue
                return False
                
        except Exception as e:
            print(f"Google Sheets 특정 행 업데이트 중 오류 발생 (시도 {시도_횟수 + 1}/{최대_재시도}): {e}")
            if 시도_횟수 < 최대_재시도 - 1:
                # 429 에러 (API 할당량 초과)인 경우 더 긴 대기 시간 설정
                if hasattr(e, 'response') and hasattr(e.response, 'status_code') and e.response.status_code == 429:
                    대기_시간 = 65 + (시도_횟수 * 5)  # 65초부터 시작하여 시도마다 5초씩 증가
                    print(f"⚠️ API 할당량 초과로 인해 {대기_시간}초 대기 후 재시도합니다...")
                    time.sleep(대기_시간)
                elif '429' in str(e) or 'RATE_LIMIT_EXCEEDED' in str(e) or 'Quota exceeded' in str(e):
                    대기_시간 = 65 + (시도_횟수 * 5)  # 65초부터 시작하여 시도마다 5초씩 증가
                    print(f"⚠️ API 할당량 초과로 인해 {대기_시간}초 대기 후 재시도합니다...")
                    time.sleep(대기_시간)
                else:
                    time.sleep(2)
                continue
            return False
    
    print(f"❌ 최대 재시도 횟수({최대_재시도})를 초과하여 업데이트에 실패했습니다.")
    return False

def 구글_시트_특정셀_업데이트(스프레드시트_ID, 지명, 컬럼명, 새값, 시트_이름="시트1", 최대_재시도=3):
    """Google Sheets에서 특정 지명의 특정 컬럼 값만 업데이트하는 함수 (재시도 로직 포함)"""
    import time
    
    for 시도_횟수 in range(최대_재시도):
        try:
            클라이언트 = 구글_시트_연결()
            if not 클라이언트:
                print(f"Google Sheets 연결 실패 (시도 {시도_횟수 + 1}/{최대_재시도})")
                if 시도_횟수 < 최대_재시도 - 1:
                    time.sleep(2)  # 2초 대기 후 재시도
                    continue
                return False
                
            # 스프레드시트 열기
            스프레드시트 = gspread_operation_with_timeout(
                lambda: 클라이언트.open_by_key(스프레드시트_ID),
                timeout=20,
                operation_name="스프레드시트 열기"
            )
            시트 = gspread_operation_with_timeout(
                lambda: 스프레드시트.worksheet(시트_이름),
                timeout=20,
                operation_name=f"시트 '{시트_이름}' 가져오기"
            )
            
            # 모든 데이터 가져오기
            모든_데이터 = gspread_operation_with_timeout(
                lambda: 시트.get_all_records(),
                timeout=30,
                operation_name="모든 데이터 가져오기"
            )
            
            # 지명이 일치하는 행 찾기
            for i, 행 in enumerate(모든_데이터):
                if 행.get('지명') == 지명:
                    # 헤더 행 찾기
                    헤더 = gspread_operation_with_timeout(
                        lambda: 시트.row_values(1),
                        timeout=20,
                        operation_name="헤더 가져오기"
                    )
                    if 컬럼명 in 헤더:
                        컬럼_인덱스 = 헤더.index(컬럼명) + 1  # gspread는 1부터 시작
                        행_번호 = i + 2  # 헤더 다음부터 시작하므로 +2
                        
                        # 업데이트 전 현재 값 확인
                        현재_값 = gspread_operation_with_timeout(
                            lambda: 시트.cell(행_번호, 컬럼_인덱스).value,
                            timeout=20,
                            operation_name="현재 값 가져오기"
                        )
                        print(f"업데이트 전 현재 값: {현재_값}")
                        
                        # 특정 셀 업데이트 (int64 타입을 일반 int로 변환)
                        업데이트_값 = int(새값) if isinstance(새값, (int, float)) else str(새값)
                        
                        # 지명을 사용했으므로 무조건 +1 증가시켜야 함
                        print(f"🔄 지명 사용으로 인한 강제 업데이트: {현재_값} → {업데이트_값}")
                        
                        # 더 강력한 업데이트 방법 시도
                        try:
                            # 방법 1: update_cell 사용
                            gspread_operation_with_timeout(
                                lambda: 시트.update_cell(행_번호, 컬럼_인덱스, 업데이트_값),
                                timeout=20,
                                operation_name="update_cell"
                            )
                            print(f"🔧 update_cell로 업데이트 시도: 행{행_번호}, 열{컬럼_인덱스}, 값{업데이트_값}")
                        except Exception as e:
                            print(f"❌ update_cell 실패: {e}")
                            # 방법 2: batch_update 사용
                            try:
                                gspread_operation_with_timeout(
                                    lambda: 시트.batch_update([{
                                        'range': f'{chr(64 + 컬럼_인덱스)}{행_번호}',
                                        'values': [[업데이트_값]]
                                    }]),
                                    timeout=20,
                                    operation_name="batch_update"
                                )
                                print(f"🔧 batch_update로 업데이트 시도: {chr(64 + 컬럼_인덱스)}{행_번호}, 값{업데이트_값}")
                            except Exception as e2:
                                print(f"❌ batch_update도 실패: {e2}")
                                raise e2
                        
                        # 업데이트 후 값 검증 (잠시 대기 후 확인)
                        time.sleep(2)  # 대기 시간을 늘림
                        업데이트_후_값 = gspread_operation_with_timeout(
                            lambda: 시트.cell(행_번호, 컬럼_인덱스).value,
                            timeout=20,
                            operation_name="업데이트 후 값 확인"
                        )
                        print(f"업데이트 후 확인 값: {업데이트_후_값}")
                        
                        # 값 비교 시 타입 변환 고려
                        예상_값_문자열 = str(업데이트_값)
                        실제_값_문자열 = str(업데이트_후_값)
                        
                        print(f"🔍 디버깅: 업데이트_값={업데이트_값} (타입: {type(업데이트_값)})")
                        print(f"🔍 디버깅: 업데이트_후_값={업데이트_후_값} (타입: {type(업데이트_후_값)})")
                        print(f"🔍 디버깅: 예상_값_문자열='{예상_값_문자열}', 실제_값_문자열='{실제_값_문자열}'")
                        print(f"🔍 디버깅: 비교 결과 = {실제_값_문자열 == 예상_값_문자열}")
                        
                        if 실제_값_문자열 == 예상_값_문자열:
                            print(f"✅ Google Sheets에서 지명 '{지명}'의 '{컬럼명}' 값을 '{업데이트_값}'으로 성공적으로 업데이트했습니다.")
                            return True
                        else:
                            print(f"❌ 업데이트 검증 실패: 예상값 '{예상_값_문자열}', 실제값 '{실제_값_문자열}'")
                            print(f"❌ 업데이트가 실제로 반영되지 않았습니다. 재시도합니다.")
                            if 시도_횟수 < 최대_재시도 - 1:
                                time.sleep(3)  # 대기 시간을 늘림
                                continue
                            return False
                    else:
                        print(f"컬럼 '{컬럼명}'을 찾을 수 없습니다.")
                        return False
            
            print(f"지명 '{지명}'을 찾을 수 없습니다.")
            return False
            
        except Exception as e:
            print(f"Google Sheets 특정 셀 업데이트 중 오류 발생 (시도 {시도_횟수 + 1}/{최대_재시도}): {e}")
            if 시도_횟수 < 최대_재시도 - 1:
                time.sleep(2)  # 2초 대기 후 재시도
                continue
            return False
    
    print(f"❌ 최대 재시도 횟수({최대_재시도})를 초과하여 업데이트에 실패했습니다.")
    return False

def 구글_시트_쓰기(스프레드시트_ID, df, 시트_이름="시트1"):
    """Google Sheets에 전체 데이터를 쓰는 함수 (전체 덮어쓰기)"""
    try:
        클라이언트 = 구글_시트_연결()
        if not 클라이언트:
            return False
            
        # 스프레드시트 열기
        스프레드시트 = gspread_operation_with_timeout(
            lambda: 클라이언트.open_by_key(스프레드시트_ID),
            timeout=20,
            operation_name="스프레드시트 열기"
        )
        시트 = gspread_operation_with_timeout(
            lambda: 스프레드시트.worksheet(시트_이름),
            timeout=20,
            operation_name=f"시트 '{시트_이름}' 가져오기"
        )
        
        # 기존 데이터 모두 삭제
        gspread_operation_with_timeout(
            lambda: 시트.clear(),
            timeout=20,
            operation_name="시트 데이터 삭제"
        )
        
        # 헤더 추가
        if not df.empty:
            헤더 = df.columns.tolist()
            gspread_operation_with_timeout(
                lambda: 시트.append_row(헤더),
                timeout=20,
                operation_name="헤더 추가"
            )
            
            # 데이터 추가
            for _, 행 in df.iterrows():
                gspread_operation_with_timeout(
                    lambda: 시트.append_row(행.tolist()),
                    timeout=20,
                    operation_name="데이터 행 추가"
                )
        
        print(f"Google Sheets에 {len(df)}개 행을 성공적으로 저장했습니다.")
        return True
        
    except Exception as e:
        print(f"Google Sheets 쓰기 중 오류 발생: {e}")
        return False

def 지명으로_행_찾기(지명, df):
    """지명을 받아서 해당하는 행을 반환하는 함수"""
    try:
        if df is not None and '지명' in df.columns:
            # 지명이 일치하는 행 찾기
            matching_rows = df[df['지명'] == 지명]
            if not matching_rows.empty:
                # 첫 번째 일치하는 행 반환 (Series 객체)
                return matching_rows.iloc[0]
        return None
    except Exception as e:
        print(f"지명으로 행 찾기 중 오류 발생: {e}")
        return None

def 하나노란으로_행_찾기(하나노란_값, df):
    """하나노란 값을 받아서 해당하는 행을 반환하는 함수"""
    try:
        if df is not None and '하나노란' in df.columns:
            # 하나노란 값이 일치하는 행 찾기
            matching_rows = df[df['하나노란'] == 하나노란_값]
            if not matching_rows.empty:
                # 첫 번째 일치하는 행 반환 (Series 객체)
                return matching_rows.iloc[0]
        return None
    except Exception as e:
        print(f"하나노란으로 행 찾기 중 오류 발생: {e}")
        return None

def 작업값_업데이트(하나노란_값, 작업관리_df):
    """하나노란 값으로 작업 값을 +1 업데이트하는 함수 (Google Sheets만)"""
    try:
        if 하나노란_값 and 하나노란_값.strip():
            # 하나노란 값으로 행 찾기
            행 = 하나노란으로_행_찾기(하나노란_값, 작업관리_df)
            if 행 is not None and '작업' in 행:
                현재_작업값 = int(행.get('작업', 0))
                새_작업값 = 현재_작업값 + 1
                행_인덱스 = 행.name
                
                print(f"작업 값 업데이트: {하나노란_값} - {현재_작업값} → {새_작업값}")
                
                # Google Sheets에서만 업데이트
                try:
                    if 구글_시트_특정_행_업데이트(작업관리_스프레드시트_ID, 하나노란_값, 행_인덱스, '작업', 새_작업값):
                        print(f"✅ Google Sheets에서 작업 값 업데이트 성공: {새_작업값}")
                        return True, 새_작업값
                    else:
                        print(f"❌ Google Sheets 작업 값 업데이트 실패")
                        return False, 0
                except Exception as e:
                    print(f"❌ Google Sheets 업데이트 중 오류: {e}")
                    return False, 0
            else:
                print(f"하나노란 값 '{하나노란_값}'에 해당하는 행을 찾을 수 없습니다.")
                return False, 0
        else:
            print("하나노란 값이 비어있어 작업 값을 업데이트할 수 없습니다.")
            return False, 0
    except Exception as e:
        print(f"작업값 업데이트 중 오류 발생: {e}")
        return False, 0

def 월작업갯수_확인(하나노란_값, 작업관리_df):
    """하나노란 값과 같은 행의 월작업개수에 도달했는지 확인하는 함수"""
    try:
        if 하나노란_값 and 하나노란_값.strip():
            # 하나노란 값으로 행 찾기
            행 = 하나노란으로_행_찾기(하나노란_값, 작업관리_df)
            if 행 is not None and '월작업개수' in 행 and '작업' in 행:
                현재_작업수 = int(행.get('작업', 0))
                월작업개수 = int(행.get('월작업개수', 0))
                print(f"하나노란 '{하나노란_값}': 현재 작업 수: {현재_작업수}, 월작업개수: {월작업개수}")
                return 현재_작업수 >= 월작업개수
            else:
                print(f"하나노란 값 '{하나노란_값}'에 해당하는 행을 찾을 수 없거나 월작업개수 컬럼이 없습니다.")
                return False
        else:
            print("하나노란 값이 비어있어 월작업갯수를 확인할 수 없습니다.")
            return False
    except Exception as e:
        print(f"월작업갯수 확인 중 오류 발생: {e}")
        return False


def 모든_인터넷_사용기록_삭제(driver):
    """모든 인터넷 사용기록을 완전히 삭제하는 함수"""
    try:
        print("\n🧹 === 모든 인터넷 사용기록 삭제 시작 ===")
        
        # 쿠키 삭제 (1차)
        print("🍪 1차 쿠키 삭제를 시작합니다...")
        driver.delete_all_cookies()
        print("✅ 1차 쿠키 삭제가 완료되었습니다.")
        time.sleep(1)
        
        # 브라우징 히스토리 삭제
        print("📜 브라우징 히스토리 삭제를 시작합니다...")
        try:
            driver.execute_script("window.history.clear();")
            print("✅ 브라우징 히스토리 삭제가 완료되었습니다.")
        except Exception as e:
            print(f"⚠️ 브라우징 히스토리 삭제 중 오류: {e}")
        time.sleep(1)
        
        # 로컬 스토리지 삭제
        print("💾 로컬 스토리지 삭제를 시작합니다...")
        try:
            driver.execute_script("localStorage.clear();")
            print("✅ 로컬 스토리지 삭제가 완료되었습니다.")
        except Exception as e:
            print(f"⚠️ 로컬 스토리지 삭제 중 오류: {e}")
        time.sleep(1)
        
        # 세션 스토리지 삭제
        print("🔐 세션 스토리지 삭제를 시작합니다...")
        try:
            driver.execute_script("sessionStorage.clear();")
            print("✅ 세션 스토리지 삭제가 완료되었습니다.")
        except Exception as e:
            print(f"⚠️ 세션 스토리지 삭제 중 오류: {e}")
        time.sleep(1)
        
        # 캐시 및 기타 데이터 삭제 (JavaScript로 가능한 범위)
        print("🗂️ 캐시 및 기타 데이터 삭제를 시작합니다...")
        try:
            # 캐시 스토리지 삭제 시도
            driver.execute_script("""
                if ('caches' in window) {
                    caches.keys().then(function(names) {
                        for (let name of names) {
                            caches.delete(name);
                        }
                    });
                }
            """)
            
            # IndexedDB 삭제 시도
            driver.execute_script("""
                if ('indexedDB' in window) {
                    try {
                        indexedDB.databases().then(databases => {
                            databases.forEach(db => {
                                indexedDB.deleteDatabase(db.name);
                            });
                        });
                    } catch(e) {
                        console.log('IndexedDB 삭제 중 오류:', e);
                    }
                }
            """)
            
            # WebSQL 삭제 시도 (구형 브라우저 지원)
            driver.execute_script("""
                if ('openDatabase' in window) {
                    try {
                        var db = openDatabase('', '', '', '');
                        db.transaction(function(tx) {
                            tx.executeSql('DELETE FROM __WebKitDatabaseInfoTable__');
                        });
                    } catch(e) {
                        console.log('WebSQL 삭제 중 오류:', e);
                    }
                }
            """)
            
            print("✅ 캐시 및 기타 데이터 삭제가 완료되었습니다.")
        except Exception as e:
            print(f"⚠️ 캐시 및 기타 데이터 삭제 중 오류: {e}")
        time.sleep(1)
        
        # 쿠키 삭제 (2차 - 최종 확인)
        print("🍪 2차 쿠키 삭제를 시작합니다...")
        driver.delete_all_cookies()
        print("✅ 2차 쿠키 삭제가 완료되었습니다.")
        time.sleep(1)
        
        print("🎉 모든 인터넷 사용기록 삭제가 완료되었습니다!")
        return True
        
    except Exception as e:
        print(f"❌ 인터넷 사용기록 삭제 중 오류 발생: {e}")
        return False

def 크롬_사용자_데이터_폴더_삭제():
    """크롬 사용자 데이터 폴더를 완전히 삭제하는 함수"""
    try:
        print("\n🗂️ === 크롬 사용자 데이터 폴더 삭제 시작 ===")
        
        # 일반적인 크롬 사용자 데이터 경로들
        크롬_데이터_경로들 = [
            os.path.expanduser("~\\AppData\\Local\\Google\\Chrome\\User Data"),
            os.path.expanduser("~\\AppData\\Roaming\\Google\\Chrome"),
            "C:\\Users\\%s\\AppData\\Local\\Google\\Chrome\\User Data" % os.getenv('USERNAME'),
            "C:\\Users\\%s\\AppData\\Roaming\\Google\\Chrome" % os.getenv('USERNAME')
        ]
        
        삭제_성공_카운트 = 0
        
        for 경로 in 크롬_데이터_경로들:
            if os.path.exists(경로):
                try:
                    print(f"📁 {경로} 폴더를 삭제합니다...")
                    
                    # 읽기 전용 속성 제거
                    for root, dirs, files in os.walk(경로):
                        for 파일 in files:
                            파일_경로 = os.path.join(root, 파일)
                            try:
                                os.chmod(파일_경로, 0o777)
                            except:
                                pass
                    
                    # 폴더 삭제
                    shutil.rmtree(경로, ignore_errors=True)
                    print(f"✅ {경로} 폴더 삭제 완료")
                    삭제_성공_카운트 += 1
                    
                except Exception as e:
                    print(f"⚠️ {경로} 폴더 삭제 중 오류: {e}")
                    
                    # 명령프롬프트를 통한 강제 삭제 시도
                    try:
                        subprocess.run(f'rmdir /s /q "{경로}"', shell=True, check=False)
                        print(f"✅ {경로} 강제 삭제 완료")
                        삭제_성공_카운트 += 1
                    except:
                        print(f"❌ {경로} 강제 삭제도 실패")
            else:
                print(f"📂 {경로} 폴더가 존재하지 않습니다.")
        
        if 삭제_성공_카운트 > 0:
            print(f"🎉 크롬 사용자 데이터 폴더 삭제 완료! ({삭제_성공_카운트}개 경로 처리)")
            return True
        else:
            print("⚠️ 삭제할 크롬 데이터 폴더를 찾지 못했습니다.")
            return False
            
    except Exception as e:
        print(f"❌ 크롬 사용자 데이터 폴더 삭제 중 오류: {e}")
        return False

def 크롬_프로세스_강제_종료():
    """모든 크롬 프로세스를 강제로 종료하는 함수"""
    try:
        print("\n🔄 === 크롬 프로세스 강제 종료 시작 ===")
        
        # Chrome 관련 프로세스들
        크롬_프로세스들 = [
            "chrome.exe",
            "chromedriver.exe", 
            "Google Chrome"
        ]
        
        종료_성공_카운트 = 0
        
        for 프로세스명 in 크롬_프로세스들:
            try:
                # taskkill 명령어로 프로세스 강제 종료
                result = subprocess.run(
                    f'taskkill /f /im "{프로세스명}" /t',
                    shell=True,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    print(f"✅ {프로세스명} 프로세스 종료 완료")
                    종료_성공_카운트 += 1
                else:
                    print(f"📝 {프로세스명} 프로세스가 실행 중이지 않음")
                    
            except Exception as e:
                print(f"⚠️ {프로세스명} 프로세스 종료 중 오류: {e}")
        
        # 잠시 대기 (프로세스 종료 완료 대기)
        time.sleep(2)
        
        print(f"✅ 모든 Chrome 프로세스를 종료했습니다. ({종료_성공_카운트}개 프로세스 처리)")
        return True
        
    except Exception as e:
        print(f"❌ 크롬 프로세스 강제 종료 중 오류: {e}")
        return False

def 모든_창_프로그램_강제_종료():
    """모든 띄워진 창과 프로그램을 강제로 종료하는 함수"""
    try:
        print("\n🔄 === 모든 창/프로그램 강제 종료 시작 ===")
        
        # 종료할 프로그램/창 목록
        종료_대상_프로세스들 = [
            # 브라우저 관련
            "chrome.exe",
            "chromedriver.exe", 
            "chrome_proxy.exe",
            "firefox.exe",
            "msedge.exe",
            "iexplore.exe",
            
            # 개발 도구
            "notepad.exe",
            "notepad++.exe",
            "code.exe",  # VS Code
            "devenv.exe",  # Visual Studio
            "pycharm64.exe",  # PyCharm
            
            # 기타 자주 사용되는 프로그램
            "excel.exe",
            "winword.exe",
            "powerpnt.exe",
            "outlook.exe",
            "teams.exe",
            "discord.exe",
            "zoom.exe",
            "skype.exe",
            
            # 시스템 도구
            "taskmgr.exe",  # 작업 관리자
            "msconfig.exe",  # 시스템 구성
            "regedit.exe",  # 레지스트리 편집기
            "cmd.exe",
            "powershell.exe",
            "wt.exe",  # Windows Terminal
        ]
        
        종료_성공_카운트 = 0
        종료_실패_목록 = []
        
        for 프로세스명 in 종료_대상_프로세스들:
            try:
                # 자기 자신 보호 (0828.exe, 포스팅.exe, python 계열)
                _보호_목록 = ("0828.exe", "포스팅.exe", "python.exe", "python3.exe", "pythonw.exe")
                if any(프로세스명.lower() == p.lower() for p in _보호_목록):
                    print(f"  {프로세스명} 제외 (자기 자신 보호)")
                    continue
                    
                # taskkill 명령어로 프로세스 강제 종료 (시스템 종료 창 방지)
                result = subprocess.run(
                    f'taskkill /f /im "{프로세스명}"',
                    shell=True,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    print(f"✅ {프로세스명} 프로세스 종료 완료")
                    종료_성공_카운트 += 1
                else:
                    # 프로세스가 실행 중이지 않음 (정상)
                    pass
                    
            except Exception as e:
                print(f"⚠️ {프로세스명} 프로세스 종료 중 오류: {e}")
                종료_실패_목록.append(프로세스명)
        
        # 추가로 모든 창 닫기 (더 강력한 방법)
        try:
            print("모든 창 닫기 시도...")
            import win32gui
            import win32con
            import win32process
            import psutil

            # explorer.exe 및 시스템 프로세스 PID 집합 (WM_CLOSE 금지)
            _시스템_프로세스명 = {
                'explorer.exe', 'dwm.exe', 'winlogon.exe', 'lsass.exe',
                'csrss.exe', 'svchost.exe', 'services.exe', 'smss.exe',
                'wininit.exe', 'taskhostw.exe', 'sihost.exe', 'ctfmon.exe',
                'shellexperiencehost.exe', 'startmenuexperiencehost.exe',
                'searchhost.exe', 'runtimebroker.exe', 'applicationframehost.exe',
            }
            _시스템_pid_set = set()
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if proc.info['name'] and proc.info['name'].lower() in _시스템_프로세스명:
                        _시스템_pid_set.add(proc.info['pid'])
                except Exception:
                    pass

            def enum_windows_callback(hwnd, windows):
                if win32gui.IsWindowVisible(hwnd):
                    window_title = win32gui.GetWindowText(hwnd)
                    if window_title:  # 제목이 있는 창만
                        windows.append((hwnd, window_title))
                return True
            
            windows = []
            win32gui.EnumWindows(enum_windows_callback, windows)
            
            닫힌_창_수 = 0
            for hwnd, title in windows:
                try:
                    # 시스템 창이나 중요한 창은 제외 (제목 기반)
                    if any(keyword in title.lower() for keyword in [
                        'desktop', 'taskbar', 'start menu', 'system tray',
                        'windows security', 'windows defender', 'antivirus'
                    ]):
                        continue
                    
                    # 0828.exe / 포스팅.exe / python 관련 창은 제외 (자기 자신 보호)
                    if any(kw in title.lower() for kw in ['0828', '포스팅', 'python']):
                        print(f"  자기 자신 보호 창 제외: {title}")
                        continue

                    # 창을 소유한 프로세스가 시스템/explorer 계열이면 제외
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        if pid in _시스템_pid_set:
                            continue
                    except Exception:
                        continue
                    
                    # 창 닫기
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    닫힌_창_수 += 1
                    print(f"창 닫기: {title}")
                    
                except Exception as e:
                    print(f"창 닫기 실패 ({title}): {e}")
            
            print(f"{닫힌_창_수}개 창을 닫았습니다.")
            
        except ImportError:
            print("win32gui 모듈이 없어 창 닫기 기능을 건너뜁니다.")
        except Exception as e:
            print(f"창 닫기 중 오류: {e}")
        
        # 잠시 대기 (프로세스 종료 완료 대기)
        time.sleep(3)
        
        print(f"🎉 모든 창/프로그램 강제 종료 완료! ({종료_성공_카운트}개 프로세스 처리)")
        if 종료_실패_목록:
            print(f"⚠️ 종료 실패한 프로세스: {', '.join(종료_실패_목록)}")
        
        return True
        
    except Exception as e:
        print(f"❌ 모든 창/프로그램 강제 종료 중 오류: {e}")
        return False

def 완전한_브라우저_데이터_삭제(driver=None):
    """브라우저와 관련된 모든 데이터를 완전히 삭제하는 함수"""
    try:
        print("\n🧹 === 완전한 브라우저 데이터 삭제 시작 ===")
        
        # 1단계: 현재 세션의 인터넷 사용기록 삭제
        if driver:
            print("1단계: 현재 세션 데이터 삭제")
            모든_인터넷_사용기록_삭제(driver)
            
            # 드라이버 종료
            try:
                driver.quit()
                print("✅ WebDriver 종료 완료")
            except:
                pass
        
        # 2단계: 모든 창/프로그램 강제 종료
        print("2단계: 모든 창/프로그램 강제 종료")
        모든_창_프로그램_강제_종료()
        
        # 3단계: 크롬 프로세스 강제 종료 (추가 보안)
        print("3단계: 크롬 프로세스 강제 종료 (추가 보안)")
        크롬_프로세스_강제_종료()
        
        # 4단계: 크롬 사용자 데이터 폴더 삭제
        print("4단계: 크롬 사용자 데이터 폴더 삭제")
        크롬_사용자_데이터_폴더_삭제()
        
        print("\n🎉 === 완전한 브라우저 데이터 삭제 완료 ===")
        print("모든 브라우징 기록, 쿠키, 캐시, 저장된 데이터가 삭제되었습니다.")
        return True
        
    except Exception as e:
        print(f"❌ 완전한 브라우저 데이터 삭제 중 오류: {e}")
        return False

# resource_path() -> 파일 상단 정의 (_앱_루트_경로 / _internal_폴더_경로)

# ================== 아이피교체 시스템 시작 ==================

# ADB 경로 설정 (사용자 환경에 맞게 수정)
ADB_PATH = r"C:\adb\adb.exe"

def adb_command(cmd: str) -> str:
    """ADB 명령어 실행 후 결과 문자열 반환"""
    result = subprocess.run([ADB_PATH] + cmd.split(), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ADB 실행 오류: {result.stderr.strip()}")
    return result.stdout.strip()

def check_device_connected():
    """USB로 연결된 안드로이드 디바이스 확인"""
    try:
        result = subprocess.run([ADB_PATH, 'devices'], capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            devices = [line for line in lines[1:] if line.strip() and 'device' in line]
            connected = len(devices) > 0
            if connected:
                print(f"✅ {len(devices)}개의 디바이스가 연결되어 있습니다.")
            else:
                print("❌ 연결된 디바이스가 없습니다.")
            return connected
        else:
            print(f"❌ ADB 연결 확인 실패: {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        print(f"❌ ADB를 찾을 수 없습니다. 경로를 확인하세요: {ADB_PATH}")
        return False
    except Exception as e:
        print(f"❌ 디바이스 확인 중 오류: {e}")
        return False

def toggle_airplane_mode_ui():
    """상태창을 내려서 (396, 588) 좌표 직접 터치로 비행기 모드 토글"""
    try:
        if not check_device_connected():
            print("연결된 디바이스가 없습니다.")
            return False
        
        print("📱 상태창을 내려서 비행기 모드 토글...")
        
        # 1. 화면 켜기
        adb_command("shell input keyevent KEYCODE_WAKEUP")
        time.sleep(1)
        
        # 2. 상태창 두 번 스와이프 (빠른 설정 패널 열기)
        print("🔽 빠른 설정 패널 열기...")
        adb_command("shell input swipe 720 0 720 1280 300")  # 화면 중앙 기준 스와이프
        time.sleep(0.5)
        adb_command("shell input swipe 720 0 720 1280 300")
        time.sleep(1)
        
        # 3. 고정 좌표로 비행기 모드 아이콘 터치 (한 칸 오른쪽으로 이동)
        airplane_x, airplane_y = 630, 588
        print(f"✈️ 비행기 모드 아이콘 터치: ({airplane_x}, {airplane_y})")
        adb_command(f"shell input tap {airplane_x} {airplane_y}")
        time.sleep(2)  # 상태 변경 대기
        
        # 4. 상태창 닫기
        print("📤 상태창 닫기...")
        adb_command("shell input keyevent KEYCODE_BACK")
        adb_command("shell input keyevent KEYCODE_BACK")
        
        print("✅ 상태창 비행기 모드 토글 완료")
        return True
        
    except Exception as e:
        print(f"❌ 상태창 비행기 모드 토글 실패: {e}")
        return False

def get_computer_ip():
    """컴퓨터의 공인 IP 주소를 가져오는 함수"""
    try:
        # requests 라이브러리로 공인 IP 확인
        import requests
        response = requests.get('https://ipinfo.io/ip', timeout=10)
        if response.status_code == 200:
            ip = response.text.strip()
            print(f"현재 컴퓨터 공인 IP: {ip}")
            return ip
    except ImportError:
        print("requests 라이브러리가 없습니다. pip install requests 실행 후 다시 시도하세요.")
        return None
    except Exception as e:
        print(f"공인 IP 확인 실패: {e}")
        return None
    
    # requests가 실패한 경우 curl 명령어 시도
    try:
        import subprocess
        result = subprocess.run(['curl', '-s', 'ipinfo.io/ip'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            ip = result.stdout.strip()
            print(f"현재 컴퓨터 공인 IP (curl): {ip}")
            return ip
    except Exception as e:
        print(f"curl 명령어 실패: {e}")
        return None
    
    return None


def _작업_허용_아이피_대기():
    """설정.xlsx 아이피교체에 IP가 지정된 경우, 현재 PC 공인 IP와 일치할 때까지 대기."""
    if not 설정_작업_허용_아이피:
        return
    allowed = str(설정_작업_허용_아이피).strip()
    while True:
        current = get_computer_ip()
        if current and current.strip() == allowed:
            print(f"[설정.xlsx] 작업 허용 IP 일치 ({current.strip()}) - 작업을 진행합니다.")
            return
        if not current:
            print(f"[설정.xlsx] 작업 허용 IP={allowed} - 현재 IP 확인 실패, 5분 후 재확인합니다.")
            중요_작업_로그_저장(f"작업 허용 IP 검사 실패 - IP 확인 불가 (허용={allowed}), 5분 후 재확인")
        else:
            print(f"[설정.xlsx] 작업 허용 IP 불일치 - 설정={allowed}, 현재={current.strip()}")
            print("설정된 IP와 동일한 컴퓨터에서만 작업할 수 있습니다. IP 일치까지 대기합니다.")
            중요_작업_로그_저장(f"작업 허용 IP 불일치 - 설정={allowed}, 현재={current.strip()}, 대기 중")
        time.sleep(300)


def save_ip_to_excel(ip_address, status, filename="ip_log.xlsx"):
    """IP 주소와 상태를 엑셀 파일에 저장 (기존 데이터에 추가)"""
    try:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 새로운 데이터
        new_data = {
            '시간': [current_time],
            'IP주소': [ip_address if ip_address else 'N/A'],
            '상태': [status]
        }
        
        # 기존 파일이 있으면 읽어서 추가
        if os.path.exists(filename):
            try:
                existing_df = pd.read_excel(filename)
                combined_df = pd.concat([existing_df, pd.DataFrame(new_data)], ignore_index=True)
            except:
                combined_df = pd.DataFrame(new_data)
        else:
            combined_df = pd.DataFrame(new_data)
        
        # 엑셀 파일로 저장
        combined_df.to_excel(filename, index=False)
        print(f"IP 정보가 {filename}에 저장되었습니다.")
        return True
        
    except Exception as e:
        print(f"엑셀 저장 중 오류: {e}")
        return False

def clear_and_save_ip_to_excel(ip_address, status, filename="ip_log.xlsx"):
    """기존 데이터 삭제하고 새로운 IP 정보만 저장"""
    try:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 새로운 데이터만 저장 (기존 데이터 삭제)
        new_data = {
            '시간': [current_time],
            'IP주소': [ip_address if ip_address else 'N/A'],
            '상태': [status]
        }
        
        df = pd.DataFrame(new_data)
        df.to_excel(filename, index=False)
        print(f"기존 데이터 삭제 후 새로운 IP 정보가 {filename}에 저장되었습니다.")
        return True
        
    except Exception as e:
        print(f"엑셀 저장 중 오류: {e}")
        return False

def check_ip_changed(filename="ip_log.xlsx"):
    """엑셀 파일에서 IP 변경 여부 확인 - 더 정확한 검증"""
    try:
        if not os.path.exists(filename):
            print(f"{filename} 파일이 존재하지 않습니다.")
            return False
        
        df = pd.read_excel(filename)
        
        if len(df) < 2:
            print("비교할 데이터가 충분하지 않습니다.")
            return False
        
        # 최신 2개 레코드 비교
        latest_ip = df.iloc[-1]['IP주소']
        previous_ip = df.iloc[-2]['IP주소']
        
        print(f"이전 IP: {previous_ip}")
        print(f"현재 IP: {latest_ip}")
        
        # IP 주소 유효성 검증
        if latest_ip == 'N/A' or previous_ip == 'N/A':
            print("❌ IP 주소가 'N/A'로 기록되어 있습니다.")
            return False
        
        if not latest_ip or not previous_ip:
            print("❌ IP 주소가 비어있습니다.")
            return False
        
        # IP 주소 형식 검증 (기본적인 형식 확인)
        import re
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        
        if not re.match(ip_pattern, str(latest_ip)) or not re.match(ip_pattern, str(previous_ip)):
            print("❌ IP 주소 형식이 올바르지 않습니다.")
            return False
        
        # IP가 변경되었는지 확인
        if latest_ip != previous_ip:
            print("✅ IP가 성공적으로 변경되었습니다!")
            print(f"   변경 전: {previous_ip}")
            print(f"   변경 후: {latest_ip}")
            return True
        else:
            return False
            
    except Exception as e:
        print(f"IP 변경 확인 중 오류: {e}")
        return False

def auto_ip_change_system():
    """자동 IP 교체 시스템 - 성공할 때까지 재시도"""
    print("\n🔄 자동 IP 교체 시스템 시작")
    
    try:
        # 1. 시작 시 IP 확인 및 엑셀 저장 (기존 데이터 삭제)
        print("📍 1단계: 시작 IP 확인 및 저장")
        initial_ip = get_computer_ip()
        if not initial_ip:
            print("❌ 시작 IP 주소를 가져올 수 없습니다.")
            return False
        clear_and_save_ip_to_excel(initial_ip, "시작")
        print(f"시작 IP: {initial_ip}")
        
        # 2. 비행기 모드 ON
        print("\n📍 2단계: 비행기 모드 켜기")
        airplane_on_attempts = 0
        while not toggle_airplane_mode_ui() and airplane_on_attempts < 3:
            airplane_on_attempts += 1
            print(f"⚠️ 비행기 모드 켜기 {airplane_on_attempts}번째 시도 실패, 5초 후 재시도...")
            time.sleep(5)
        
        if airplane_on_attempts >= 3:
            print("❌ 비행기 모드 켜기 최대 시도 횟수 도달")
            return False
        
        print("✅ 비행기 모드 켜기 성공")
        
        # 3. 15초 대기 (비행기 모드 완전 적용 대기)
        print("\n📍 3단계: 15초 대기 중... (비행기 모드 완전 적용)")
        for i in range(15, 0, -5):
            print(f"   {i}초 남음...")
            time.sleep(5)
        
        # 4. 비행기 모드 OFF
        print("\n📍 4단계: 비행기 모드 끄기")
        airplane_off_attempts = 0
        while not toggle_airplane_mode_ui() and airplane_off_attempts < 3:
            airplane_off_attempts += 1
            print(f"⚠️ 비행기 모드 끄기 {airplane_off_attempts}번째 시도 실패, 5초 후 재시도...")
            time.sleep(5)
        
        if airplane_off_attempts >= 3:
            print("❌ 비행기 모드 끄기 최대 시도 횟수 도달")
            return False
        
        print("✅ 비행기 모드 끄기 성공")
        
        # 5. 60초 대기 (네트워크 재연결 및 IP 할당 대기)
        print("\n📍 5단계: 60초 대기 중... (네트워크 재연결 및 IP 할당)")
        for i in range(60, 0, -10):
            print(f"   {i}초 남음...")
            time.sleep(10)
        
        # 6. IP 확인 및 엑셀 저장
        print("\n📍 6단계: 변경 후 IP 확인")
        final_ip = get_computer_ip()
        if not final_ip:
            print("❌ 변경 후 IP 주소를 가져올 수 없습니다.")
            return False
        save_ip_to_excel(final_ip, "완료")
        print(f"시작 IP: {final_ip}")
        
        # 7. IP 변경 여부 확인
        print("\n📍 7단계: IP 변경 여부 확인")
        if check_ip_changed():
            print("🎉 IP 교체 성공!")
            return True
        else:
            print("🔄 IP가 변경되지 않았습니다.")
            return False
            
    except Exception as e:
        print(f"❌ 자동 IP 교체 중 오류 발생: {e}")
        return False

# ================== 아이피교체 시스템 끝 ==================

# ================== 웹페이지 로딩 대기 시스템 시작 ==================
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

def 페이지_로딩_완료_대기(driver, timeout=10):
    """페이지가 완전히 로딩될 때까지 대기하는 함수"""
    try:
        wait = WebDriverWait(driver, timeout)
        # 페이지 로딩 완료 대기
        wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
        print("✅ 페이지 로딩이 완료되었습니다.")
        return True
    except Exception as e:
        print(f"⚠️ 페이지 로딩 대기 중 오류: {e}")
        return False

def 특정_요소_대기(driver, by, value, timeout=10):
    """특정 요소가 나타날 때까지 대기하는 함수"""
    try:
        wait = WebDriverWait(driver, timeout)
        element = wait.until(EC.presence_of_element_located((by, value)))
        print(f"✅ 요소를 찾았습니다: {value}")
        return element
    except Exception as e:
        print(f"⚠️ 요소 '{value}' 대기 중 오류: {e}")
        return None

def 요소_클릭_가능_대기(driver, by, value, timeout=10):
    """특정 요소가 클릭 가능할 때까지 대기하는 함수"""
    try:
        wait = WebDriverWait(driver, timeout)
        element = wait.until(EC.element_to_be_clickable((by, value)))
        print(f"✅ 요소가 클릭 가능합니다: {value}")
        return element
    except Exception as e:
        print(f"⚠️ 요소 '{value}' 클릭 가능 대기 중 오류: {e}")
        return None

def 요소_보임_대기(driver, by, value, timeout=10):
    """특정 요소가 화면에 보일 때까지 대기하는 함수"""
    try:
        wait = WebDriverWait(driver, timeout)
        element = wait.until(EC.visibility_of_element_located((by, value)))
        print(f"✅ 요소가 화면에 보입니다: {value}")
        return element
    except Exception as e:
        print(f"⚠️ 요소 '{value}' 보임 대기 중 오류: {e}")
        return None

def 페이지_제목_포함_대기(driver, title_text, timeout=10):
    """페이지 제목에 특정 텍스트가 포함될 때까지 대기하는 함수"""
    try:
        wait = WebDriverWait(driver, timeout)
        wait.until(EC.title_contains(title_text))
        print(f"✅ 페이지 제목에 '{title_text}'가 포함되었습니다.")
        return True
    except Exception as e:
        print(f"⚠️ 페이지 제목 '{title_text}' 대기 중 오류: {e}")
        return False

def URL_변경_대기(driver, expected_url, timeout=10):
    """URL이 특정 주소로 변경될 때까지 대기하는 함수"""
    try:
        wait = WebDriverWait(driver, timeout)
        wait.until(EC.url_contains(expected_url))
        print(f"✅ URL이 '{expected_url}'를 포함하도록 변경되었습니다.")
        return True
    except Exception as e:
        print(f"⚠️ URL '{expected_url}' 변경 대기 중 오류: {e}")
        return False

def 안전한_요소_클릭(driver, by, value, timeout=10):
    """요소가 클릭 가능해질 때까지 기다린 후 안전하게 클릭하는 함수"""
    try:
        element = 요소_클릭_가능_대기(driver, by, value, timeout)
        if element:
            element.click()
            print(f"✅ 요소를 성공적으로 클릭했습니다: {value}")
            return True
        else:
            print(f"❌ 요소를 찾을 수 없어 클릭하지 못했습니다: {value}")
            return False
    except Exception as e:
        print(f"❌ 요소 '{value}' 클릭 중 오류: {e}")
        return False

def 안전한_텍스트_입력(driver, by, value, text, timeout=10):
    """요소가 나타날 때까지 기다린 후 안전하게 텍스트를 입력하는 함수"""
    try:
        element = 특정_요소_대기(driver, by, value, timeout)
        if element:
            element.clear()  # 기존 텍스트 삭제
            element.send_keys(text)
            print(f"✅ 텍스트를 성공적으로 입력했습니다: '{text}' -> {value}")
            return True
        else:
            print(f"❌ 요소를 찾을 수 없어 텍스트를 입력하지 못했습니다: {value}")
            return False
    except Exception as e:
        print(f"❌ 요소 '{value}'에 텍스트 입력 중 오류: {e}")
        return False

def Ajax_완료_대기(driver, timeout=10):
    """jQuery Ajax 요청이 완료될 때까지 대기하는 함수"""
    try:
        wait = WebDriverWait(driver, timeout)
        wait.until(lambda driver: driver.execute_script("return typeof jQuery !== 'undefined' && jQuery.active == 0"))
        print("✅ Ajax 요청이 완료되었습니다.")
        return True
    except Exception as e:
        print(f"⚠️ Ajax 완료 대기 중 오류: {e}")
        return False

# ================== 웹페이지 로딩 대기 시스템 끝 ==================

def 구글스프레드시트_계정정보_가져오기():
    """구글 스프레드시트에서 계정 정보를 가져오는 함수"""
    import socket
    import time
    
    # 1. 파일 존재 여부 확인
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(키_파일_경로):
        print(f"오류: {키_파일_경로} 파일을 찾을 수 없습니다.")
        print("구글 스프레드시트 API 인증을 위한 서비스 계정 키 파일이 필요합니다.")
        return pd.DataFrame()
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 2. 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 3. 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                # 5. 진행상황 출력
                if 시도_횟수 > 0:
                    print(f"구글 스프레드시트 계정정보 가져오기 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 인증 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
                gc = gspread_authorize_with_timeout(creds)
                
                # 스프레드시트 열기 (URL에서 ID 추출)
                spreadsheet_id = '1JioOQCAlWxCpQnsr43UcQt9gWvCGDeFYlwlmT-m8B6s'
                spreadsheet = gspread_operation_with_timeout(
                    lambda: gc.open_by_key(spreadsheet_id),
                    timeout=20,
                    operation_name="스프레드시트 열기"
                )
                
                # 첫 번째 워크시트 선택
                worksheet = gspread_operation_with_timeout(
                    lambda: spreadsheet.get_worksheet(0),
                    timeout=20,
                    operation_name="워크시트 가져오기"
                )
                
                # 모든 데이터 가져오기
                all_values = gspread_operation_with_timeout(
                    lambda: worksheet.get_all_values(),
                    timeout=30,
                    operation_name="모든 데이터 가져오기"
                )
                
                if len(all_values) < 2:  # 헤더만 있거나 데이터가 없는 경우
                    print("구글 스프레드시트에 데이터가 없습니다.")
                    return pd.DataFrame()
                
                # 헤더와 데이터 분리
                headers = all_values[0]
                data = all_values[1:]
                
                # 데이터프레임 생성
                df = pd.DataFrame(data, columns=headers)
                
                # 필요한 컬럼이 있는지 확인하고 기본값 설정
                required_columns = ['아이디', '비번', '홍보문구', '하나노란']
                for col in required_columns:
                    if col not in df.columns:
                        print(f"경고: '{col}' 컬럼이 구글 스프레드시트에 없습니다.")
                        df[col] = ''
                
                # 하루최대포스팅수 컬럼이 없으면 기본값 3으로 설정
                if '하루최대포스팅수' not in df.columns:
                    df['하루최대포스팅수'] = 3
                    print("'하루최대포스팅수' 컬럼이 없어 기본값 3으로 설정했습니다.")
                
                # 포스팅수 컬럼이 없으면 기본값 0으로 설정
                if '포스팅수' not in df.columns:
                    df['포스팅수'] = 0
                    print("'포스팅수' 컬럼이 없어 기본값 0으로 설정했습니다.")
                
                if 시도_횟수 > 0:
                    print(f"구글 스프레드시트 계정정보 가져오기 성공! (시도 {시도_횟수 + 1}회)")
                
                print(f"구글 스프레드시트에서 {len(df)}개의 계정 정보를 가져왔습니다.")
                return df
                
            except (socket.timeout, TimeoutError) as timeout_error:
                # 4. socket.timeout 또는 TimeoutError 예외 발생 시 30초 대기 후 재시도
                print(f"연결 타임아웃 발생 (시도 {시도_횟수 + 1}/10). 30초 대기 후 재시도합니다...")
                if 시도_횟수 < 9:
                    time.sleep(30)
                    
            except Exception as e:
                print(f"구글 스프레드시트 계정정보 가져오기 중 오류 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:
                    time.sleep(5)
        
        print("구글 스프레드시트 계정정보 가져오기 실패: 최대 재시도 횟수(10회)에 도달했습니다.")
        return pd.DataFrame()
        
    finally:
        # 6. 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def 구글스프레드시트_로그인시간_확인(아이디):
    """로그인 간격 확인 (비활성화 - 항상 로그인 허용). 마지막로그인시간 기록은 업데이트 함수 사용."""
    return True

def 구글스프레드시트_로그인시간_업데이트(아이디):
    """구글 스프레드시트에서 특정 아이디의 마지막 로그인 시간을 업데이트하는 함수"""
    import socket
    import time
    
    # 1. 파일 존재 여부 확인
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(키_파일_경로):
        print(f"오류: {키_파일_경로} 파일을 찾을 수 없습니다.")
        return False
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 2. 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 3. 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                # 5. 진행상황 출력
                if 시도_횟수 > 0:
                    print(f"구글 스프레드시트 로그인시간 업데이트 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 인증 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
                gc = gspread_authorize_with_timeout(creds)
                
                # 계정정보 스프레드시트 열기
                spreadsheet_id = '1JioOQCAlWxCpQnsr43UcQt9gWvCGDeFYlwlmT-m8B6s'
                spreadsheet = gspread_operation_with_timeout(
                    lambda: gc.open_by_key(spreadsheet_id),
                    timeout=20,
                    operation_name="스프레드시트 열기"
                )
                
                # 첫 번째 워크시트 선택
                worksheet = gspread_operation_with_timeout(
                    lambda: spreadsheet.get_worksheet(0),
                    timeout=20,
                    operation_name="워크시트 가져오기"
                )
                
                # 모든 데이터 가져오기
                all_values = gspread_operation_with_timeout(
                    lambda: worksheet.get_all_values(),
                    timeout=30,
                    operation_name="모든 데이터 가져오기"
                )
                
                if len(all_values) < 2:
                    print("계정정보 구글 스프레드시트에 데이터가 없습니다.")
                    return False
                
                # 헤더와 데이터 분리
                headers = all_values[0]
                data = all_values[1:]
                
                # 아이디 컬럼 인덱스 찾기
                if '아이디' not in headers:
                    print("계정정보 구글 스프레드시트에 '아이디' 컬럼이 없습니다.")
                    return False
                
                아이디_컬럼_인덱스 = headers.index('아이디')
                
                # 로그인간격_분과 마지막로그인시간 컬럼 확인 및 추가
                if '로그인간격_분' not in headers:
                    # 헤더에 로그인간격_분 컬럼 추가
                    gspread_operation_with_timeout(
                        lambda: worksheet.update_cell(1, len(headers) + 1, '로그인간격_분'),
                        timeout=20,
                        operation_name="로그인간격_분 컬럼 추가"
                    )
                    로그인간격_컬럼_인덱스 = len(headers)
                    # 모든 데이터 행에 기본값 30 추가
                    for row_idx in range(2, len(all_values) + 1):
                        gspread_operation_with_timeout(
                            lambda: worksheet.update_cell(row_idx, 로그인간격_컬럼_인덱스 + 1, 30),
                            timeout=20,
                            operation_name="로그인간격_분 값 업데이트"
                        )
                else:
                    로그인간격_컬럼_인덱스 = headers.index('로그인간격_분')
                
                if '마지막로그인시간' not in headers:
                    # 헤더에 마지막로그인시간 컬럼 추가
                    gspread_operation_with_timeout(
                        lambda: worksheet.update_cell(1, len(headers) + 1, '마지막로그인시간'),
                        timeout=20,
                        operation_name="마지막로그인시간 컬럼 추가"
                    )
                    마지막로그인시간_컬럼_인덱스 = len(headers)
                else:
                    마지막로그인시간_컬럼_인덱스 = headers.index('마지막로그인시간')
                
                # 해당 아이디 찾기
                for row_idx, row_data in enumerate(data, start=2):  # 2부터 시작 (헤더 다음 행)
                    if row_data[아이디_컬럼_인덱스] == 아이디:
                        # 현재 시간으로 마지막 로그인 시간 업데이트 (문자열로 변환하여 저장)
                        현재_시간 = datetime.datetime.now()
                        현재_시간_문자열 = 현재_시간.strftime('%Y-%m-%d %H:%M:%S')
                        gspread_operation_with_timeout(
                            lambda: worksheet.update_cell(row_idx, 마지막로그인시간_컬럼_인덱스 + 1, 현재_시간_문자열),
                            timeout=20,
                            operation_name="마지막로그인시간 값 업데이트"
                        )
                        
                        if 시도_횟수 > 0:
                            print(f"구글 스프레드시트 로그인시간 업데이트 성공! (시도 {시도_횟수 + 1}회)")
                        
                        print(f"아이디 '{아이디}'의 마지막 로그인 시간이 업데이트되었습니다.")
                        return True
                
                print(f"아이디 '{아이디}'를 계정정보 구글 스프레드시트에서 찾을 수 없습니다.")
                return False
                
            except (socket.timeout, TimeoutError):
                # 4. socket.timeout 예외 발생 시 30초 대기 후 재시도
                print(f"연결 타임아웃 발생 (시도 {시도_횟수 + 1}/10). 30초 대기 후 재시도합니다...")
                if 시도_횟수 < 9:
                    time.sleep(30)
                    
            except Exception as e:
                print(f"구글 스프레드시트 로그인시간 업데이트 중 오류 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:
                    time.sleep(5)
        
        print("구글 스프레드시트 로그인시간 업데이트 실패: 최대 재시도 횟수(10회)에 도달했습니다.")
        return False
        
    finally:
        # 6. 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def _로그인금지시간대_허용(아이디, df, at_time=None, verbose=False):
    """지정 시각(at_time, 기본 now)에 로그인 금지 구간이 아니면 True"""
    try:
        at_time = at_time or datetime.datetime.now()
        아이디_정보 = df[df['아이디'] == 아이디]
        if len(아이디_정보) == 0:
            return True
        if '로그인금지시간대' not in df.columns:
            return True
        금지시간대_값 = str(아이디_정보.iloc[0]['로그인금지시간대']).strip()
        if not 금지시간대_값 or 금지시간대_값.lower() in ['', 'nan', 'none', '없음']:
            return True

        현재_시 = at_time.hour
        현재_분 = at_time.minute
        현재_시간_분 = 현재_시 * 60 + 현재_분
        현재_요일 = at_time.weekday()

        if '업무시간' in 금지시간대_값.lower():
            if 현재_요일 < 5:
                if 8 * 60 <= 현재_시간_분 < 18 * 60:
                    if verbose:
                        요일명 = ['월요일', '화요일', '수요일', '목요일', '금요일'][현재_요일]
                        print(
                            f"아이디 '{아이디}'는 평일 업무시간({요일명} 8:00-18:00)에 "
                            f"로그인이 금지되어 있습니다."
                        )
                        print(f"현재 시간: {at_time.strftime('%H:%M')}, 로그인 불가능")
                    return False
            if verbose:
                print(f"아이디 '{아이디}'는 현재 시간({at_time.strftime('%H:%M')})에 로그인 가능합니다.")
            return True

        for 시간대 in 금지시간대_값.split(','):
            시간대 = 시간대.strip()
            if '-' not in 시간대:
                continue
            try:
                시작_시간, 종료_시간 = 시간대.split('-', 1)
                시작_시간 = 시작_시간.strip()
                종료_시간 = 종료_시간.strip()
                if ':' in 시작_시간:
                    시작_시, 시작_분 = map(int, 시작_시간.split(':'))
                else:
                    시작_시, 시작_분 = int(시작_시간), 0
                if ':' in 종료_시간:
                    종료_시, 종료_분 = map(int, 종료_시간.split(':'))
                else:
                    종료_시, 종료_분 = int(종료_시간), 0
                시작_시간_분 = 시작_시 * 60 + 시작_분
                종료_시간_분 = 종료_시 * 60 + 종료_분
                금지 = False
                if 종료_시간_분 < 시작_시간_분:
                    if 현재_시간_분 >= 시작_시간_분 or 현재_시간_분 < 종료_시간_분:
                        금지 = True
                elif 시작_시간_분 <= 현재_시간_분 < 종료_시간_분:
                    금지 = True
                if 금지:
                    if verbose:
                        print(f"아이디 '{아이디}'는 금지시간대({시간대})에 로그인이 금지되어 있습니다.")
                        print(f"현재 시간: {at_time.strftime('%H:%M')}, 로그인 불가능")
                    return False
            except Exception as e:
                if verbose:
                    print(f"시간대 파싱 오류 '{시간대}': {e}")
                continue

        if verbose:
            print(f"아이디 '{아이디}'는 현재 시간({at_time.strftime('%H:%M')})에 로그인 가능합니다.")
        return True
    except Exception as e:
        if verbose:
            print(f"로그인금지시간대 확인 중 오류 발생: {e}")
        return True


def 로그인금지시간대_확인(아이디, df):
    """특정 아이디의 로그인금지시간대를 확인하여 현재 시간에 로그인 가능한지 판단하는 함수"""
    return _로그인금지시간대_허용(아이디, df, datetime.datetime.now(), verbose=True)

def 다음_스크립트_실행(스크립트명):
    """다음 스크립트를 실행하는 함수"""
    try:
        # 현재 스크립트 디렉토리의 절대 경로
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = resource_path(스크립트명)
        
        if os.path.exists(script_path):
            print(f"{스크립트명} 파일을 찾았습니다. 실행을 시작합니다...")
            # 작업 디렉토리를 현재 스크립트 디렉토리로 변경
            subprocess.run([sys.executable, script_path], 
                         cwd=current_dir, 
                         check=True)
            print(f"{스크립트명} 실행이 완료되었습니다!")
        else:
            print(f"오류: {스크립트명} 파일을 찾을 수 없습니다.")
            print(f"찾은 경로: {script_path}")
            print(f"현재 디렉토리: {current_dir}")
            print(f"디렉토리 내용: {os.listdir(current_dir)}")
            
    except subprocess.CalledProcessError as e:
        print(f"{스크립트명} 실행 중 오류 발생: {e}")
    except Exception as e:
        print(f"{스크립트명} 실행 중 예상치 못한 오류: {e}")

# 타임아웃이 있는 입력 함수
def input_with_timeout(prompt, timeout=30, default_value="1"):
    """타임아웃이 있는 입력 함수. 시간 내 응답이 없으면 기본값 반환"""
    import sys
    import queue
    
    print(f"{prompt} (30초 내 응답 없으면 자동으로 '{default_value}' 선택)")
    sys.stdout.flush()
    
    입력_큐 = queue.Queue()
    입력_완료 = threading.Event()
    
    def 입력_받기():
        try:
            result = input()
            입력_큐.put(result)
            입력_완료.set()
        except:
            입력_완료.set()
    
    입력_스레드 = threading.Thread(target=입력_받기, daemon=True)
    입력_스레드.start()
    
    # 타임아웃까지 대기
    입력_완료.wait(timeout=timeout)
    
    if not 입력_큐.empty():
        return 입력_큐.get().strip() or default_value
    else:
        print(f"\n⏰ 30초가 지나 자동으로 '{default_value}'를 선택합니다.")
        return default_value

def 자정까지_대기():
    """모든 업체/아이디가 오늘 한도를 채웠을 때 자정(00:00)까지 대기하는 함수"""
    import datetime
    지금 = datetime.datetime.now()
    자정 = (지금 + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=30, microsecond=0
    )
    남은초 = (자정 - 지금).total_seconds()
    남은분 = int(남은초 / 60)
    남은시 = 남은분 // 60
    남은분_나머지 = 남은분 % 60
    print(f"\n모든 업체/아이디가 오늘 작업을 완료했습니다.")
    print(f"자정까지 {남은시}시간 {남은분_나머지}분 대기합니다... (재개 예정: {자정.strftime('%Y-%m-%d %H:%M:%S')})")
    중요_작업_로그_저장(f"하루 작업 한도 완료 - 자정까지 {남은시}시간 {남은분_나머지}분 대기")
    time.sleep(남은초)
    print("자정이 지났습니다. 작업을 재개합니다.")
    중요_작업_로그_저장("자정 대기 완료 - 작업 재개")


def 월작업_완료_업체_목록_가져오기():
    """작업관리 스프레드시트에서 이번 달 월작업개수를 달성한 하나노란 목록을 반환하는 함수"""
    try:
        작업관리_df = 구글_시트_읽기(작업관리_스프레드시트_ID)
        if 작업관리_df is None or 작업관리_df.empty:
            print("작업관리 스프레드시트 읽기 실패 또는 비어있음 - 필터링 건너뜀")
            return []
        완료된_목록 = []
        if '하나노란' in 작업관리_df.columns and '작업' in 작업관리_df.columns and '월작업개수' in 작업관리_df.columns:
            for _, 행 in 작업관리_df.iterrows():
                try:
                    현재_작업수 = int(float(행.get('작업', 0) or 0))
                    월작업개수 = int(float(행.get('월작업개수', 0) or 0))
                    하나노란값 = str(행.get('하나노란', '')).strip()
                    if 월작업개수 > 0 and 현재_작업수 >= 월작업개수 and 하나노란값 and 하나노란값 != 'nan':
                        완료된_목록.append(하나노란값)
                        print(f"  월작업 완료: 하나노란={하나노란값} ({현재_작업수}/{월작업개수})")
                except Exception as _e:
                    pass
        print(f"월작업 완료 업체 수: {len(완료된_목록)}개")
        return 완료된_목록
    except Exception as e:
        print(f"월작업 완료 업체 목록 가져오기 오류: {e}")
        return []


# 재시작 시 타임스탬프 업데이트 함수
def 재시작_타임스탬프_업데이트():
    """프로그램 재시작 시 설정 파일의 타임스탬프를 현재 시간으로 업데이트"""
    설정_파일_경로 = resource_path('겹치는상호제거설정.txt')
    if os.path.exists(설정_파일_경로):
        try:
            with open(설정_파일_경로, 'r', encoding='utf-8') as f:
                파일_내용 = f.read().strip()
                if '|' in 파일_내용:
                    저장된_설정, _ = 파일_내용.split('|', 1)
                    현재_시간 = time.time()
                    with open(설정_파일_경로, 'w', encoding='utf-8') as f:
                        f.write(f"{저장된_설정}|{현재_시간}")
        except Exception as e:
            pass  # 오류 발생 시 무시


def 프로그램_같은_터미널_재시작(이유="", 타임스탬프_업데이트=True):
    """현재 터미널에서 포스팅.py를 처음부터 다시 실행 (새 콘솔 창 없음)"""
    if 이유:
        print(f"같은 터미널에서 프로그램을 재시작합니다: {이유}")
        중요_작업_로그_저장(f"프로그램 재시작 (같은 터미널): {이유}")
    if 타임스탬프_업데이트:
        재시작_타임스탬프_업데이트()
    script = os.path.abspath(__file__)
    args = [sys.executable, script] + sys.argv[1:]
    os.execv(sys.executable, args)


# 겹치는 상호 제거 기능 ON/OFF - 설정.xlsx 값 적용 (질문 없이 자동 적용)
겹치는_개수 = 0
if 설정_상호제거기능 == 1:
    겹치는_상호_제거_사용 = True
    print("겹치는 상호 제거 기능: 사용 (ON) - 설정.xlsx 적용")
else:
    겹치는_상호_제거_사용 = False
    print("겹치는 상호 제거 기능: 사용 안함 (OFF) - 설정.xlsx 적용")

def 포스팅작업요청_스프레드시트_값_확인():
    """포스팅 작업요청 스프레드시트에 작업 가능한 행이 있는지 확인
    - 지명키워드, 주제, 하나노란, 사용아이디 모두에 값이 있어야 함
    - 사용아이디가 현재 로그인 가능한 상태여야 함
    """
    try:
        print("\n=== 포스팅 작업요청 스프레드시트 확인 ===")
        df = 구글_시트_읽기(포스팅작업요청_스프레드시트_ID)
        
        if df is None or df.empty:
            print("포스팅 작업요청 스프레드시트가 비어있거나 읽을 수 없습니다.")
            return False
        
        print(f"스프레드시트 읽기 성공. 행 수: {len(df)}, 컬럼: {df.columns.tolist()}")
        
        # 필수 컬럼 확인: 지명키워드, 주제, 하나노란, 사용아이디
        필수_컬럼_목록 = ['지명키워드', '주제', '하나노란', '사용아이디']
        누락된_컬럼 = []
        for 컬럼명 in 필수_컬럼_목록:
            if 컬럼명 not in df.columns:
                누락된_컬럼.append(컬럼명)
        
        if 누락된_컬럼:
            print(f"경고: 필수 컬럼이 스프레드시트에 없습니다: {누락된_컬럼}")
            print(f"컬럼 목록: {df.columns.tolist()}")
            return False
        
        # 계정정보 스프레드시트 미리 가져오기
        print("계정정보 스프레드시트에서 계정 정보 가져오기...")
        id_df = 구글스프레드시트_계정정보_가져오기()
        if id_df.empty:
            print("계정정보 스프레드시트에서 계정 정보를 가져올 수 없습니다.")
            return False
        
        # 필수 컬럼 추가
        if '로그인간격_분' not in id_df.columns:
            id_df['로그인간격_분'] = 30
        if '마지막로그인시간' not in id_df.columns:
            id_df['마지막로그인시간'] = ''
        
        # 모든 행 확인
        for idx in range(len(df)):
            행 = df.iloc[idx]
            
            # 1. 필수 컬럼에 값이 있는지 확인
            지명키워드 = str(행['지명키워드']).strip() if '지명키워드' in df.columns else ''
            주제 = str(행['주제']).strip() if '주제' in df.columns else ''
            하나노란 = str(행['하나노란']).strip() if '하나노란' in df.columns else ''
            사용아이디 = str(행['사용아이디']).strip() if '사용아이디' in df.columns else ''
            
            # NaN 체크 및 빈 문자열 체크
            if pd.isna(행['지명키워드']) or 지명키워드.lower() == 'nan' or 지명키워드 == '':
                continue
            if pd.isna(행['주제']) or 주제.lower() == 'nan' or 주제 == '':
                continue
            if pd.isna(행['하나노란']) or 하나노란.lower() == 'nan' or 하나노란 == '':
                continue
            if pd.isna(행['사용아이디']) or 사용아이디.lower() == 'nan' or 사용아이디 == '':
                continue
            
            # 2. 사용아이디가 계정정보 스프레드시트에 등록되어 있는지 확인
            사용아이디_목록 = str(사용아이디).split(",")
            사용아이디_목록 = [아이디.strip() for 아이디 in 사용아이디_목록 if 아이디.strip()]
            
            로그인_가능한_아이디_있음 = False
            
            for 아이디 in 사용아이디_목록:
                if 아이디 not in id_df['아이디'].values:
                    print(f"  → 행 {idx + 2}: 사용아이디 '{아이디}'가 계정정보 스프레드시트에 등록되어 있지 않습니다.")
                    continue
                
                # 로그인금지시간대 확인
                if not 로그인금지시간대_확인(아이디, id_df):
                    print(f"  → 행 {idx + 2}: 사용아이디 '{아이디}'는 로그인금지시간대입니다.")
                    continue
                
                아이디_정보 = id_df[id_df['아이디'] == 아이디].iloc[0]
                로그인_가능 = True
                
                # 하루최대포스팅수 확인 (계정정보 스프레드시트에서 직접 확인)
                if 로그인_가능:
                    try:
                        # 계정정보 스프레드시트에서 하루최대포스팅수와 포스팅수 확인
                        하루_최대_포스팅수 = None
                        포스팅수 = None
                        
                        # 하루최대포스팅수 확인
                        if '하루최대포스팅수' in 아이디_정보:
                            하루_최대_포스팅수 = 아이디_정보['하루최대포스팅수']
                            if pd.isna(하루_최대_포스팅수):
                                하루_최대_포스팅수 = 3  # 기본값
                            else:
                                try:
                                    하루_최대_포스팅수 = int(float(하루_최대_포스팅수))
                                except (ValueError, TypeError):
                                    하루_최대_포스팅수 = 3  # 기본값
                        else:
                            하루_최대_포스팅수 = 3  # 기본값
                        
                        # 포스팅수 확인
                        if '포스팅수' in 아이디_정보:
                            포스팅수 = 아이디_정보['포스팅수']
                            if pd.isna(포스팅수):
                                포스팅수 = 0  # 기본값
                            else:
                                try:
                                    포스팅수 = int(float(포스팅수))
                                except (ValueError, TypeError):
                                    포스팅수 = 0  # 기본값
                        else:
                            포스팅수 = 0  # 기본값
                        
                        # 하루최대포스팅수에 도달했으면 제외
                        if 포스팅수 >= 하루_최대_포스팅수:
                            로그인_가능 = False
                            print(f"  → 행 {idx + 2}: 사용아이디 '{아이디}'는 하루최대포스팅수({하루_최대_포스팅수})에 도달했습니다. (현재 포스팅수: {포스팅수})")
                    except Exception as e:
                        print(f"  → 행 {idx + 2}: 사용아이디 '{아이디}'의 하루최대포스팅수 확인 중 오류: {e}")
                        # 오류 발생 시에도 계속 진행 (기본값으로 처리)
                        pass
                
                if 로그인_가능:
                    로그인_가능한_아이디_있음 = True
                    break
            
            # 모든 조건을 만족하는 행이 있으면 True 반환
            if 로그인_가능한_아이디_있음:
                print(f"포스팅 작업요청 스프레드시트에 작업 가능한 행이 있습니다. (데이터 행 인덱스 {idx}, 스프레드시트 행 {idx + 2})")
                print(f"  지명키워드: '{지명키워드}'")
                print(f"  주제: '{주제}'")
                print(f"  하나노란: '{하나노란}'")
                print(f"  사용아이디: '{사용아이디}'")
                return True
        
        print("포스팅 작업요청 스프레드시트에 작업 가능한 행이 없습니다.")
        print("(지명키워드, 주제, 하나노란, 사용아이디 모두에 값이 있고, 사용아이디가 로그인 가능한 행이 없습니다)")
        print("→ 원래 경로(지명업체키워드 스프레드시트)로 진행합니다.")
        # 디버깅을 위해 처음 몇 행 출력
        if len(df) > 0:
            print(f"첫 5행 데이터 (디버깅용):")
            print(df.head().to_string())
        return False  # False 반환하여 원래 경로로 진행
        
    except Exception as e:
        print(f"포스팅 작업요청 스프레드시트 확인 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False

def 엑셀_상호_비교(순위_파일):
    """구글 스프레드시트의 계정정보와 뷰순위.xlsx를 비교하는 함수"""
    try:
        # 구글 스프레드시트에서 계정정보 가져오기
        id_df = 구글스프레드시트_계정정보_가져오기()
        if id_df.empty:
            print("구글 스프레드시트에서 계정정보를 가져올 수 없습니다.")
            return 0
        
        # 뷰순위.xlsx 파일 읽기
        rank_df = pd.read_excel(순위_파일)
        
        # 상호 항목 추출
        id_titles = set(id_df['상호'].astype(str).str.strip())
        rank_titles = set(rank_df['상호'].astype(str).str.strip())
        
        # 교집합 개수
        겹치는_상호 = id_titles & rank_titles
        print(f"겹치는 상호 개수: {len(겹치는_상호)}")
        print(f"겹치는 상호 목록: {list(겹치는_상호)}")
        
        return len(겹치는_상호)
        
    except Exception as e:
        print(f"상호 비교 중 오류 발생: {e}")
        return 0

def 사용아이디로_계정_필터링(사용아이디_값, 계정정보_df):
    """지명키워드.xlsx에서 가져온 사용아이디 값으로 계정 필터링"""
    try:
        # 사용아이디 값이 비어있는지 확인
        if not 사용아이디_값 or not 사용아이디_값.strip():
            print("사용아이디 값이 비어있어 전체 계정을 반환합니다.")
            return 계정정보_df
        
        # 쉼표로 구분된 아이디들 분리
        사용아이디_목록 = str(사용아이디_값).split(",")
        사용아이디_목록 = [아이디.strip() for 아이디 in 사용아이디_목록 if 아이디.strip()]
        
        print(f"지명키워드에서 가져온 사용아이디 목록: {사용아이디_목록}")
        
        # 해당 아이디들과 일치하는 계정만 필터링
        필터링된_계정 = 계정정보_df[계정정보_df["아이디"].isin(사용아이디_목록)]
        
        print(f"필터링된 계정 수: {len(필터링된_계정)}개")
        return 필터링된_계정
        
    except Exception as e:
        print(f"사용아이디로 계정 필터링 실패: {e}")
        return 계정정보_df  # 필터링 실패 시 전체 반환

def 포스팅작업요청_처리():
    """포스팅 작업요청 경로로 처리 (지명키워드.xlsx, 작업아이디.xlsx 생성)"""
    global 겹치는_상호_제거_사용, 겹치는_개수
    
    try:
        print("\n=== 포스팅 작업요청 경로 시작 ===")

        _작업_허용_아이피_대기()
        
        # 1. 포스팅 작업요청 스프레드시트에서 데이터 읽기
        print("1단계: 포스팅 작업요청 스프레드시트에서 데이터 읽기")
        df = 구글_시트_읽기(포스팅작업요청_스프레드시트_ID)
        
        if df is None or df.empty:
            print("포스팅 작업요청 스프레드시트 데이터를 읽을 수 없습니다.")
            return False
        
        # 2. 사용 컬럼 값이 가장 낮은 행부터 시작하여 작업 가능한 행 찾기
        print("2단계: 작업 가능한 행 찾기")
        if '사용' not in df.columns:
            print("'사용' 컬럼이 없어 첫 번째 데이터 행부터 확인합니다.")
            정렬된_인덱스 = df.index.tolist()
        else:
            df['사용'] = pd.to_numeric(df['사용'], errors='coerce').fillna(0)
            # 사용 값이 낮은 순서대로 정렬
            정렬된_인덱스 = df.sort_values('사용').index.tolist()
        
        # 계정정보 스프레드시트 미리 가져오기
        print("계정정보 스프레드시트에서 계정 정보 가져오기...")
        id_df = 구글스프레드시트_계정정보_가져오기()
        if id_df.empty:
            print("계정정보 스프레드시트에서 계정 정보를 가져올 수 없습니다.")
            return False
        
        # 필수 컬럼 추가
        if '로그인간격_분' not in id_df.columns:
            id_df['로그인간격_분'] = 30
        if '마지막로그인시간' not in id_df.columns:
            id_df['마지막로그인시간'] = ''
        
        # 작업 가능한 행 찾기
        선택_행_인덱스 = None
        선택_행 = None
        
        for 행_인덱스 in 정렬된_인덱스:
            행 = df.iloc[행_인덱스]
            
            # 지명키워드가 있는지 확인
            지명키워드 = str(행['지명키워드']).strip() if '지명키워드' in df.columns else ''
            if not 지명키워드 or 지명키워드.lower() == 'nan' or 지명키워드 == '':
                continue
            
            사용아이디 = str(행['사용아이디']).strip() if '사용아이디' in df.columns else ''
            if 사용아이디 == 'nan':
                사용아이디 = ''
            
            # 사용아이디가 있으면 계정정보 스프레드시트에 등록되어 있는지 확인
            if 사용아이디 and 사용아이디.strip():
                사용아이디_목록 = str(사용아이디).split(",")
                사용아이디_목록 = [아이디.strip() for 아이디 in 사용아이디_목록 if 아이디.strip()]
                
                # 사용아이디 목록 중 하나라도 계정정보에 있는지 확인
                등록된_아이디_있음 = False
                작업_가능한_아이디 = None
                
                for 아이디 in 사용아이디_목록:
                    if 아이디 in id_df['아이디'].values:
                        등록된_아이디_있음 = True
                        # 로그인금지시간대 확인
                        if 로그인금지시간대_확인(아이디, id_df):
                            작업_가능한_아이디 = 아이디
                            break
                
                if not 등록된_아이디_있음:
                    print(f"  → 행 {행_인덱스 + 2}: 사용아이디 '{사용아이디}'가 계정정보 스프레드시트에 등록되어 있지 않습니다.")
                    continue
                
                if not 작업_가능한_아이디:
                    print(f"  → 행 {행_인덱스 + 2}: 사용아이디 '{사용아이디}'는 로그인금지시간대입니다.")
                    continue
            else:
                # 사용아이디가 없으면 전체 계정 사용 가능
                pass
            
            # 작업 가능한 행을 찾았음
            선택_행_인덱스 = 행_인덱스
            선택_행 = 행
            print(f"작업 가능한 행을 찾았습니다: 행 {행_인덱스 + 2}")
            break
        
        # 작업 가능한 행이 없으면 False 반환
        if 선택_행_인덱스 is None or 선택_행 is None:
            print("작업 가능한 행이 없습니다. 원래 경로로 진행합니다.")
            return False
        
        # 3. 필요한 값 추출
        print("3단계: 필요한 값 추출")
        지명키워드 = str(선택_행['지명키워드']).strip() if '지명키워드' in df.columns else ''
        하나노란 = str(선택_행['하나노란']).strip() if '하나노란' in df.columns else ''
        if 하나노란 == 'nan':
            하나노란 = ''
        사용아이디 = str(선택_행['사용아이디']).strip() if '사용아이디' in df.columns else ''
        if 사용아이디 == 'nan':
            사용아이디 = ''
        
        # 지명키워드를 지명과 키워드로 분리 (공백 기준 첫 번째 단어는 지명, 나머지는 키워드)
        지명 = ''
        키워드 = ''
        if 지명키워드:
            parts = 지명키워드.split(maxsplit=1)
            if len(parts) >= 1:
                지명 = parts[0]
            if len(parts) >= 2:
                키워드 = parts[1]
        
        주제 = str(선택_행['주제']).strip() if '주제' in df.columns else ''
        if 주제 == 'nan':
            주제 = ''
        
        서비스 = str(선택_행['서비스']).strip() if '서비스' in df.columns else ''
        if 서비스 == 'nan':
            서비스 = ''
        
        print(f"추출된 값: 지명={지명}, 키워드={키워드}, 지명키워드={지명키워드}, 하나노란={하나노란}, 사용아이디={사용아이디}, 주제={주제}, 서비스={서비스}")
        
        # 4. 지명키워드 캐시 DataFrame 업데이트 (xlsx 파일 불필요)
        print("4단계: 지명키워드 캐시 업데이트")
        global _지명키워드_캐시_df
        result_df = pd.DataFrame({
            '지명': [지명],
            '키워드': [키워드],
            '지명키워드': [지명키워드],
            '하나노란': [하나노란],
            '사용아이디': [사용아이디],
            '주제': [주제] if 주제 else [''],
            '서비스': [서비스] if 서비스 else [''],
            '포스팅작업요청_행인덱스': [선택_행_인덱스 + 2]  # 스프레드시트 행 번호 (헤더 포함, 1-based)
        })
        _지명키워드_캐시_df = result_df
        print(f"지명키워드 캐시 업데이트 완료: {지명키워드}")
        중요_작업_로그_저장(f"포스팅 작업요청 - 지명키워드 캐시 업데이트 완료: {지명키워드}")
        
        # 5. 사용 컬럼 값 +1 업데이트
        if '사용' in df.columns:
            print("5단계: 사용 컬럼 값 업데이트")
            현재_사용_횟수 = int(df.loc[선택_행_인덱스, '사용'])
            새_사용_횟수 = 현재_사용_횟수 + 1
            print(f"사용 횟수 업데이트: {현재_사용_횟수} → {새_사용_횟수}")
            
            업데이트_성공 = False
            for 재시도 in range(3):
                if 구글_시트_특정_행_업데이트(포스팅작업요청_스프레드시트_ID, 지명키워드, 선택_행_인덱스, '사용', 새_사용_횟수):
                    print(f"사용 횟수 업데이트 성공: {새_사용_횟수}")
                    업데이트_성공 = True
                    break
                else:
                    print(f"사용 횟수 업데이트 실패 (재시도 {재시도 + 1}/3)")
                    if 재시도 < 2:
                        # API 할당량 초과를 고려하여 더 긴 대기 시간 설정
                        대기_시간 = 65 + (재시도 * 5)  # 65초부터 시작하여 재시도마다 5초씩 증가
                        print(f"⚠️ {대기_시간}초 대기 후 재시도합니다...")
                        time.sleep(대기_시간)
            
            if not 업데이트_성공:
                print("사용 횟수 업데이트 실패했지만 계속 진행합니다.")
        
        # 6. 아이디2 구글 시트에서 계정 필터링 (로컬 xlsx 파일 생성 없음)
        print("6단계: 아이디2 구글 시트에서 계정 필터링")
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        순위_파일 = resource_path("뷰순위.xlsx")
        
        # 겹치는_상호_제거_사용이 True이고 겹치는_개수가 아직 계산되지 않았으면 계산
        if 겹치는_상호_제거_사용 and 겹치는_개수 == 0:
            겹치는_개수 = 엑셀_상호_비교(순위_파일)
        
        # 1. 구글 스프레드시트 → 계정정보 가져오기
        print("  6-1: 구글 스프레드시트에서 계정정보 가져오기")
        id_df = 구글스프레드시트_계정정보_가져오기()
        if id_df.empty:
            print("구글 스프레드시트에서 계정정보를 가져올 수 없습니다.")
            return False
        
        # 2-3. 겹치는 상호 제거 (선택적)
        if 겹치는_상호_제거_사용:
            print("  6-2: 뷰순위.xlsx에서 이미 작업된 상호 확인")
            rank_df = pd.read_excel(순위_파일)
            print("  6-3: 겹치는 상호 제거")
            id_titles = set(id_df['상호'].astype(str).str.strip())
            rank_titles = set(rank_df['상호'].astype(str).str.strip())
            겹치는_상호 = id_titles & rank_titles
            작업_df = id_df[~id_df['상호'].astype(str).str.strip().isin(겹치는_상호)]
            print(f"겹치는 상호 제거 후 남은 계정 수: {len(작업_df)}개")
        else:
            print("  6-2-3: 겹치는 상호 제거 기능을 사용하지 않아 전체 계정을 사용합니다.")
            작업_df = id_df.copy()
            print(f"전체 계정 수: {len(작업_df)}개")
        
        # 4. 지명키워드.xlsx에서 지명 값 가져오기
        print("  6-4: 지명키워드.xlsx에서 지명 값 가져오기")
        현재_지명 = 지명
        
        # 5. 사용아이디로 계정 필터링
        if 사용아이디 and 사용아이디.strip():
            print(f"  6-5: 사용아이디 '{사용아이디}'로 계정 필터링")
            작업_df = 사용아이디로_계정_필터링(사용아이디, 작업_df)
            print(f"필터링된 계정 수: {len(작업_df)}개")
        
        # 7. 필수 컬럼 추가
        print("  6-7: 필수 컬럼 추가")
        if '포스팅수' not in 작업_df.columns:
            작업_df['포스팅수'] = 0
        if '로그인간격_분' not in 작업_df.columns:
            작업_df['로그인간격_분'] = 30
        if '마지막로그인시간' not in 작업_df.columns:
            작업_df['마지막로그인시간'] = ''
        
        # 7-0. 하루최대포스팅수가 0인 아이디 제외
        print("  6-7-0: 하루최대포스팅수 필터링")
        if '하루최대포스팅수' in 작업_df.columns:
            # 하루최대포스팅수를 숫자로 변환 (문자열일 수 있으므로)
            작업_df['하루최대포스팅수'] = pd.to_numeric(작업_df['하루최대포스팅수'], errors='coerce')
            
            # 하루최대포스팅수가 0 이하인 아이디들 필터링
            필터링_전_개수 = len(작업_df)
            작업_df = 작업_df[
                (작업_df['하루최대포스팅수'] > 0) & 
                (작업_df['하루최대포스팅수'].notna())
            ]
            필터링_후_개수 = len(작업_df)
            print(f"하루최대포스팅수가 0 이하인 아이디를 제외한 후 {필터링_후_개수}개의 아이디가 남았습니다. (제외: {필터링_전_개수 - 필터링_후_개수}개)")
            
            if 필터링_후_개수 == 0:
                print("하루최대포스팅수 제한으로 인해 사용 가능한 아이디가 없습니다.")
                return False
        else:
            print("하루최대포스팅수 컬럼이 없어 필터링을 건너뜁니다.")
        
        # 7-1. 로그인금지시간대 필터링
        print("  6-8: 로그인금지시간대 필터링")
        print(f"현재 시간: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일'][datetime.datetime.now().weekday()]})")
        
        시간제한_아이디들 = []
        for idx, row in 작업_df.iterrows():
            아이디 = row['아이디']
            if not 로그인금지시간대_확인(아이디, 작업_df):
                시간제한_아이디들.append(아이디)
                print(f"  → 아이디 '{아이디}'는 현재 시간에 로그인이 금지되어 제외됩니다.")
        
        작업_df = 작업_df[~작업_df['아이디'].isin(시간제한_아이디들)]
        print(f"로그인금지시간대 확인 후 남은 계정 수: {len(작업_df)}개")
        
        if len(작업_df) == 0:
            print("로그인금지시간대 제한으로 인해 사용 가능한 아이디가 없습니다.")
            print("다른 시간에 다시 시도해주세요.")
            return False
        
        # 7-2. 구글 스프레드시트에서 사용 중인 아이디 필터링
        print("  6-9: 구글 스프레드시트에서 사용 중인 아이디 필터링")
        사용중인_아이디들 = []
        try:
            사용중인_아이디들 = 구글스프레드시트_사용중인_아이디_목록_가져오기()
            print(f"현재 구글 스프레드시트에서 사용 중인 아이디들: {사용중인_아이디들}")
        except Exception as e:
            print(f"구글 스프레드시트에서 사용 중인 아이디 목록 가져오기 실패: {e}")
            사용중인_아이디들 = []
        
        # 사용 중이지 않은 아이디들만 필터링
        사용가능한_아이디들 = 작업_df[~작업_df['아이디'].isin(사용중인_아이디들)]
        
        if len(사용가능한_아이디들) == 0:
            print("모든 아이디가 구글 스프레드시트에서 사용 중입니다.")
            중요_작업_로그_저장("포스팅 작업요청 분기 - 모든 아이디가 구글 스프레드시트에서 사용 중")
            print("모든 아이디가 사용 중이어서 프로그램을 재시작합니다.")
            
            프로그램_같은_터미널_재시작("포스팅 작업요청 - 모든 아이디 사용 중")
        
        print(f"사용 가능한 아이디 수: {len(사용가능한_아이디들)}개")
        작업_df = 사용가능한_아이디들
        
        # 8. 계정 필터링 완료 (구글 시트 직접 사용, xlsx 저장 없음)
        print(f"  6-10: 계정 필터링 완료 - 사용 가능 계정 {len(작업_df)}개 (구글 시트 직접 사용)")
        
        if 현재_지명:
            중요_작업_로그_저장(f"포스팅 작업요청 - 계정 필터링 완료 - 현재 작업 지명: {현재_지명}, 계정 수: {len(작업_df)}개")
        
        # === 계정 필터링 완료 후 IP 교체 실행 ===
        if 설정_아이피교체 != 1:
            if 설정_작업_허용_아이피:
                print(f"[설정.xlsx] 아이피교체={설정_작업_허용_아이피} (고정 IP) - IP 교체를 건너뜁니다.")
            else:
                print("[설정.xlsx] 아이피교체 OFF - IP 교체를 건너뜁니다.")
        elif len(작업_df) > 0:
            print("\n계정 필터링 완료 후 IP 교체를 실행합니다...")
            중요_작업_로그_저장("포스팅 작업요청 - 계정 필터링 완료 후 자동 IP 교체 시스템 시작")
            
            # === IP 교체 시스템 설정 ===
            MAX_IP_CHANGE_RETRIES = 10      # 최대 재시도 횟수 (필요시 조정 가능)
            INITIAL_RETRY_DELAY = 30        # 초기 재시도 대기 시간 (초)
            RETRY_DELAY_INCREMENT = 30      # 재시도마다 증가하는 대기 시간 (초)
            
            # IP 교체 시스템 실행 - 성공할 때까지 재시도
            print("\n🔄 IP 교체를 성공할 때까지 계속 시도합니다...")
            print(f"설정: 최대 {MAX_IP_CHANGE_RETRIES}회 시도, 대기시간 {INITIAL_RETRY_DELAY}초부터 점진적 증가")
            ip_change_success = False
            retry_count = 0
            
            # === IP 교체 시스템 실행 ===
            while not ip_change_success and retry_count < MAX_IP_CHANGE_RETRIES:
                retry_count += 1
                print(f"\n🔄 IP 교체 시도 {retry_count}번째...")
                중요_작업_로그_저장(f"포스팅 작업요청 - 계정 필터링 후 IP 교체 {retry_count}번째 시도 시작")
                
                try:
                    if auto_ip_change_system():
                        print("✅ IP 교체가 성공적으로 완료되었습니다!")
                        중요_작업_로그_저장(f"포스팅 작업요청 - 계정 필터링 후 IP 교체 성공 (시도 {retry_count}번째)")
                        ip_change_success = True
                    else:
                        print(f"⚠️ IP 교체 {retry_count}번째 시도 실패")
                        if retry_count < MAX_IP_CHANGE_RETRIES:
                            # 재시도 간격을 점진적으로 증가 (30초 → 60초 → 90초...)
                            wait_time = INITIAL_RETRY_DELAY + (retry_count - 1) * RETRY_DELAY_INCREMENT
                            print(f"🔄 {wait_time}초 후 재시도합니다... (시도 {retry_count}/{MAX_IP_CHANGE_RETRIES})")
                            중요_작업_로그_저장(f"포스팅 작업요청 - 계정 필터링 후 IP 교체 {retry_count}번째 시도 실패, {wait_time}초 후 재시도 예정")
                            time.sleep(wait_time)
                        else:
                            print("❌ 최대 재시도 횟수에 도달했습니다. 프로그램을 종료합니다.")
                            중요_작업_로그_저장(f"포스팅 작업요청 - 계정 필터링 후 IP 교체 최대 재시도 횟수 도달, 프로그램 종료")
                            sys.exit(1)  # 프로그램 강제 종료
                            
                except Exception as e:
                    print(f"❌ IP 교체 {retry_count}번째 시도 중 오류 발생: {e}")
                    if retry_count < MAX_IP_CHANGE_RETRIES:
                        # 재시도 간격을 점진적으로 증가 (30초 → 60초 → 90초...)
                        wait_time = INITIAL_RETRY_DELAY + (retry_count - 1) * RETRY_DELAY_INCREMENT
                        print(f"🔄 {wait_time}초 후 재시도합니다... (시도 {retry_count}/{MAX_IP_CHANGE_RETRIES})")
                        중요_작업_로그_저장(f"포스팅 작업요청 - 계정 필터링 후 IP 교체 {retry_count}번째 시도 오류: {str(e)}, {wait_time}초 후 재시도 예정")
                        time.sleep(wait_time)
                    else:
                        print("❌ 최대 재시도 횟수에 도달했습니다. 프로그램을 종료합니다.")
                        중요_작업_로그_저장(f"포스팅 작업요청 - 계정 필터링 후 IP 교체 최대 재시도 횟수 도달, 프로그램 종료")
                        sys.exit(1)  # 프로그램 강제 종료
            
            if ip_change_success:
                if 설정_아이피교체 == 1:
                    print("🎉 IP 교체 성공! 다음 단계로 진행합니다.")
            else:
                print("❌ IP 교체 실패로 프로그램이 종료됩니다.")
                sys.exit(1)
        else:
            print("⚠️ 사용 가능한 계정이 없어 IP 교체를 건너뜁니다.")
        
        print("=== 포스팅 작업요청 경로 완료 ===")
        return True
        
    except Exception as e:
        print(f"포스팅 작업요청 처리 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False



# ==============================================================================
# 포스팅.py 시작
# 예약시간 도래 시 키워드생성_실행()이 지명키워드 구글시트에 데이터를 저장합니다.
# ==============================================================================

지명키워드_구글시트_ID = "1rGentuqu4Jhzxv-b-Zu92AejlBXWdoYb6Qp3DO1XhOM"
지명키워드_작업_시트_GID = 1679797725  # 지명키워드가 이미 등록된 작업 대기 시트
지명키워드_이력_시트_GID = 39603624  # 지명키워드 생성 이력 기록 시트 (날짜/아이디/폴더/글유형/아이피/링크)
서비스지역_시트_GID = 1646398695  # SEO 서비스 지역 안내 목록 (원고 생성용)
_지명키워드_이력_헤더 = ['지명키워드', '날짜', '사용아이디', '폴더', '글유형', '세부유형', '아이피', '링크']
_서비스지역_시트_헤더 = ['그룹명', '지역묶음', '지역동의어', '핫지역', '사용', '비고']
전용아이디_시트_GID = 2069004194


def _작업_폴더명():
    """현재 작업 PC 폴더명 (이력·스케줄·전용아이디 시트 공통)"""
    return os.path.basename(os.getcwd())

# 지명키워드 전역 캐시 (구글시트에서 한 번 읽어 메모리에 보관)
_지명키워드_캐시_df = None
_지명키워드_작업_행번호 = None
_로컬_작업_스케줄 = []
_전용아이디_시트_등록됨 = False
_전용아이디_등록_폴더 = ''
_전용아이디_정리_완료 = False
_전용아이디_종료훅_등록됨 = False
_전용아이디_목록_캐시 = None
_전용아이디_목록_캐시_시각 = None
_전용아이디_목록_캐시_TTL_초 = 60
_전용아이디_ws_캐시 = None
_전용아이디_ws_캐시_시각 = None
_스케줄_창_끝 = None
_스케줄_자정대기 = False
_현재_스케줄_항목 = None
_스케줄_현황_출력_간격 = 10
_마지막_공용_스케줄_재계획 = None
_공용_스케줄_재계획_간격_초 = 300
_테스트_스케줄_활성 = False
_테스트_스케줄_추가됨 = False
_스케줄_균등_분포_임계값 = 8
_스케줄_PC_변칙_분_캐시 = None


def 지명키워드_df_가져오기():
    """지명키워드 캐시 DataFrame 반환. 캐시가 없으면 빈 DataFrame 반환."""
    if _지명키워드_캐시_df is not None:
        return _지명키워드_캐시_df
    return pd.DataFrame()


def _셀값_비어있음(값):
    if 값 is None:
        return True
    s = str(값).strip()
    return s == '' or s.lower() in ('nan', 'none')


def _현재_작업_지명키워드():
    """작업큐 캐시에서 현재 지명키워드 반환"""
    try:
        df = 지명키워드_df_가져오기()
        if not df.empty and '지명키워드' in df.columns:
            kw = str(df.iloc[0]['지명키워드']).strip()
            if not _셀값_비어있음(kw):
                return kw
    except Exception:
        pass
    return None


def _지명키워드_동일(저장값, 현재값):
    if _셀값_비어있음(저장값) or _셀값_비어있음(현재값):
        return False
    return str(저장값).strip().replace(' ', '') == str(현재값).strip().replace(' ', '')


def _포스팅만_재시도_플래그_지명키워드():
    """재시도 플래그 파일에 기록된 지명키워드 반환 (없으면 None)"""
    try:
        path = _포스팅만_재시도_플래그_경로()
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            v = str(f.read()).strip()
        if not v or v.lower() in ('nan', 'none'):
            return None
        return v
    except Exception:
        return None


def _최종원고_지명키워드_일치(지명키워드):
    """최종원고.txt 제목(첫 줄)에 현재 지명키워드 전체가 포함되는지 확인 (지명만 같으면 불일치)"""
    if _셀값_비어있음(지명키워드):
        return False
    원고_경로 = resource_path('최종원고.txt')
    if not os.path.exists(원고_경로):
        return False
    try:
        with open(원고_경로, 'r', encoding='utf-8') as f:
            첫줄 = f.readline().strip().lstrip('#').strip()
        if not 첫줄:
            return False
        kw_norm = str(지명키워드).strip().replace(' ', '')
        title_norm = 첫줄.replace(' ', '')
        return bool(kw_norm) and kw_norm in title_norm
    except Exception:
        return False


def _원고_작성_지명키워드_경로():
    return resource_path(os.path.join('_internal', '원고_지명키워드.txt'))


def _원고_작성_지명키워드_저장(지명키워드):
    """최종원고 작성 시 사용한 지명키워드를 파일에 기록 (완전 일치 검증용)"""
    try:
        path = _원고_작성_지명키워드_경로()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(str(지명키워드).strip())
    except Exception as e:
        오류_로그_저장(f"원고 지명키워드 저장 오류: {e}")


def _원고_작성_지명키워드_읽기():
    try:
        path = _원고_작성_지명키워드_경로()
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            v = str(f.read()).strip()
        if _셀값_비어있음(v):
            return None
        return v
    except Exception:
        return None


def _원고_캐시_파일_삭제():
    """지명키워드 변경 시 이전 원고·연관어·키워드 기록 삭제"""
    for rel in ('최종원고.txt', '연관어.txt', os.path.join('_internal', '원고_지명키워드.txt')):
        try:
            path = resource_path(rel)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _원고_작성_지명키워드_일치(지명키워드):
    """저장된 원고 지명키워드와 현재 키워드 완전 동일 여부 (지명만 같고 서비스 다르면 불일치)"""
    if _셀값_비어있음(지명키워드):
        return False
    저장된 = _원고_작성_지명키워드_읽기()
    if 저장된:
        return _지명키워드_동일(저장된, 지명키워드)
    return _최종원고_지명키워드_일치(지명키워드)


def _블로그제목_현재키워드_행_선택(제목_df, 지명키워드):
    """현재 작업 지명키워드와 일치하는 블로그제목 행 1개 선택 (없으면 None)"""
    if 제목_df is None or 제목_df.empty or _셀값_비어있음(지명키워드):
        return None
    if '지명키워드' not in 제목_df.columns:
        return None
    일치_행 = 제목_df[
        제목_df['지명키워드'].apply(lambda v: _지명키워드_동일(v, 지명키워드))
    ]
    if 일치_행.empty:
        return None
    return 일치_행.sample(n=1).iloc[0]


def _키워드생성_후_원고캐시_초기화(새_지명키워드):
    """새 지명키워드 생성 시 이전 포스팅 재시도 플래그 해제, 키워드 변경 시 원고 캐시 삭제"""
    global _원고_재사용_모드
    _포스팅만_재시도_플래그_해제()
    _원고_재사용_모드 = False
    저장된 = _원고_작성_지명키워드_읽기()
    if not _지명키워드_동일(새_지명키워드, 저장된):
        _원고_캐시_파일_삭제()
        if 저장된:
            print(
                f"지명키워드 변경('{저장된}' -> '{새_지명키워드}') "
                f"- 기존 원고·연관어 삭제, 제목·원고 재생성"
            )
        else:
            print(f"새 지명키워드 생성('{새_지명키워드}') - 원고 캐시 없음, 제목·원고 재생성")
    else:
        print(f"동일 지명키워드('{새_지명키워드}') - 원고 재사용 가능 (플래그만 해제)")


def _포스팅만_재시도_플래그_경로():
    return resource_path(os.path.join('_internal', '포스팅만_재시도.flag'))


def _포스팅만_재시도_플래그_설정():
    """재시작 시 IP/제목/원고 생성을 건너뛰도록 플래그 기록"""
    try:
        path = _포스팅만_재시도_플래그_경로()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(_현재_작업_지명키워드() or '')
    except Exception as e:
        오류_로그_저장(f"포스팅만 재시도 플래그 설정 오류: {e}")


def _포스팅만_재시도_플래그_확인():
    return os.path.exists(_포스팅만_재시도_플래그_경로())


def _포스팅만_재시도_플래그_해제():
    try:
        path = _포스팅만_재시도_플래그_경로()
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _기존_원고_재사용_가능(지명키워드=None):
    """실패·대기 재시작 시 원고 재사용 비활성화 (항상 재생성)"""
    return False


_제목원고_생성_재시도_간격_초 = 120


def _블로그제목_생성_완료(지명키워드=None):
    """블로그제목.xlsx에 현재 지명키워드 제목이 저장됐는지 확인"""
    if not 지명키워드:
        지명키워드 = _현재_작업_지명키워드()
    if not 지명키워드:
        return False
    제목_경로 = resource_path('블로그제목.xlsx')
    if not os.path.exists(제목_경로):
        return False
    try:
        제목_df = pd.read_excel(제목_경로)
        if 제목_df.empty or '지명키워드' not in 제목_df.columns or '생성된제목' not in 제목_df.columns:
            return False
        row = _블로그제목_현재키워드_행_선택(제목_df, 지명키워드)
        if row is None:
            return False
        제목 = str(row.get('생성된제목', '')).strip()
        return bool(제목) and 제목.lower() not in ('nan', 'none')
    except Exception:
        return False


def _최종원고_생성_완료(지명키워드=None):
    """최종원고·연관어가 현재 지명키워드 기준으로 준비됐는지 확인"""
    if not 지명키워드:
        지명키워드 = _현재_작업_지명키워드()
    if not 지명키워드:
        return False
    원고_경로 = resource_path('최종원고.txt')
    if not os.path.exists(원고_경로) or os.path.getsize(원고_경로) < 100:
        return False
    if not _원고_작성_지명키워드_일치(지명키워드):
        return False
    연관어_경로 = resource_path('연관어.txt')
    if not os.path.exists(연관어_경로) or os.path.getsize(연관어_경로) < 5:
        return False
    return True


def _블로그제목_생성_무한_재시도(생성_함수):
    """제목 생성 실패 시 2분 간격 무제한 재시도"""
    시도 = 0
    kw = _현재_작업_지명키워드()
    while True:
        시도 += 1
        print(f"\n=== 블로그 제목 생성 시도 {시도}회 (지명키워드: {kw}) ===")
        try:
            생성_함수()
        except Exception as e:
            print(f"블로그 제목 생성 중 오류: {e}")
            오류_로그_저장(f"블로그 제목 생성 오류 (시도 {시도}): {e}")
        if _블로그제목_생성_완료(kw):
            print(f"블로그 제목 생성 완료 (시도 {시도}회)")
            중요_작업_로그_저장(f"블로그 제목 생성 완료 (시도 {시도}회): {kw}")
            return
        print(
            f"블로그 제목 생성 미완료 - "
            f"{_제목원고_생성_재시도_간격_초}초 후 재시도합니다... (시도 {시도}회)"
        )
        중요_작업_로그_저장(f"블로그 제목 생성 실패 - 2분 후 재시도 (시도 {시도}): {kw}")
        time.sleep(_제목원고_생성_재시도_간격_초)


def _최종원고_생성_무한_재시도(생성_함수):
    """원고·연관어 생성 실패 시 2분 간격 무제한 재시도"""
    시도 = 0
    kw = _현재_작업_지명키워드()
    while True:
        시도 += 1
        print(f"\n=== 최종원고 생성 시도 {시도}회 (지명키워드: {kw}) ===")
        try:
            생성_함수()
        except Exception as e:
            print(f"최종원고 생성 중 오류: {e}")
            오류_로그_저장(f"최종원고 생성 오류 (시도 {시도}): {e}")
        if _최종원고_생성_완료(kw):
            print(f"최종원고·연관어 생성 완료 (시도 {시도}회)")
            중요_작업_로그_저장(f"최종원고·연관어 생성 완료 (시도 {시도}회): {kw}")
            return
        print(
            f"최종원고 생성 미완료 - "
            f"{_제목원고_생성_재시도_간격_초}초 후 재시도합니다... (시도 {시도}회)"
        )
        중요_작업_로그_저장(f"최종원고 생성 실패 - 2분 후 재시도 (시도 {시도}): {kw}")
        time.sleep(_제목원고_생성_재시도_간격_초)


_원고_재사용_모드 = False


def _컬럼_글자(n):
    """1-based column index -> Excel column letter (A, B, ... Z, AA, ...)"""
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _시트_범위_업데이트(worksheet, range_name, values, value_input_option='USER_ENTERED', timeout=20, operation_name='시트 범위 업데이트'):
    """Worksheet.update DeprecationWarning 회피 (gspread 6.0 대비 batch_update 사용)"""
    gspread_operation_with_timeout(
        lambda: worksheet.batch_update(
            [{'range': range_name, 'values': values}],
            value_input_option=value_input_option
        ),
        timeout=timeout,
        operation_name=operation_name
    )


def _시트_429_오류(e):
    """Google Sheets API 429(할당량 초과) 여부"""
    if hasattr(e, 'response') and hasattr(e.response, 'status_code') and e.response.status_code == 429:
        return True
    s = str(e)
    return '429' in s or 'RATE_LIMIT_EXCEEDED' in s or 'Quota exceeded' in s


def _시트_429_대기(시도_횟수, 작업명='시트'):
    """429 발생 시 분당 한도 리셋을 고려한 대기"""
    대기_시간 = 65 + (시도_횟수 * 5)
    print(f"API 할당량 초과({작업명}) - {대기_시간}초 후 재시도합니다...")
    time.sleep(대기_시간)


def _전용아이디_목록_캐시_유효():
    """전용아이디 목록 캐시 TTL 이내인지 확인"""
    if _전용아이디_목록_캐시 is None or _전용아이디_목록_캐시_시각 is None:
        return False
    return (datetime.datetime.now() - _전용아이디_목록_캐시_시각).total_seconds() < _전용아이디_목록_캐시_TTL_초


def _전용아이디_목록_캐시_무효화():
    """전용아이디 시트/목록 캐시 초기화"""
    global _전용아이디_목록_캐시, _전용아이디_목록_캐시_시각
    global _전용아이디_ws_캐시, _전용아이디_ws_캐시_시각
    _전용아이디_목록_캐시 = None
    _전용아이디_목록_캐시_시각 = None
    _전용아이디_ws_캐시 = None
    _전용아이디_ws_캐시_시각 = None


def _전용아이디_시트_가져오기():
    """gid=2069004194 시트2(전용아이디 목록) worksheet 반환"""
    global _전용아이디_ws_캐시, _전용아이디_ws_캐시_시각
    if _전용아이디_ws_캐시 is not None and _전용아이디_ws_캐시_시각 is not None:
        if (datetime.datetime.now() - _전용아이디_ws_캐시_시각).total_seconds() < _전용아이디_목록_캐시_TTL_초:
            return _전용아이디_ws_캐시
    _키_파일 = resource_path('khon21-534690057aec.json')
    import socket as _sock
    _원래 = _sock.getdefaulttimeout()
    _sock.setdefaulttimeout(20)
    try:
        _scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        _creds = Credentials.from_service_account_file(_키_파일, scopes=_scope)
        _gc = gspread_authorize_with_timeout(_creds)
        _sp = gspread_operation_with_timeout(
            lambda: _gc.open_by_key(지명키워드_구글시트_ID), timeout=20, operation_name="전용아이디 시트 열기")
        for _ws in gspread_operation_with_timeout(
                lambda: _sp.worksheets(), timeout=10, operation_name="전용아이디 시트 목록"):
            if _ws.id == 전용아이디_시트_GID:
                _전용아이디_ws_캐시 = _ws
                _전용아이디_ws_캐시_시각 = datetime.datetime.now()
                return _ws
        _ws = gspread_operation_with_timeout(
            lambda: _sp.get_worksheet(1), timeout=10, operation_name="전용아이디 시트2 fallback")
        _전용아이디_ws_캐시 = _ws
        _전용아이디_ws_캐시_시각 = datetime.datetime.now()
        return _ws
    finally:
        _sock.setdefaulttimeout(_원래)


def _동일_폴더_프로그램_실행_중():
    """같은 폴더에서 포스팅.py/exe가 다른 PID로 실행 중이면 True (재시작 시 종료 삭제 방지)"""
    try:
        import psutil
    except ImportError:
        return False
    내_pid = os.getpid()
    내_스크립트 = os.path.abspath(__file__).lower()
    내_폴더 = os.path.basename(os.getcwd()).lower()
    for proc in psutil.process_iter(['pid', 'cmdline', 'cwd']):
        try:
            pid = proc.info.get('pid')
            if not pid or pid == 내_pid:
                continue
            cmdline = proc.info.get('cmdline') or []
            cmd_text = ' '.join(str(c) for c in cmdline).lower()
            if '포스팅.py' not in cmd_text and '포스팅.exe' not in cmd_text:
                if os.path.basename(내_스크립트) not in cmd_text:
                    continue
            cwd = proc.info.get('cwd') or ''
            if cwd and os.path.basename(cwd).lower() == 내_폴더:
                return True
            if 내_스크립트 in cmd_text:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False


def _전용아이디_종료훅_등록():
    """종료 시 전용아이디 시트 행 삭제 비활성화 (시트 값 유지)"""
    return


def _전용아이디_시트_종료_정리():
    """종료 시 전용아이디 시트 행 삭제 안 함 (시트 값 유지)"""
    return


def _전용아이디_시트_기록():
    """설정.xlsx 사용아이디를 시트2 전용아이디 컬럼에 기록 (PC 폴더 기준 upsert)"""
    global _전용아이디_시트_등록됨, _전용아이디_등록_폴더
    uid = str(설정_사용아이디 or '').strip()
    if uid.lower() in ('', 'nan', 'none', '*'):
        msg = "공용 PC - 전용아이디 시트 기록 생략"
        print(msg)
        디버그_로그_저장(msg)
        return

    폴더명 = os.path.basename(os.getcwd())
    try:
        _ws = _전용아이디_시트_가져오기()
        _all = gspread_operation_with_timeout(
            lambda: _ws.get_all_values(), timeout=20, operation_name="전용아이디 시트 읽기")

        if not _all:
            headers = ['폴더', '전용아이디']
            _시트_범위_업데이트(_ws, 'A1:B1', [headers], operation_name="전용아이디 헤더 생성")
            _all = [headers]

        headers = list(_all[0])
        if '전용아이디' not in headers:
            gspread_operation_with_timeout(
                lambda: _ws.update_cell(1, len(headers) + 1, '전용아이디'),
                timeout=10, operation_name="전용아이디 헤더 추가")
            headers.append('전용아이디')

        if '폴더' not in headers:
            old_headers = headers[:]
            headers = ['폴더'] + old_headers
            _시트_범위_업데이트(_ws, 'A1', [headers], operation_name="폴더 헤더 추가")
            if len(_all) > 1:
                for row_idx in range(1, len(_all)):
                    old_row = _all[row_idx] + [''] * max(0, len(old_headers) - len(_all[row_idx]))
                    padded = [''] + old_row[:len(old_headers)]
                    end_col = _컬럼_글자(len(headers))
                    _시트_범위_업데이트(
                        _ws, f'A{row_idx + 1}:{end_col}{row_idx + 1}', [padded],
                        operation_name=f"폴더 컬럼 삽입 {row_idx + 1}행")
            _all[0] = headers

        폴더_i = headers.index('폴더')
        uid_i = headers.index('전용아이디')
        target_row = None

        # 1차: 폴더명으로 검색
        for row_idx in range(1, len(_all)):
            row = _all[row_idx] + [''] * (len(headers) - len(_all[row_idx]))
            if str(row[폴더_i]).strip() == 폴더명:
                target_row = row_idx + 1
                break

        # 2차: 폴더명 불일치 시 전용아이디로 검색 (같은 아이디가 다른 폴더로 등록된 경우)
        if target_row is None:
            현재_uid_set = set(_id_정규화(p) for p in uid.split(',') if _id_정규화(p))
            for row_idx in range(1, len(_all)):
                row = _all[row_idx] + [''] * (len(headers) - len(_all[row_idx]))
                기존_uid = str(row[uid_i]).strip()
                기존_uid_set = set(_id_정규화(p) for p in 기존_uid.split(',') if _id_정규화(p))
                if 현재_uid_set & 기존_uid_set:
                    target_row = row_idx + 1
                    print(f"전용아이디 일치 행 발견: 기존폴더='{row[폴더_i]}' -> 새폴더='{폴더명}' (행 {target_row}) - 업데이트")
                    break

        row_data = [''] * len(headers)
        row_data[폴더_i] = 폴더명
        row_data[uid_i] = uid

        end_col = _컬럼_글자(len(headers))
        if target_row:
            _시트_범위_업데이트(
                _ws, f'A{target_row}:{end_col}{target_row}', [row_data],
                operation_name=f"전용아이디 {target_row}행 갱신")
            msg = f"전용아이디 시트 갱신: 폴더='{폴더명}', 전용아이디='{uid}' (행 {target_row})"
        else:
            new_row = len(_all) + 1
            _시트_범위_업데이트(
                _ws, f'A{new_row}:{end_col}{new_row}', [row_data],
                operation_name=f"전용아이디 {new_row}행 추가")
            msg = f"전용아이디 시트 추가: 폴더='{폴더명}', 전용아이디='{uid}' (행 {new_row})"

        print(msg)
        디버그_로그_저장(msg)
        _전용아이디_시트_등록됨 = True
        _전용아이디_등록_폴더 = 폴더명
        _전용아이디_목록_캐시_무효화()
    except Exception as e:
        print(f"전용아이디 시트 기록 실패 (포스팅은 계속): {e}")
        오류_로그_저장(f"전용아이디 시트 기록 실패: {e}")


def _공용PC_모드():
    """설정.사용아이디가 비었거나 * 이면 공용 PC"""
    uid = str(설정_사용아이디 or '').strip()
    return not uid or uid.lower() in ('nan', 'none', '*')


def _전용아이디_목록_가져오기(강제_갱신=False):
    """시트2에 등록된 전용아이디 집합 (공용 PC 제외용, 1분 TTL 캐시)"""
    global _전용아이디_목록_캐시, _전용아이디_목록_캐시_시각
    if not 강제_갱신 and _전용아이디_목록_캐시_유효():
        return _전용아이디_목록_캐시

    최대_재시도 = 3
    for 시도 in range(최대_재시도):
        try:
            _ws = _전용아이디_시트_가져오기()
            _all = gspread_operation_with_timeout(
                lambda: _ws.get_all_values(), timeout=20, operation_name="전용아이디 목록 읽기")
            if not _all:
                _전용아이디_목록_캐시 = set()
                _전용아이디_목록_캐시_시각 = datetime.datetime.now()
                return _전용아이디_목록_캐시

            headers = list(_all[0])
            if '전용아이디' not in headers:
                _전용아이디_목록_캐시 = set()
                _전용아이디_목록_캐시_시각 = datetime.datetime.now()
                return _전용아이디_목록_캐시

            uid_i = headers.index('전용아이디')
            result = set()
            for row_idx in range(1, len(_all)):
                row = _all[row_idx] + [''] * (len(headers) - len(_all[row_idx]))
                raw = str(row[uid_i]).strip()
                if not raw or raw.lower() in ('nan', 'none'):
                    continue
                for part in raw.split(','):
                    uid = _id_정규화(part)
                    if uid:
                        result.add(uid)
            _전용아이디_목록_캐시 = result
            _전용아이디_목록_캐시_시각 = datetime.datetime.now()
            return result
        except Exception as e:
            if _시트_429_오류(e) and 시도 < 최대_재시도 - 1:
                _시트_429_대기(시도, '전용아이디 목록')
                continue
            print(f"전용아이디 목록 읽기 실패: {e}")
            if _전용아이디_목록_캐시 is not None:
                print("전용아이디 목록: 기존 캐시 사용 (시트 읽기 실패)")
                return _전용아이디_목록_캐시
            return set()


def _아이디_전용등록_충돌(사용아이디_값, 전용_목록):
    """사용아이디(쉼표 목록)가 시트2 전용아이디와 겹치면 True"""
    if not 전용_목록:
        return False
    for part in str(사용아이디_값).split(','):
        uid = _id_정규화(part)
        if uid and uid in 전용_목록:
            return True
    return False


def _행_값_가져오기(row_data, headers, col_name):
    if col_name not in headers:
        return ''
    idx = headers.index(col_name)
    if idx < len(row_data):
        return row_data[idx]
    return ''


def _id_정규화(값):
    s = str(값).strip()
    if s.lower() in ('nan', 'none', ''):
        return ''
    if s.endswith('.0'):
        try:
            f = float(s)
            if f == int(f):
                return str(int(f))
        except ValueError:
            pass
    return s


def _id_동일(a, b):
    return _id_정규화(a) == _id_정규화(b)


def _사용아이디_일치(행_사용아이디, 기준_사용아이디):
    """행의 사용아이디(쉼표 목록)와 기준 ID(단일 또는 쉼표)가 일치하는지"""
    if _셀값_비어있음(기준_사용아이디) or str(기준_사용아이디).strip() == '*':
        return True
    기준_목록 = [_id_정규화(x) for x in str(기준_사용아이디).split(',') if x.strip()]
    행_목록 = [_id_정규화(x) for x in str(행_사용아이디).split(',') if x.strip()]
    if not 기준_목록:
        return True
    return any(b in 행_목록 for b in 기준_목록)


def _행_완전_비어있음(row_data, headers):
    for i, _h in enumerate(headers):
        v = row_data[i] if i < len(row_data) else ''
        if not _셀값_비어있음(v):
            return False
    return True


def _행_설정ID_일치(row_data, headers, 설정_아이디):
    """전용 PC 매칭: 작업스케줄 사용아이디 == 설정.사용아이디 (PC 컬럼은 레거시 호환)"""
    uid = _행_값_가져오기(row_data, headers, '사용아이디')
    if not _셀값_비어있음(uid):
        return _사용아이디_일치(uid, 설정_아이디)
    pc = _행_값_가져오기(row_data, headers, 'PC')
    if not _셀값_비어있음(pc):
        return _id_동일(pc, 설정_아이디)
    return False


def _행_예약_상태(row_data, headers):
    """empty | skeleton | partial | ready"""
    지명키워드 = _행_값_가져오기(row_data, headers, '지명키워드')
    사용아이디 = _행_값_가져오기(row_data, headers, '사용아이디')
    pc = _행_값_가져오기(row_data, headers, 'PC')
    if not _셀값_비어있음(지명키워드):
        return 'ready'
    if not _셀값_비어있음(사용아이디):
        for col in ('지명', '키워드', '하나노란', '주제', '서비스'):
            if col in headers and not _셀값_비어있음(_행_값_가져오기(row_data, headers, col)):
                return 'partial'
        return 'skeleton'
    if not _셀값_비어있음(pc):
        for col in ('지명', '키워드', '하나노란', '주제', '서비스'):
            if col in headers and not _셀값_비어있음(_행_값_가져오기(row_data, headers, col)):
                return 'partial'
        return 'skeleton'
    if _행_완전_비어있음(row_data, headers):
        return 'empty'
    return 'partial'


def _행_dict_만들기(row_data, headers):
    d = {}
    for i, h in enumerate(headers):
        d[h] = row_data[i] if i < len(row_data) else ''
    return d


def _지명키워드_시트_읽기():
    """지명키워드 구글시트 전체 읽기 -> (worksheet, all_values, headers)"""
    _키_파일 = resource_path('khon21-534690057aec.json')
    import socket as _sock
    _원래 = _sock.getdefaulttimeout()
    _sock.setdefaulttimeout(20)
    try:
        _scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        _creds = Credentials.from_service_account_file(_키_파일, scopes=_scope)
        _gc = gspread_authorize_with_timeout(_creds)
        _sp = gspread_operation_with_timeout(
            lambda: _gc.open_by_key(지명키워드_구글시트_ID), timeout=20, operation_name="지명키워드 시트 열기")
        _ws = gspread_operation_with_timeout(
            lambda: _sp.sheet1, timeout=10, operation_name="지명키워드 sheet1")
        _all = gspread_operation_with_timeout(
            lambda: _ws.get_all_values(), timeout=20, operation_name="지명키워드 전체 읽기")
        if not _all:
            return _ws, [], []
        return _ws, _all, _all[0]
    finally:
        _sock.setdefaulttimeout(_원래)


def _지명키워드_행_폴더_업데이트(_ws, headers, row_num, 폴더명):
    if '폴더' in headers:
        _col = headers.index('폴더') + 1
    else:
        _col = len(headers) + 1
        gspread_operation_with_timeout(
            lambda: _ws.update_cell(1, _col, '폴더'), timeout=10, operation_name="폴더 헤더 추가")
    gspread_operation_with_timeout(
        lambda: _ws.update_cell(row_num, _col, 폴더명),
        timeout=10, operation_name="폴더 업데이트")
    print(f"지명키워드 시트 폴더 컬럼 업데이트 완료: '{폴더명}' (행 {row_num})")


# ──────────────────────────────────────────────────────────
# 지명키워드 로컬 작업큐 관리 (GID=0 구글시트 대체)
# 파일: _internal/지명키워드_작업큐.json
# ──────────────────────────────────────────────────────────
def _로컬_작업큐_파일_경로():
    return resource_path('지명키워드_작업큐.json')


def _로컬_작업큐_읽기():
    path = _로컬_작업큐_파일_경로()
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"로컬 작업큐 읽기 오류: {e}")
        return []


def _로컬_작업큐_저장(큐):
    path = _로컬_작업큐_파일_경로()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(큐, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"로컬 작업큐 저장 오류: {e}")


def 지명키워드_로컬파일_저장(result_df, 사용_아이디=None):
    """키워드 생성 결과를 로컬 작업큐 파일에 추가 (GID=0 구글시트 대체)"""
    try:
        저장_사용아이디 = str(사용_아이디).strip() if 사용_아이디 else str(result_df.iloc[0].get('사용아이디', '')).strip()
        item = {
            '지명':       str(result_df.iloc[0].get('지명', '')),
            '키워드':     str(result_df.iloc[0].get('키워드', '')),
            '주제':       str(result_df.iloc[0].get('주제', '')),
            '서비스':     str(result_df.iloc[0].get('서비스', '')),
            '지명키워드': str(result_df.iloc[0].get('지명키워드', '')),
            '하나노란':   str(result_df.iloc[0].get('하나노란', '')),
            '사용아이디': 저장_사용아이디,
            '폴더':       '',
            '생성시각':   datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        큐 = _로컬_작업큐_읽기()
        큐.append(item)
        _로컬_작업큐_저장(큐)
        print(f"지명키워드 로컬 작업큐 저장 완료 (사용아이디: {저장_사용아이디}, 지명키워드: {item['지명키워드']})")
        return True
    except Exception as e:
        print(f"지명키워드 로컬 작업큐 저장 오류: {e}")
        return False


def _로컬_작업큐_항목_선택(폴더명, 설정_아이디=None):
    """로컬 작업큐에서 작업 가능한 항목 선택 -> (인덱스, item) 또는 (None, None)"""
    global _현재_스케줄_항목
    전용_목록 = _전용아이디_목록_가져오기() if _공용PC_모드() and not 설정_아이디 else set()
    큐 = _로컬_작업큐_읽기()
    디버그_로그_저장(f"작업큐 항목선택 시작 - 폴더={폴더명}, 설정아이디={설정_아이디}, 큐={len(큐)}건")
    for item in _로컬_스케줄_포스팅_후보_목록(설정_아이디):
        target_uid = item['사용아이디']
        for idx, q_item in enumerate(큐):
            if not q_item.get('지명키워드'):
                continue
            q_uid = q_item.get('사용아이디', '')
            if not _사용아이디_일치(q_uid, target_uid):
                continue
            if _공용PC_모드() and _아이디_전용등록_충돌(q_uid, 전용_목록):
                continue
            q_폴더 = q_item.get('폴더', '')
            if q_폴더 and q_폴더 != 폴더명:
                디버그_로그_저장(f"작업큐 항목 폴더 충돌 - idx={idx}, q_폴더={q_폴더}, 현재폴더={폴더명}")
                continue
            item['포스팅진행중'] = True
            _현재_스케줄_항목 = item
            디버그_로그_저장(f"작업큐 항목 선택 완료 - idx={idx}, 지명키워드={q_item.get('지명키워드')}, 사용아이디={q_uid}")
            _스케줄_시트_동기화_비동기()
            return idx, q_item
    디버그_로그_저장(f"작업큐 항목 없음 - 폴더={폴더명}, 설정아이디={설정_아이디}")
    return None, None


def _로컬_작업큐_폴더_업데이트(idx, 폴더명):
    """작업큐 항목에 폴더명 기록 (현재 PC 선점 표시)"""
    큐 = _로컬_작업큐_읽기()
    if 0 <= idx < len(큐):
        큐[idx]['폴더'] = 폴더명
        _로컬_작업큐_저장(큐)
        print(f"로컬 작업큐 폴더 업데이트: '{폴더명}' (인덱스 {idx})")


def _캐시_설정_로컬(item, idx):
    """로컬 작업큐 항목으로 전역 캐시 설정"""
    global _지명키워드_캐시_df, _지명키워드_작업_행번호
    _col_names = ['지명', '키워드', '주제', '서비스', '지명키워드', '하나노란', '사용아이디', '폴더']
    _row_dict = {c: [item.get(c, '')] for c in _col_names}
    _지명키워드_캐시_df = pd.DataFrame(_row_dict)
    _지명키워드_작업_행번호 = idx
    print(f"지명키워드 로컬 작업큐 읽기 성공: {item}")
    디버그_로그_저장(
        f"캐시설정 - idx={idx}, 지명키워드={item.get('지명키워드')}, "
        f"사용아이디={item.get('사용아이디')}, 하나노란={item.get('하나노란')}, "
        f"생성시각={item.get('생성시각')}"
    )


def _로컬_작업큐_항목_삭제(idx):
    """포스팅 완료 후 로컬 작업큐에서 항목 제거"""
    큐 = _로컬_작업큐_읽기()
    if idx is not None and 0 <= idx < len(큐):
        삭제_항목 = 큐.pop(idx)
        _로컬_작업큐_저장(큐)
        print(f"로컬 작업큐 항목 삭제 완료 (인덱스 {idx}, 지명키워드: {삭제_항목.get('지명키워드', '')})")
        중요_작업_로그_저장(f"포스팅 완료 후 로컬 작업큐 항목 삭제: {삭제_항목.get('지명키워드', '')}")
        시트_행번호 = 삭제_항목.get('작업시트_행번호')
        if 시트_행번호:
            try:
                _지명키워드_작업_시트_행_삭제(시트_행번호)
            except Exception as e:
                print(f"작업시트 행 삭제 오류: {e}")
    else:
        print(f"로컬 작업큐 항목 삭제 건너뜀 (인덱스: {idx})")


def _지명키워드_작업_시트_읽기():
    """GID=1679797725 작업시트 전체 읽기 -> (worksheet, all_values, headers)"""
    _키_파일 = resource_path('khon21-534690057aec.json')
    import socket as _sock
    _원래 = _sock.getdefaulttimeout()
    _sock.setdefaulttimeout(20)
    try:
        _scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        _creds = Credentials.from_service_account_file(_키_파일, scopes=_scope)
        _gc = gspread_authorize_with_timeout(_creds)
        _sp = gspread_operation_with_timeout(
            lambda: _gc.open_by_key(지명키워드_구글시트_ID), timeout=20, operation_name="작업시트 열기")
        _ws = gspread_operation_with_timeout(
            lambda: _sp.get_worksheet_by_id(지명키워드_작업_시트_GID),
            timeout=10, operation_name="작업시트 가져오기")
        _all = gspread_operation_with_timeout(
            lambda: _ws.get_all_values(), timeout=20, operation_name="작업시트 전체 읽기")
        if not _all:
            return _ws, [], []
        return _ws, _all, _all[0]
    finally:
        _sock.setdefaulttimeout(_원래)


def _지명키워드_작업_시트_헤더_보장(ws, headers):
    """작업시트에 폴더 컬럼이 없으면 추가"""
    if '폴더' in headers:
        return headers
    headers = list(headers) + ['폴더']
    gspread_operation_with_timeout(
        lambda: ws.update_cell(1, len(headers), '폴더'),
        timeout=10, operation_name="작업시트 폴더 헤더 추가")
    return headers


def _지명키워드_작업_시트_사용가능_행_찾기(all_values, headers, 사용_아이디, 폴더명):
    """지명키워드가 채워진 등록 작업 중 사용 가능한 행 반환 -> (row_num, row_dict)"""
    candidates = []
    for row_idx in range(1, len(all_values)):
        row_data = all_values[row_idx]
        지명키워드 = _행_값_가져오기(row_data, headers, '지명키워드')
        if _셀값_비어있음(지명키워드):
            continue
        row_uid = _행_값_가져오기(row_data, headers, '사용아이디')
        if 사용_아이디 and not _사용아이디_일치(row_uid, 사용_아이디):
            continue
        비고 = _행_값_가져오기(row_data, headers, '비고')
        비고_값 = str(비고).strip()
        row_폴더 = _행_값_가져오기(row_data, headers, '폴더')
        if 비고_값 == '작업중':
            if row_폴더 != 폴더명:
                continue
        elif 비고_값 == '완료':
            continue
        if not _셀값_비어있음(row_폴더) and row_폴더 != 폴더명:
            continue
        사용_값 = _행_값_가져오기(row_data, headers, '사용')
        try:
            사용_숫자 = float(str(사용_값).strip()) if not _셀값_비어있음(사용_값) else 0
        except ValueError:
            사용_숫자 = 0
        candidates.append((사용_숫자, row_idx + 1, _행_dict_만들기(row_data, headers)))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][1], candidates[0][2]


def _지명키워드_작업_시트_셀_업데이트(ws, headers, row_num, col_name, value):
    if col_name not in headers:
        headers = _지명키워드_작업_시트_헤더_보장(ws, headers) if col_name == '폴더' else headers
        if col_name not in headers:
            return headers
    col_idx = headers.index(col_name) + 1
    gspread_operation_with_timeout(
        lambda r=row_num, c=col_idx, v=value: ws.update_cell(r, c, value),
        timeout=10, operation_name=f"작업시트 {col_name} 업데이트")
    return headers


def _지명키워드_작업_시트_선점(ws, headers, row_num, 폴더명):
    """다른 PC 중복 방지: 비고=작업중 + 폴더 기록"""
    headers = _지명키워드_작업_시트_헤더_보장(ws, headers)
    _지명키워드_작업_시트_셀_업데이트(ws, headers, row_num, '폴더', 폴더명)
    _지명키워드_작업_시트_셀_업데이트(ws, headers, row_num, '비고', '작업중')
    print(f"작업시트 선점: 비고=작업중, 폴더='{폴더명}' (행 {row_num})")


def _지명키워드_작업_시트_행_삭제(row_num):
    """포스팅 완료 후 작업시트에서 해당 행 삭제"""
    ws, all_values, headers = _지명키워드_작업_시트_읽기()
    if not headers or row_num < 2 or row_num > len(all_values):
        return
    gspread_operation_with_timeout(
        lambda: ws.delete_rows(row_num),
        timeout=20, operation_name=f"작업시트 {row_num}행 삭제")
    print(f"작업시트 행 삭제 완료 (행 {row_num})")
    중요_작업_로그_저장(f"작업시트 행 삭제: 행번호={row_num}")


def 지명키워드_작업_시트_로컬큐_저장(row_dict, 사용_아이디=None, 시트_행번호=None):
    """작업시트(GID=1679797725) 행을 로컬 작업큐에 추가"""
    try:
        저장_사용아이디 = str(사용_아이디).strip() if 사용_아이디 else str(row_dict.get('사용아이디', '')).strip()
        지명키워드 = str(row_dict.get('지명키워드', '')).strip()
        if _셀값_비어있음(지명키워드):
            return False
        큐 = _로컬_작업큐_읽기()
        for q in 큐:
            if q.get('작업시트_행번호') == 시트_행번호:
                print(f"작업시트 행 {시트_행번호}는 이미 로컬 작업큐에 있습니다.")
                return True
            if q.get('지명키워드') == 지명키워드 and _사용아이디_일치(q.get('사용아이디', ''), 저장_사용아이디):
                print(f"동일 지명키워드가 이미 로컬 작업큐에 있습니다: {지명키워드}")
                return True
        item = {
            '지명':       str(row_dict.get('지명', '')),
            '키워드':     str(row_dict.get('키워드', '')),
            '주제':       str(row_dict.get('주제', '')),
            '서비스':     str(row_dict.get('서비스', '')),
            '지명키워드': 지명키워드,
            '하나노란':   str(row_dict.get('하나노란', '')),
            '사용아이디': 저장_사용아이디,
            '폴더':       '',
            '생성시각':   datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '작업시트_행번호': 시트_행번호,
        }
        큐.append(item)
        _로컬_작업큐_저장(큐)
        print(f"작업시트 -> 로컬 작업큐 저장 완료 (사용아이디: {저장_사용아이디}, 지명키워드: {지명키워드})")
        return True
    except Exception as e:
        print(f"작업시트 로컬큐 저장 오류: {e}")
        return False


def _예약_시트_작업_가져오기(사용_아이디=None, 스케줄_항목=None):
    """예약시간 도래 시 GID=1679797725 작업시트에서 지명키워드 등록 작업 우선 확인"""
    uid = str(사용_아이디).strip() if 사용_아이디 else None
    if 스케줄_항목 and 스케줄_항목.get('사용아이디'):
        uid = str(스케줄_항목.get('사용아이디')).strip()
    폴더명 = _작업_폴더명()
    try:
        ws, all_values, headers = _지명키워드_작업_시트_읽기()
        if not all_values or len(all_values) < 2:
            디버그_로그_저장(f"작업시트 등록 작업 없음 - 사용아이디={uid}")
            return False
        row_num, row_dict = _지명키워드_작업_시트_사용가능_행_찾기(all_values, headers, uid, 폴더명)
        if row_num is None:
            디버그_로그_저장(f"작업시트 사용 가능 행 없음 - 사용아이디={uid}")
            return False
        _지명키워드_작업_시트_선점(ws, headers, row_num, 폴더명)
        if not 지명키워드_작업_시트_로컬큐_저장(row_dict, uid, row_num):
            return False
        if 스케줄_항목 is not None:
            스케줄_항목['키워드생성됨'] = True
            스케줄_항목['지명키워드'] = row_dict.get('지명키워드', '')
            _스케줄_파일_저장()
            _스케줄_시트_동기화_비동기()
        print(f"작업시트(GID={지명키워드_작업_시트_GID}) 등록 작업 사용: {row_dict.get('지명키워드')}")
        디버그_로그_저장(
            f"작업시트 등록 작업 사용 - 행={row_num}, 지명키워드={row_dict.get('지명키워드')}, 사용아이디={uid}"
        )
        return True
    except Exception as e:
        print(f"작업시트 확인 오류: {e}")
        디버그_로그_저장(f"작업시트 확인 오류: {e}")
        return False


def _지명키워드_행_예약(_ws, headers, all_values, 설정_아이디):
    """빈 행에 사용아이디 기록 (전용 PC 예약 = 설정.사용아이디)"""
    if '사용아이디' not in headers:
        gspread_operation_with_timeout(
            lambda: _ws.update_cell(1, len(headers) + 1, '사용아이디'),
            timeout=10, operation_name="사용아이디 헤더 추가")
        headers = list(headers) + ['사용아이디']

    uid_col = headers.index('사용아이디') + 1
    예약_id = _id_정규화(설정_아이디) or str(설정_아이디).strip()

    for row_idx in range(1, len(all_values)):
        row_data = all_values[row_idx]
        if _행_예약_상태(row_data, headers) == 'empty':
            gspread_operation_with_timeout(
                lambda r=row_idx + 1, c=uid_col, v=예약_id: _ws.update_cell(r, c, v),
                timeout=10, operation_name="사용아이디 예약")
            print(f"빈 행 {row_idx + 1}에 사용아이디 '{예약_id}' 예약 완료")
            return row_idx + 1

    new_row_num = len(all_values) + 1
    new_row = [''] * len(headers)
    new_row[headers.index('사용아이디')] = 예약_id
    end_col = _컬럼_글자(len(headers))
    _시트_범위_업데이트(
        _ws, f'A{new_row_num}:{end_col}{new_row_num}', [new_row],
        timeout=20, operation_name="사용아이디 예약 행 추가")
    print(f"새 행 {new_row_num}에 사용아이디 '{예약_id}' 예약 완료")
    return new_row_num


def _캐시_설정(row_data, headers, row_num):
    global _지명키워드_캐시_df, _지명키워드_작업_행번호
    _row_dict = {h: [(_행_값_가져오기(row_data, headers, h))] for h in headers}
    _지명키워드_캐시_df = pd.DataFrame(_row_dict)
    _지명키워드_작업_행번호 = row_num
    print(f"지명키워드 구글시트 읽기 성공: {_지명키워드_캐시_df.to_dict('records')}")


def _예약시간_파싱(값):
    if _셀값_비어있음(값):
        return None
    s = str(값).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M:%S', '%Y/%m/%d %H:%M'):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.datetime.fromisoformat(s.replace('T', ' ')[:19])
    except ValueError:
        return None


def _예약시간_도래(예약시간_값):
    """예약시간이 없거나 현재 시각 이전/같으면 True"""
    if _셀값_비어있음(예약시간_값):
        return True
    dt = _예약시간_파싱(예약시간_값)
    if dt is None:
        return True
    return dt <= datetime.datetime.now()


def _스케줄_일일_10시_창(now=None):
    """매일 01:00 기준 현재 스케줄 주기 (시작 01:00 ~ 다음날 01:00)"""
    now = now or datetime.datetime.now()
    today_1 = now.replace(hour=1, minute=0, second=0, microsecond=0)
    if now < today_1:
        return today_1 - datetime.timedelta(days=1), today_1
    return today_1, today_1 + datetime.timedelta(days=1)


def _스케줄_계획_금지시간(now=None):
    """매일 23:00~01:00 사이면 스케줄 계획/배치 금지"""
    now = now or datetime.datetime.now()
    t = now.time()
    return t >= datetime.time(23, 0) or t < datetime.time(1, 0)


def _예약시간_09_10_금지(dt):
    """어느 날이든 23:00~01:00 구간이면 True"""
    t = dt.time()
    return t >= datetime.time(23, 0) or t < datetime.time(1, 0)


def _스케줄_예약_당일_끝(기준_시작):
    """스케줄 주기 시작일 달력 기준 예약 배치 마감 (23시 전, 다음날 배치 금지)"""
    d = 기준_시작.date()
    return datetime.datetime(d.year, d.month, d.day, 22, 59, 59)


def _예약시간_09_10_건너뛰기(dt, 예약_당일=None):
    """23~01 구간이면 다음 01:00으로 이동. 예약_당일 지정 시 그날을 넘기지 않음"""
    if not _예약시간_09_10_금지(dt):
        return dt
    bumped = dt.replace(hour=1, minute=0, second=0, microsecond=0)
    if bumped <= dt:
        bumped += datetime.timedelta(days=1)
        bumped = bumped.replace(hour=1, minute=0, second=0, microsecond=0)
    if 예약_당일 is not None and bumped.date() > 예약_당일:
        return dt
    return bumped


def _스케줄_주기_갱신_확인():
    """1시 주기 종료 또는 23시~1시 이후 미계획 시 스케줄 재수립"""
    global _스케줄_자정대기
    if _스케줄_계획_금지시간():
        return False
    now = datetime.datetime.now()
    if _스케줄_창_끝 and now >= _스케줄_창_끝:
        print(f"\n스케줄 주기 종료 ({_스케줄_창_끝.strftime('%Y-%m-%d %H:%M')}) - 새 스케줄 계획")
        _작업스케줄_로컬_계획()
        return True
    if _스케줄_자정대기:
        _스케줄_자정대기 = False
        _작업스케줄_로컬_계획()
        return True
    return False


def _발행시간고정_창_목록(기준_날짜):
    """발행시간고정=1 일 때 허용 시간 창 목록 반환: 10~14시, 18~22시"""
    d = 기준_날짜.date()
    return [
        (datetime.datetime(d.year, d.month, d.day, 10, 0, 0),
         datetime.datetime(d.year, d.month, d.day, 14, 0, 0)),
        (datetime.datetime(d.year, d.month, d.day, 18, 0, 0),
         datetime.datetime(d.year, d.month, d.day, 22, 0, 0)),
    ]


def _발행시간고정_허용(candidate):
    """발행시간고정=1 일 때 candidate 시각이 허용 창(10~14, 18~22) 안에 있으면 True"""
    t = candidate.time()
    return (
        datetime.time(10, 0) <= t < datetime.time(14, 0) or
        datetime.time(18, 0) <= t < datetime.time(22, 0)
    )


def _발행시간고정_다음_창_시작(candidate, 예약_당일=None):
    """발행시간고정=1 일 때 candidate 이후 가장 가까운 허용 창 시작 시각 반환"""
    창_목록 = list(_발행시간고정_창_목록(candidate))
    if 예약_당일 is None:
        이튿날 = candidate + datetime.timedelta(days=1)
        창_목록 += _발행시간고정_창_목록(이튿날)
    elif candidate.date() < 예약_당일:
        창_목록 += _발행시간고정_창_목록(
            datetime.datetime.combine(예약_당일, datetime.time(0)))
    for 창_시작, _ in sorted(창_목록):
        if 예약_당일 is not None and 창_시작.date() > 예약_당일:
            continue
        if 창_시작 > candidate:
            return 창_시작
    return candidate


def _스케줄_PC_변칙_분():
    """PC/직원 폴더별 고정 분 오프셋 (-75~+75, 5분 단위). 다른 PC와 목표 시각 분산."""
    global _스케줄_PC_변칙_분_캐시
    if _스케줄_PC_변칙_분_캐시 is not None:
        return _스케줄_PC_변칙_분_캐시
    pc_name = os.environ.get('COMPUTERNAME', '') or os.environ.get('HOSTNAME', '')
    key = f'{pc_name}|{_앱_루트_경로()}'
    h = int(hashlib.md5(key.encode('utf-8')).hexdigest()[:8], 16)
    _스케줄_PC_변칙_분_캐시 = ((h % 31) - 15) * 5
    return _스케줄_PC_변칙_분_캐시


def _24시간_랜덤_예약시간_생성(
    개수, 기준=None, 기존_예약=None, 전체_예약=None,
    목표_오프셋=0, 목표_전체=None, 아이디=None, id_df=None,
):
    """매일 1시 주기 안 랜덤 예약시간 생성
    - 동일 아이디(기존_예약): 6시간 간격 (전 PC 공통)
    - 같은 PC 내 아이디 간(전체_예약): 1시간 30분 간격 (공용 PC는 자기 PC 예약만)
    - 23~01시 배치 제외
    - 주기 시작일 달력 기준 당일 22:59까지 (다음날 배치 금지)
    - 목표_전체 지정 시 당일 창 안 작업을 고르게 분포 (앞쪽 몰림 방지)
    - PC별 고정 분 오프셋 + 슬롯당 0~8분/초 랜덤으로 다른 PC 예약시간 겹침 완화
    - 아이디/id_df 지정 시 로그인금지시간대 밖 슬롯만 배치
    """
    if 개수 <= 0:
        return []
    now = 기준 or datetime.datetime.now()
    일일_시작, 일일_끝 = _스케줄_일일_10시_창(now)
    예약_당일 = 일일_시작.date()
    창_시작 = max(now + datetime.timedelta(minutes=1), 일일_시작)
    창_끝 = min(일일_끝, _스케줄_예약_당일_끝(일일_시작))
    같은아이디_간격 = datetime.timedelta(hours=6)
    전체_간격 = datetime.timedelta(hours=1, minutes=30)
    발행고정 = (설정_발행시간고정 == 1)

    same_occupied = sorted(기존_예약 or [])
    all_occupied = sorted(t for t in (전체_예약 or []) if t >= now)

    def _배치_가능(candidate):
        if candidate < 창_시작 or candidate > 창_끝:
            return False
        if candidate.date() != 예약_당일:
            return False
        if _예약시간_09_10_금지(candidate):
            return False
        if 발행고정 and not _발행시간고정_허용(candidate):
            return False
        if not all(abs((candidate - t).total_seconds()) >= 같은아이디_간격.total_seconds() for t in same_occupied):
            return False
        if not all(abs((candidate - t).total_seconds()) >= 전체_간격.total_seconds() for t in all_occupied):
            return False
        if 아이디 and id_df is not None and not _로그인금지시간대_허용(아이디, id_df, candidate):
            return False
        return True

    def _모든_유효_슬롯():
        """당일 창 안 10분 단위 전수 탐색"""
        result = []
        candidate = 창_시작
        while candidate <= 창_끝:
            if _배치_가능(candidate):
                result.append(candidate)
            candidate += datetime.timedelta(minutes=10)
            if _예약시간_09_10_금지(candidate):
                break
            candidate = _예약시간_09_10_건너뛰기(candidate, 예약_당일)
            if 발행고정 and not _발행시간고정_허용(candidate):
                candidate = _발행시간고정_다음_창_시작(candidate, 예약_당일)
        return result

    def _보완_우선_슬롯(유효_목록):
        """다른 PC same-ID t+6h 보완 시각 우선, 이후 t+6h 이후 슬롯"""
        if not 유효_목록:
            return []
        유효_set = set(유효_목록)
        ordered = []
        seen = set()
        for t in same_occupied:
            for cand in (t + 같은아이디_간격, t - 같은아이디_간격):
                if cand in 유효_set and cand not in seen:
                    ordered.append(cand)
                    seen.add(cand)
        if same_occupied:
            min_after = max(t + 같은아이디_간격 for t in same_occupied)
            for s in sorted(유효_목록):
                if s not in seen and s >= min_after:
                    ordered.append(s)
                    seen.add(s)
        for s in sorted(유효_목록):
            if s not in seen:
                ordered.append(s)
        return ordered

    new_times = []
    total_slots = 목표_전체 if 목표_전체 and 목표_전체 > 0 else 개수
    for _ in range(개수):
        유효 = _모든_유효_슬롯()
        if not 유효:
            break
        placement_idx = (목표_오프셋 or 0) + len(new_times)
        target = 창_시작 + (창_끝 - 창_시작) * (placement_idx + 0.5) / total_slots
        target = target + datetime.timedelta(
            minutes=_스케줄_PC_변칙_분() + random.randint(0, 8),
            seconds=random.randint(0, 59),
        )
        ordered = _보완_우선_슬롯(유효)
        if ordered:
            placed = min(ordered, key=lambda t: abs((t - target).total_seconds()))
        else:
            placed = None
        if placed is None:
            break
        same_occupied.append(placed)
        all_occupied.append(placed)
        new_times.append(placed)

    return [t.strftime('%Y-%m-%d %H:%M:%S') for t in sorted(new_times)]


def _스케줄_당일_유효_슬롯_개수(기존_예약=None, 전체_예약=None, 기준=None, 아이디=None, id_df=None):
    """당일 창 안 1.5h/6h/로그인금지 규칙을 만족하는 10분 슬롯 개수 (재계획 판단용)"""
    if 기준 is None:
        기준 = datetime.datetime.now()
    now = 기준
    일일_시작, 일일_끝 = _스케줄_일일_10시_창(now)
    예약_당일 = 일일_시작.date()
    창_시작 = max(now + datetime.timedelta(minutes=1), 일일_시작)
    창_끝 = min(일일_끝, _스케줄_예약_당일_끝(일일_시작))
    같은아이디_간격 = datetime.timedelta(hours=6)
    전체_간격 = datetime.timedelta(hours=1, minutes=30)
    발행고정 = (설정_발행시간고정 == 1)
    same_occupied = sorted(기존_예약 or [])
    all_occupied = sorted(t for t in (전체_예약 or []) if t >= now)
    count = 0
    candidate = 창_시작
    while candidate <= 창_끝:
        ok = (
            candidate.date() == 예약_당일
            and not _예약시간_09_10_금지(candidate)
            and (not 발행고정 or _발행시간고정_허용(candidate))
            and all(abs((candidate - t).total_seconds()) >= 같은아이디_간격.total_seconds() for t in same_occupied)
            and all(abs((candidate - t).total_seconds()) >= 전체_간격.total_seconds() for t in all_occupied)
            and (not 아이디 or id_df is None or _로그인금지시간대_허용(아이디, id_df, candidate))
        )
        if ok:
            count += 1
        candidate += datetime.timedelta(minutes=10)
        if _예약시간_09_10_금지(candidate):
            break
        candidate = _예약시간_09_10_건너뛰기(candidate, 예약_당일)
        if 발행고정 and not _발행시간고정_허용(candidate):
            candidate = _발행시간고정_다음_창_시작(candidate, 예약_당일)
    return count


def _스케줄_작업_교차_펼치기(계획_대상):
    """아이디별 등록 건수를 라운드로빈으로 펼쳐 당일 시간 균등 분포에 유리하게 함"""
    buckets = []
    for _, _, 아이디, _, 등록_건수 in 계획_대상:
        if 등록_건수 > 0:
            buckets.append([아이디] * 등록_건수)
    if not buckets:
        return []
    result = []
    max_len = max(len(b) for b in buckets)
    for i in range(max_len):
        for bucket in buckets:
            if i < len(bucket):
                result.append(bucket[i])
    return result


def _스케줄_계획_불가_사유(아이디, 기존_예약, 전체_예약, 창_끝, id_df=None):
    """보완 실패 시 콘솔용 사유 문자열"""
    ref = list(기존_예약 or [])
    if not ref:
        if _스케줄_당일_유효_슬롯_개수(기존_예약=[], 전체_예약=전체_예약, 아이디=아이디, id_df=id_df) <= 0:
            return "당일 빈 슬롯 없음 (로그인금지/1.5h/마감 제한, 5분마다 자동 재계획)"
        return "1시간 30분 간격 제한으로 계획 불가 (같은 PC 내)"
    최소_6h = max(ref) + datetime.timedelta(hours=6)
    if 최소_6h > 창_끝:
        return (
            f"당일 보완 불가 (같은아이디 6h: {최소_6h.strftime('%H:%M')} 필요, "
            f"마감 {창_끝.strftime('%H:%M')})"
        )
    blockers = []
    for t in sorted(전체_예약 or []):
        if t >= datetime.datetime.now() and abs((최소_6h - t).total_seconds()) < 90 * 60:
            blockers.append(t.strftime('%H:%M'))
    if blockers:
        return (
            f"보완 불가 (같은아이디 6h: {최소_6h.strftime('%H:%M')} 필요, "
            f"이 PC 예약 {', '.join(blockers)} 과 1.5h 간격)"
        )
    return (
        f"보완 불가 (같은아이디 6h: {최소_6h.strftime('%H:%M')} 이후 필요, "
        f"이 PC 1.5h 간격 충돌)"
    )


def _작업스케줄_기존_예약시간_목록(all_values, headers, 아이디):
    """해당 아이디 미완료(skeleton/ready) 행의 예약시간 datetime 목록"""
    now = datetime.datetime.now()
    result = []
    for row_idx in range(1, len(all_values)):
        row_data = all_values[row_idx]
        if _행_예약_상태(row_data, headers) not in ('skeleton', 'ready'):
            continue
        row_uid = _행_값_가져오기(row_data, headers, '사용아이디')
        if not _사용아이디_일치(row_uid, 아이디):
            continue
        dt = _예약시간_파싱(_행_값_가져오기(row_data, headers, '예약시간'))
        if dt is None:
            continue
        if dt < now - datetime.timedelta(hours=24):
            continue
        result.append(dt)
    return result


def _작업스케줄_등록된_미완료_개수(all_values, headers, 아이디):
    """작업스케줄 시트에서 해당 아이디의 미완료(skeleton) 등록 건수"""
    now = datetime.datetime.now()
    cnt = 0
    for row_idx in range(1, len(all_values)):
        row_data = all_values[row_idx]
        if _행_예약_상태(row_data, headers) != 'skeleton':
            continue
        row_uid = _행_값_가져오기(row_data, headers, '사용아이디')
        if not _사용아이디_일치(row_uid, 아이디):
            continue
        예약 = _행_값_가져오기(row_data, headers, '예약시간')
        if not _셀값_비어있음(예약):
            dt = _예약시간_파싱(예약)
            if dt and dt < now - datetime.timedelta(hours=24):
                continue
        cnt += 1
    return cnt


def _작업스케줄_행_일괄_추가(_ws, headers, all_values, new_rows):
    if not new_rows:
        return
    start_row = len(all_values) + 1
    end_row = start_row + len(new_rows) - 1
    end_col = _컬럼_글자(len(headers))
    range_name = f'A{start_row}:{end_col}{end_row}'
    _시트_범위_업데이트(_ws, range_name, new_rows, timeout=30, operation_name="작업스케줄 일괄 등록")


def _작업스케줄_로컬_계획():
    """하루최대포스팅수>0 아이디의 오늘 예약 계획을 메모리에만 저장하고 콘솔에 출력 (시트 기록 없음)"""
    global _로컬_작업_스케줄, _스케줄_창_끝, _스케줄_자정대기
    print("\n=== 오늘 작업 스케줄 (콘솔 전용, 시트 미기록) ===")

    if _스케줄_계획_금지시간():
        print("23시~1시 구간 - 스케줄 계획 생략 (1시 이후 자동 재계획)")
        _로컬_작업_스케줄 = []
        _스케줄_자정대기 = True
        _, _스케줄_창_끝 = _스케줄_일일_10시_창()
        return []

    _스케줄_자정대기 = False

    창_시작, 창_끝 = _스케줄_일일_10시_창()
    _스케줄_창_끝 = 창_끝
    예약_마감 = _스케줄_예약_당일_끝(창_시작)
    print(
        f"스케줄 주기: {창_시작.strftime('%Y-%m-%d %H:%M')} ~ {창_끝.strftime('%Y-%m-%d %H:%M')} "
        f"(매일 1시 기준, 예약은 {예약_마감.strftime('%Y-%m-%d %H:%M')}까지, 23시~1시 배치 제외)"
    )
    print(f"  PC 예약 변칙: {_스케줄_PC_변칙_분():+d}분 고정 + 슬롯당 0~8분/초 랜덤")
    id_df = 구글스프레드시트_계정정보_가져오기()
    if id_df.empty or '아이디' not in id_df.columns:
        print("계정정보를 가져올 수 없어 스케줄 계획을 건너뜁니다.")
        _로컬_작업_스케줄 = []
        return []

    if '하루최대포스팅수' not in id_df.columns:
        id_df['하루최대포스팅수'] = 3
    if '포스팅수' not in id_df.columns:
        id_df['포스팅수'] = 0

    id_df = id_df.copy()
    id_df['하루최대포스팅수'] = pd.to_numeric(id_df['하루최대포스팅수'], errors='coerce').fillna(0).astype(int)
    id_df['포스팅수'] = pd.to_numeric(id_df['포스팅수'], errors='coerce').fillna(0).astype(int)
    eligible = id_df[id_df['하루최대포스팅수'] > 0]

    전용 = bool(설정_사용아이디) and str(설정_사용아이디).strip() != '*'
    if 전용:
        설정_uid = str(설정_사용아이디).strip()
        사용아이디_목록 = [x.strip() for x in 설정_uid.split(',') if x.strip()]
        eligible = eligible[eligible['아이디'].isin(사용아이디_목록)]
        print(f"전용 PC 모드: '{설정_uid}' 아이디만 스케줄 계획 ({len(eligible)}개)")
    else:
        print(f"하루최대포스팅수>0 아이디 {len(eligible)}개")

    if eligible.empty:
        print("계획 대상 아이디가 없습니다.")
        _로컬_작업_스케줄 = []
        return []

    전용_목록 = _전용아이디_목록_가져오기() if _공용PC_모드() else set()
    if _공용PC_모드() and 전용_목록:
        print(f"  공용 PC: 시트2 전용아이디 {len(전용_목록)}개 스케줄/작업 제외")

    schedule = []
    전체_예약시간 = []  # 이 PC에서 배치한 아이디 간 1.5h 간격용 (다른 PC와는 무관)
    아이디별_예약시간 = {}  # 동일 아이디 6시간 간격 보장용 (전 PC 시트 참조)
    다른PC_미완료_건수 = {}
    if _공용PC_모드():
        print("  공용 PC: 시트 다른 PC 예약 확인 후 빈 슬롯 보완 배치 (PC 간 1.5h 미적용)")
        _, 시트_아이디별_6h, 다른PC_미완료_건수 = _스케줄_시트_공용_참조_읽기(창_시작, 창_끝)
        for uid, times in 시트_아이디별_6h.items():
            아이디별_예약시간.setdefault(uid, []).extend(times)

    계획_대상 = []
    for _, acc in eligible.iterrows():
        아이디 = str(acc['아이디']).strip()
        if _셀값_비어있음(아이디):
            print("  (공란): 스킵 (계정정보 시트에 아이디 없음)")
            continue
        if _공용PC_모드() and _아이디_전용등록_충돌(아이디, 전용_목록):
            print(f"  {아이디}: 스킵 (전용 PC 등록 ID)")
            continue
        하루_최대 = int(acc['하루최대포스팅수'])
        포스팅수 = int(acc['포스팅수'])
        등록_건수 = max(0, 하루_최대 - 포스팅수)
        if _공용PC_모드():
            등록_건수 = max(0, 등록_건수 - 다른PC_미완료_건수.get(아이디, 0))
        if 등록_건수 <= 0:
            if _공용PC_모드() and 다른PC_미완료_건수.get(아이디, 0) > 0 and 포스팅수 < 하루_최대:
                print(f"  {아이디}: 스킵 (다른 PC 미완료 {다른PC_미완료_건수[아이디]}건)")
            else:
                print(f"  {아이디}: 스킵 (최대 {하루_최대}, 완료 {포스팅수})")
            continue
        타PC_미완료 = 다른PC_미완료_건수.get(아이디, 0) if _공용PC_모드() else 0
        ref6 = len(아이디별_예약시간.get(아이디, []))
        계획_대상.append((타PC_미완료, ref6, 아이디, acc, 등록_건수))
    # 다른 PC 미배정·6h 제약 적은 아이디 먼저 배치해 빈 슬롯 최대 활용
    계획_대상.sort(key=lambda x: (x[0], x[1], x[2]))

    total_tasks = sum(x[4] for x in 계획_대상)
    균등_분포 = total_tasks > 0 and total_tasks <= _스케줄_균등_분포_임계값
    if 균등_분포:
        print(f"  당일 작업 {total_tasks}건 - 남은 시간에 고르게 분포 배치")

    if 균등_분포:
        flat_uids = _스케줄_작업_교차_펼치기(계획_대상)
        batch_아이디별 = {uid: list(아이디별_예약시간.get(uid, [])) for uid in {u for u in flat_uids}}
        batch_전체 = list(전체_예약시간)
        global_idx = 0
        for uid in flat_uids:
            예약_목록 = _24시간_랜덤_예약시간_생성(
                1,
                기존_예약=list(batch_아이디별.get(uid, [])),
                전체_예약=list(batch_전체),
                목표_오프셋=global_idx,
                목표_전체=total_tasks,
                아이디=uid,
                id_df=id_df,
            )
            global_idx += 1
            if not 예약_목록:
                배치_끝 = min(창_끝, _스케줄_예약_당일_끝(창_시작))
                사유 = _스케줄_계획_불가_사유(
                    uid,
                    list(batch_아이디별.get(uid, [])),
                    list(batch_전체),
                    배치_끝,
                    id_df=id_df,
                )
                print(f"  {uid}: {사유}")
                continue
            예약 = 예약_목록[0]
            dt = _예약시간_파싱(예약) or datetime.datetime.now()
            batch_전체.append(dt)
            batch_아이디별.setdefault(uid, []).append(dt)
            print(f"  {uid}: 균등 1건 -> {예약}")
            schedule.append({
                '사용아이디': uid,
                '예약시간': dt,
                '예약시간_str': 예약,
                '키워드생성됨': False,
                '포스팅진행중': False,
                '포스팅완료': False,
            })
    else:
        for _, _, 아이디, acc, 등록_건수 in 계획_대상:
            예약_목록 = _24시간_랜덤_예약시간_생성(
                등록_건수,
                기존_예약=list(아이디별_예약시간.get(아이디, [])),
                전체_예약=list(전체_예약시간),
                아이디=아이디,
                id_df=id_df,
            )
            if not 예약_목록 and 등록_건수 > 1:
                for n in range(등록_건수 - 1, 0, -1):
                    예약_목록 = _24시간_랜덤_예약시간_생성(
                        n,
                        기존_예약=list(아이디별_예약시간.get(아이디, [])),
                        전체_예약=list(전체_예약시간),
                        아이디=아이디,
                        id_df=id_df,
                    )
                    if 예약_목록:
                        print(f"  {아이디}: {등록_건수}건 요청 -> {len(예약_목록)}건만 배치")
                        break
            if not 예약_목록:
                배치_끝 = min(창_끝, _스케줄_예약_당일_끝(창_시작))
                사유 = _스케줄_계획_불가_사유(
                    아이디,
                    list(아이디별_예약시간.get(아이디, [])),
                    list(전체_예약시간),
                    배치_끝,
                    id_df=id_df,
                )
                print(f"  {아이디}: {사유}")
                continue

            print(f"  {아이디}: 보완 {len(예약_목록)}건 -> {', '.join(예약_목록)}")
            for 예약 in 예약_목록:
                dt = _예약시간_파싱(예약) or datetime.datetime.now()
                전체_예약시간.append(dt)
                아이디별_예약시간.setdefault(아이디, []).append(dt)
                schedule.append({
                    '사용아이디': 아이디,
                    '예약시간': dt,
                    '예약시간_str': 예약,
                    '키워드생성됨': False,
                    '포스팅진행중': False,
                    '포스팅완료': False,
                })

    schedule.sort(key=lambda x: x['예약시간'])
    _로컬_작업_스케줄 = schedule
    if _공용PC_모드() and not schedule:
        print("  공용 PC: 현재 당일 배치 불가 - 5분마다 빈 슬롯 재탐색")
    대상 = str(설정_사용아이디).strip() if (설정_사용아이디 and str(설정_사용아이디).strip() != '*') else None
    _로컬_스케줄_현황_출력(대상)
    _스케줄_파일_저장()
    _스케줄_시트_동기화_비동기(지연_초=0)  # 스케줄 생성 시 즉시 기록
    return schedule


def _공용PC_스케줄_재계획_필요():
    """공용 PC에서 로컬 미완료 예약이 없으면 재계획 대상"""
    if not _공용PC_모드() or _스케줄_계획_금지시간():
        return False
    if not _로컬_작업_스케줄:
        return True
    미완료 = [
        s for s in _로컬_작업_스케줄
        if not s.get('포스팅완료') and not s.get('포스팅진행중')
    ]
    return len(미완료) == 0


def _공용PC_스케줄_재계획_시도():
    """다른 PC 예약이 지나가며 빈 슬롯이 생기면 주기적으로 재계획"""
    global _마지막_공용_스케줄_재계획
    if not _공용PC_스케줄_재계획_필요():
        return False
    now = datetime.datetime.now()
    if _마지막_공용_스케줄_재계획 is not None:
        if (now - _마지막_공용_스케줄_재계획).total_seconds() < _공용_스케줄_재계획_간격_초:
            return False
    print("\n공용 PC: 다른 PC 예약 변동 반영 - 빈 슬롯 재탐색")
    _마지막_공용_스케줄_재계획 = now
    _작업스케줄_로컬_계획()
    return bool(_로컬_작업_스케줄)


_스케줄_시트_헤더 = ['사용아이디', '예약시간', '상태', '지명키워드', '폴더', '업데이트시각']


def _스케줄_시트_공용_참조_읽기(창_시작, 창_끝):
    """공용 PC 스케줄 계획용: GID=0 시트 참조 (시간 규칙 기반, 아이디 독점 없음)

    Returns:
        (미사용_예약목록, 아이디별_6h_참조, 다른PC_미완료_건수)
        - 미사용_예약목록: 항상 [] (PC 간 1.5h 간격 미적용, 호환용)
        - 아이디별_6h_참조: 전 PC, 창_시작-6h~배치끝, 완료 포함 (같은 아이디 6h 간격용)
        - 다른PC_미완료_건수: 다른 PC 미완료 건수 (하루최대 차감용)
        실패 시 ([], {}, {})
    """
    import socket as _sock
    원래 = _sock.getdefaulttimeout()
    현재_폴더 = os.path.basename(os.getcwd())
    아이디별_6h_참조 = {}
    다른PC_미완료_건수 = {}
    try:
        _sock.setdefaulttimeout(30)
        키_파일 = resource_path('khon21-534690057aec.json')
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(키_파일, scopes=scope)
        gc = gspread_authorize_with_timeout(creds)
        sp = gspread_operation_with_timeout(
            lambda: gc.open_by_key(지명키워드_구글시트_ID),
            timeout=20, operation_name="공용 스케줄 참조 시트 열기")
        ws = gspread_operation_with_timeout(
            lambda: sp.sheet1, timeout=10, operation_name="공용 스케줄 참조 sheet1")
        existing = gspread_operation_with_timeout(
            lambda: ws.get_all_values(), timeout=20, operation_name="공용 스케줄 참조 읽기")
        if not existing or existing[0] != _스케줄_시트_헤더:
            return [], 아이디별_6h_참조, 다른PC_미완료_건수

        headers = existing[0]
        uid_i = headers.index('사용아이디')
        time_i = headers.index('예약시간')
        status_i = headers.index('상태')
        folder_i = headers.index('폴더')
        예약_당일 = 창_시작.date()
        now = datetime.datetime.now()
        lookback_시작 = 창_시작 - datetime.timedelta(hours=6)
        배치_끝 = min(창_끝, _스케줄_예약_당일_끝(창_시작))
        다른PC_표시 = []

        for row in existing[1:]:
            if len(row) <= max(uid_i, time_i, status_i, folder_i):
                continue
            folder = str(row[folder_i]).strip()
            if not folder:
                continue
            uid = str(row[uid_i]).strip()
            if not uid:
                continue
            dt = _예약시간_파싱(row[time_i])
            if dt is None:
                continue
            status = str(row[status_i]).strip()

            if lookback_시작 <= dt <= 배치_끝:
                if folder == 현재_폴더 and status != '완료':
                    pass
                else:
                    아이디별_6h_참조.setdefault(uid, []).append(dt)

            if folder == 현재_폴더:
                continue

            if dt < 창_시작 or dt > 배치_끝 or dt.date() != 예약_당일:
                continue
            if status == '완료':
                continue
            다른PC_미완료_건수[uid] = 다른PC_미완료_건수.get(uid, 0) + 1
            다른PC_표시.append((dt, uid, folder, status))

        if 다른PC_표시:
            print("  [다른 PC 시트 예약] 이 PC에서 보완 배치 (6h만 공유, 1.5h는 PC별)")
            for dt, uid, folder, status in sorted(다른PC_표시, key=lambda x: x[0]):
                print(f"    {dt.strftime('%H:%M')} {uid} ({folder}) [{status}]")

        ref_6h = sum(len(v) for v in 아이디별_6h_참조.values())
        if 다른PC_표시 or ref_6h or 다른PC_미완료_건수:
            print(
                f"  공용 PC: 시트 참조 - 다른 PC 예약 {len(다른PC_표시)}건, "
                f"6h 참조 {ref_6h}건, 다른 PC 미완료 {sum(다른PC_미완료_건수.values())}건"
            )
        return [], 아이디별_6h_참조, 다른PC_미완료_건수
    except Exception as e:
        print(f"  공용 PC: 시트 참조 실패 (로컬만 계획): {e}")
        return [], {}, {}
    finally:
        _sock.setdefaulttimeout(원래)


_스케줄_파일_경로 = None


def _스케줄_파일_저장():
    """현재 _로컬_작업_스케줄을 _internal/스케줄.json에 저장"""
    try:
        path = resource_path('스케줄.json')
        import json as _json
        창_시작, 창_끝 = _스케줄_일일_10시_창()
        data = {
            '창_시작': 창_시작.strftime('%Y-%m-%d %H:%M:%S'),
            '창_끝': 창_끝.strftime('%Y-%m-%d %H:%M:%S'),
            '항목': [
                {
                    '사용아이디': item['사용아이디'],
                    '예약시간_str': item['예약시간_str'],
                    '키워드생성됨': item.get('키워드생성됨', False),
                    '포스팅진행중': False,
                    '포스팅완료': item.get('포스팅완료', False),
                }
                for item in _로컬_작업_스케줄
            ]
        }
        with open(path, 'w', encoding='utf-8') as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [스케줄 저장 오류] {e}")


# ──────────────────────────────────────────────────────────
# 스케줄 진행 현황 구글시트(GID=0) 동기화
# ──────────────────────────────────────────────────────────
def _스케줄_시트_동기화():
    """로컬 작업 스케줄을 구글시트(GID=0)에 동기화 - 이 PC 폴더 행만 갱신, 다른 PC 행 유지"""
    if not _로컬_작업_스케줄:
        return
    import socket as _sock
    원래 = _sock.getdefaulttimeout()
    try:
        _sock.setdefaulttimeout(30)
        키_파일 = resource_path('khon21-534690057aec.json')
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(키_파일, scopes=scope)
        gc = gspread_authorize_with_timeout(creds)
        sp = gspread_operation_with_timeout(
            lambda: gc.open_by_key(지명키워드_구글시트_ID),
            timeout=20, operation_name="스케줄 시트 열기")
        ws = gspread_operation_with_timeout(
            lambda: sp.sheet1, timeout=10, operation_name="스케줄 sheet1")

        headers = _스케줄_시트_헤더
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        현재_폴더 = os.path.basename(os.getcwd())

        # 이 PC의 새 행 생성
        내_행 = []
        for item in sorted(_로컬_작업_스케줄, key=lambda x: x['예약시간']):
            if item.get('포스팅완료'):
                상태 = '완료'
            elif item.get('포스팅진행중'):
                상태 = '포스팅중'
            elif item.get('키워드생성됨'):
                상태 = '키워드생성완료'
            else:
                상태 = '대기중'
            내_행.append([
                item['사용아이디'],
                item['예약시간_str'],
                상태,
                item.get('지명키워드', ''),
                현재_폴더,
                now_str,
            ])

        # 현재 시트 읽기
        existing = gspread_operation_with_timeout(
            lambda: ws.get_all_values(), timeout=20, operation_name="스케줄 시트 읽기")

        if not existing or existing[0] != _스케줄_시트_헤더:
            # 헤더 없거나 컬럼 구조 다름 -> 전체 초기화
            다른PC_행 = []
        else:
            폴더_idx = headers.index('폴더')
            다른PC_행 = [
                row for row in existing[1:]
                if len(row) > 폴더_idx and row[폴더_idx] != 현재_폴더
            ]

        all_rows = [headers] + 다른PC_행 + 내_행
        gspread_operation_with_timeout(
            lambda: ws.clear(), timeout=20, operation_name="스케줄 시트 초기화")
        gspread_operation_with_timeout(
            lambda: ws.batch_update(
                [{'range': 'A1', 'values': all_rows}],
                value_input_option='USER_ENTERED'
            ),
            timeout=30, operation_name="스케줄 시트 업데이트")
        print(f"스케줄 시트 동기화 완료: 이 PC {len(내_행)}건 / 전체 {len(all_rows) - 1}건 (폴더: {현재_폴더})")
    except Exception as e:
        print(f"스케줄 시트 동기화 오류: {e}")
    finally:
        _sock.setdefaulttimeout(원래)


def _스케줄_시트_동기화_비동기(지연_초=None):
    """스케줄 시트 동기화를 백그라운드 스레드에서 실행 (메인 흐름 비차단)
    - 지연_초=None: 0~600초 랜덤 지연 (동시 쓰기 충돌 방지)
    - 지연_초=0: 즉시 실행 (프로그램 시작 시 등)
    """
    def _지연_후_동기화():
        지연 = random.randint(0, 600) if 지연_초 is None else 지연_초
        if 지연 > 0:
            time.sleep(지연)
        _스케줄_시트_동기화()
    threading.Thread(target=_지연_후_동기화, daemon=True).start()


def _스케줄_파일_불러오기():
    """_internal/스케줄.json을 읽어 현재 주기에 해당하면 _로컬_작업_스케줄 복원"""
    global _로컬_작업_스케줄, _스케줄_창_끝
    try:
        import json as _json
        path = resource_path('스케줄.json')
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as f:
            data = _json.load(f)

        저장_창_끝_str = data.get('창_끝', '')
        if not 저장_창_끝_str:
            return False
        저장_창_끝 = _예약시간_파싱(저장_창_끝_str)
        if 저장_창_끝 is None:
            return False

        now = datetime.datetime.now()
        if now >= 저장_창_끝:
            print("  [스케줄 복원] 저장된 주기가 이미 만료됨 - 새로 계획합니다.")
            return False

        항목_목록 = data.get('항목', [])
        schedule = []
        for item in 항목_목록:
            dt = _예약시간_파싱(item.get('예약시간_str', ''))
            if dt is None:
                continue
            schedule.append({
                '사용아이디': item['사용아이디'],
                '예약시간': dt,
                '예약시간_str': item['예약시간_str'],
                '키워드생성됨': item.get('키워드생성됨', False),
                '포스팅진행중': False,
                '포스팅완료': item.get('포스팅완료', False),
            })

        if not schedule:
            return False

        _로컬_작업_스케줄 = sorted(schedule, key=lambda x: x['예약시간'])
        _스케줄_창_끝 = 저장_창_끝
        대상 = str(설정_사용아이디).strip() if (설정_사용아이디 and str(설정_사용아이디).strip() != '*') else None
        print(f"  [스케줄 복원] {len(_로컬_작업_스케줄)}건 복원 (주기 끝: {저장_창_끝_str})")
        디버그_로그_저장(f"스케줄 복원 완료 - {len(_로컬_작업_스케줄)}건, 주기끝={저장_창_끝_str}, 대상아이디={대상}")
        _로컬_스케줄_현황_출력(대상)
        _스케줄_시트_동기화_비동기(지연_초=0)  # 복원 시 즉시 기록
        return True
    except Exception as e:
        print(f"  [스케줄 불러오기 오류] {e}")
        return False


def _시작후_테스트_스케줄_1건_추가(예약_지연_초=0):
    """테스트용 스케줄 1건 추가 (최초 1회만). 예약_지연_초=0 이면 추가 직후 도래."""
    global _로컬_작업_스케줄, _테스트_스케줄_추가됨

    if _테스트_스케줄_추가됨:
        return

    test_uid = None
    if 설정_사용아이디 and str(설정_사용아이디).strip() != '*':
        for part in str(설정_사용아이디).split(','):
            part = part.strip()
            if part:
                test_uid = part
                break

    if not test_uid and _로컬_작업_스케줄:
        test_uid = _로컬_작업_스케줄[0]['사용아이디']

    if not test_uid:
        id_df = 구글스프레드시트_계정정보_가져오기()
        if not id_df.empty and '아이디' in id_df.columns:
            for _, acc in id_df.iterrows():
                uid = str(acc['아이디']).strip()
                if uid:
                    test_uid = uid
                    break

    if not test_uid:
        print("  [테스트] 사용 가능한 아이디가 없어 테스트 스케줄을 추가하지 않습니다.")
        _테스트_스케줄_추가됨 = True
        return

    test_dt = datetime.datetime.now() + datetime.timedelta(seconds=예약_지연_초)
    test_str = test_dt.strftime('%Y-%m-%d %H:%M:%S')
    _로컬_작업_스케줄.append({
        '사용아이디': test_uid,
        '예약시간': test_dt,
        '예약시간_str': test_str,
        '키워드생성됨': False,
        '포스팅진행중': False,
        '포스팅완료': False,
        '테스트': True,
    })
    _로컬_작업_스케줄.sort(key=lambda x: x['예약시간'])
    _테스트_스케줄_추가됨 = True
    print(f"  [테스트] 스케줄 1건 추가: {test_str} ({test_uid})")
    중요_작업_로그_저장(f"[테스트] 스케줄 1건 추가: {test_str} ({test_uid})")

    _스케줄_파일_저장()
    _스케줄_시트_동기화_비동기(지연_초=0)

    대상 = str(설정_사용아이디).strip() if (설정_사용아이디 and str(설정_사용아이디).strip() != '*') else None
    _로컬_스케줄_현황_출력(대상)


def _시작후_테스트_스케줄_10초후_등록(대기_초=10):
    """프로그램 시작 후 N초 뒤 백그라운드에서 테스트 스케줄 1건 등록"""
    if not _테스트_스케줄_활성:
        return

    def _지연_등록():
        try:
            print(f"  [테스트] {대기_초}초 후 테스트 스케줄 1건을 등록합니다...")
            time.sleep(대기_초)
            _시작후_테스트_스케줄_1건_추가(예약_지연_초=0)
        except Exception as e:
            print(f"  [테스트] 스케줄 등록 오류: {e}")
            오류_로그_저장(f"테스트 스케줄 등록 오류: {e}")

    threading.Thread(target=_지연_등록, daemon=True).start()


def _스케줄_항목_상태_문자(item):
    if item.get('포스팅완료'):
        return '[완료]'
    if item.get('포스팅진행중'):
        return '[포스팅중]'
    if item.get('키워드생성됨'):
        return '[키워드완료]'
    if item['예약시간'] <= datetime.datetime.now():
        return '[예약도래]'
    return '[대기]'


def _로컬_스케줄_현황_출력(대상_아이디=None):
    """스케줄 현황 콘솔 출력 (5분 간격 호출)"""
    print("\n=== 스케줄 현황 ===")
    if not _로컬_작업_스케줄:
        print("  (계획된 작업 없음)")
        return

    if _스케줄_창_끝:
        창_시작, _ = _스케줄_일일_10시_창()
        print(f"  주기: {창_시작.strftime('%Y-%m-%d %H:%M')} ~ {_스케줄_창_끝.strftime('%Y-%m-%d %H:%M')}")

    items = []
    for item in sorted(_로컬_작업_스케줄, key=lambda x: x['예약시간']):
        if 대상_아이디 and not _사용아이디_일치(item['사용아이디'], 대상_아이디):
            continue
        items.append(item)

    if not items:
        print("  (표시할 작업 없음)")
        return

    완료_수 = sum(1 for i in items if i.get('포스팅완료'))
    print(f"  총 {len(items)}건 / 완료 {완료_수}건")
    for item in items:
        print(f"  {item['예약시간_str']}  {item['사용아이디']}  {_스케줄_항목_상태_문자(item)}")


def _로컬_스케줄_항목_완료표시(사용_아이디=None):
    """포스팅 정상 완료 시 스케줄 항목에 완료 표시"""
    global _현재_스케줄_항목
    if _현재_스케줄_항목 is not None:
        디버그_로그_저장(f"스케줄 완료표시 - 사용아이디={_현재_스케줄_항목.get('사용아이디')}, 예약시간={_현재_스케줄_항목.get('예약시간_str')}")
        _현재_스케줄_항목['포스팅완료'] = True
        _현재_스케줄_항목['포스팅진행중'] = False
        _현재_스케줄_항목 = None
        _스케줄_파일_저장()
        _스케줄_시트_동기화_비동기()
        return
    for item in _로컬_작업_스케줄:
        if item.get('포스팅진행중'):
            디버그_로그_저장(f"스케줄 완료표시(진행중→완료) - 사용아이디={item.get('사용아이디')}")
            item['포스팅완료'] = True
            item['포스팅진행중'] = False
            _스케줄_파일_저장()
            _스케줄_시트_동기화_비동기()
            return
        if 사용_아이디 and _사용아이디_일치(item['사용아이디'], 사용_아이디) and not item.get('포스팅완료'):
            if item.get('키워드생성됨') or item['예약시간'] <= datetime.datetime.now():
                디버그_로그_저장(f"스케줄 완료표시(아이디매칭) - 사용아이디={item.get('사용아이디')}")
                item['포스팅완료'] = True
                item['포스팅진행중'] = False
                _스케줄_파일_저장()
                _스케줄_시트_동기화_비동기()
                return


def _로컬_스케줄_다음_키워드생성_항목(대상_아이디=None):
    """예약시간 도래 + 아직 키워드 미생성 항목"""
    now = datetime.datetime.now()
    전용_목록 = _전용아이디_목록_가져오기() if _공용PC_모드() and not 대상_아이디 else set()
    candidates = []
    for item in _로컬_작업_스케줄:
        if item.get('키워드생성됨') or item.get('포스팅완료'):
            continue
        if 대상_아이디 and not _사용아이디_일치(item['사용아이디'], 대상_아이디):
            continue
        if _공용PC_모드() and not 대상_아이디 and _아이디_전용등록_충돌(item['사용아이디'], 전용_목록):
            continue
        if item['예약시간'] <= now:
            candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=lambda x: x['예약시간'])
    return candidates[0]


def _로컬_스케줄_포스팅_후보_목록(대상_아이디=None):
    """키워드 생성 완료 + 예약시간 도래 + 포스팅 미완료 항목 목록"""
    now = datetime.datetime.now()
    전용_목록 = _전용아이디_목록_가져오기() if _공용PC_모드() and not 대상_아이디 else set()
    candidates = []
    for item in _로컬_작업_스케줄:
        if item.get('포스팅완료') or item.get('포스팅진행중'):
            continue
        if not item.get('키워드생성됨'):
            continue
        if 대상_아이디 and not _사용아이디_일치(item['사용아이디'], 대상_아이디):
            continue
        if _공용PC_모드() and not 대상_아이디 and _아이디_전용등록_충돌(item['사용아이디'], 전용_목록):
            continue
        if item['예약시간'] <= now:
            candidates.append(item)
    candidates.sort(key=lambda x: x['예약시간'])
    return candidates


def _로컬_스케줄_다음_포스팅_항목(대상_아이디=None):
    """키워드 생성 완료 + 예약시간 도래 + 아직 포스팅 미완료 항목"""
    candidates = _로컬_스케줄_포스팅_후보_목록(대상_아이디)
    if not candidates:
        return None
    return candidates[0]


def _로컬_스케줄_다음_예약_안내(대상_아이디=None):
    """대기 중 다음 예약 시각 문자열 반환"""
    now = datetime.datetime.now()
    전용_목록 = _전용아이디_목록_가져오기() if _공용PC_모드() and not 대상_아이디 else set()
    pending = []
    for item in _로컬_작업_스케줄:
        if item.get('포스팅완료'):
            continue
        if 대상_아이디 and not _사용아이디_일치(item['사용아이디'], 대상_아이디):
            continue
        if _공용PC_모드() and not 대상_아이디 and _아이디_전용등록_충돌(item['사용아이디'], 전용_목록):
            continue
        if item['예약시간'] > now or not item.get('키워드생성됨'):
            pending.append(item)
    if not pending:
        return None
    pending.sort(key=lambda x: x['예약시간'])
    nxt = pending[0]
    return f"{nxt['예약시간_str']} ({nxt['사용아이디']})"


def _작업스케줄_일일_등록():
    """(레거시) 로컬 계획만 수립 - 시트에 skeleton 등록하지 않음"""
    _작업스케줄_로컬_계획()
    # _시작후_테스트_스케줄_1건_추가()  # 테스트 스케줄 비활성


def _작업_행_선택_준비됨(all_values, headers, 폴더명, 설정_아이디=None):
    """로컬 스케줄 기준: 키워드 생성 완료 + 예약시간 도래한 ready 행 선택"""
    global _현재_스케줄_항목
    전용_목록 = _전용아이디_목록_가져오기() if _공용PC_모드() and not 설정_아이디 else set()

    for item in _로컬_스케줄_포스팅_후보_목록(설정_아이디):
        target_uid = item['사용아이디']
        후보 = []
        for row_idx in range(1, len(all_values)):
            row_data = all_values[row_idx]
            if _행_예약_상태(row_data, headers) != 'ready':
                continue
            row_uid = _행_값_가져오기(row_data, headers, '사용아이디')
            if not _사용아이디_일치(row_uid, target_uid):
                continue
            if _공용PC_모드() and _아이디_전용등록_충돌(row_uid, 전용_목록):
                continue
            폴더 = _행_값_가져오기(row_data, headers, '폴더')
            if not _셀값_비어있음(폴더) and 폴더 != 폴더명:
                continue
            후보.append((row_idx, row_data))
        if not 후보:
            continue
        row_idx, row_data = 후보[-1]
        item['포스팅진행중'] = True
        _현재_스케줄_항목 = item
        return row_idx + 1, row_data
    return None, None


def _예약시간_도래_스켈레톤_있음(all_values, headers, 대상_아이디=None):
    """(레거시) 로컬 스케줄 기준 키워드생성 필요 여부"""
    return _로컬_스케줄_다음_키워드생성_항목(대상_아이디) is not None


def _kw_사용아이디_목록_파싱(값):
    if _셀값_비어있음(값):
        return []
    return [x.strip() for x in str(값).split(',') if x.strip()]


def _kw_행_사용아이디_포함(사용아이디_셀, target_uid):
    """행 사용아이디(쉼표 목록)에 target_uid(단일 또는 쉼표 목록) 중 하나라도 있으면 True"""
    if not target_uid:
        return True
    return _사용아이디_일치(사용아이디_셀, target_uid)


def _kw_지명업체_df_사용아이디_필터(df, target_uid):
    """지명업체키워드에서 예약 사용아이디가 포함된 행만 남김"""
    if not target_uid or '사용아이디' not in df.columns:
        return df
    mask = df['사용아이디'].apply(lambda v: _kw_행_사용아이디_포함(v, target_uid))
    return df[mask].copy()


def _kw_지명선택_사용아이디_필터_적용(df, 사용_아이디=None):
    """예약 사용아이디에 맞는 지명만 남김"""
    예약_사용아이디 = str(사용_아이디).strip() if 사용_아이디 else None
    if not 예약_사용아이디:
        return df, None
    필터_전_수 = len(df)
    df = _kw_지명업체_df_사용아이디_필터(df, 예약_사용아이디)
    print(f"사용아이디 '{예약_사용아이디}' 매칭 지명 필터: {필터_전_수}개 -> {len(df)}개")
    if df.empty:
        print(f"지명업체키워드에 사용아이디 '{예약_사용아이디}'에 해당하는 지명이 없습니다.")
        return None, 예약_사용아이디
    return df, 예약_사용아이디


def _kw_행_데이터_생성(result_df, headers, 사용아이디_값, 예약시간_값=None):
    row_data = [''] * len(headers)
    for col in result_df.columns:
        if col in headers and col not in ('사용아이디', '예약시간'):
            row_data[headers.index(col)] = str(result_df.iloc[0][col])
    if '사용아이디' in headers:
        row_data[headers.index('사용아이디')] = str(사용아이디_값)
    if '예약시간' in headers and 예약시간_값 is not None:
        row_data[headers.index('예약시간')] = str(예약시간_값)
    return row_data


def _kw_시트_행_쓰기(worksheet, headers, row_num, row_data):
    end_col = _컬럼_글자(len(headers))
    range_name = f'A{row_num}:{end_col}{row_num}'
    gspread_operation_with_timeout(
        lambda: worksheet.batch_update(
            [{'range': range_name, 'values': [row_data]}],
            value_input_option='USER_ENTERED'
        ),
        timeout=20, operation_name=f"지명키워드 {row_num}행 저장"
    )


def 지명키워드_구글시트_저장(result_df, 사용_아이디=None):
    """지명키워드 데이터를 구글 시트에 저장 (skeleton 없으면 새 행 추가)"""
    import socket as _socket
    원래_타임아웃 = _socket.getdefaulttimeout()
    try:
        _socket.setdefaulttimeout(30)
        키_파일_경로 = resource_path('khon21-534690057aec.json')
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
        gc = gspread_authorize_with_timeout(creds)
        spreadsheet = gspread_operation_with_timeout(
            lambda: gc.open_by_key(지명키워드_구글시트_ID),
            timeout=20, operation_name="지명키워드 시트 열기"
        )
        worksheet = gspread_operation_with_timeout(
            lambda: spreadsheet.sheet1,
            timeout=10, operation_name="지명키워드 sheet1 가져오기"
        )
        existing = gspread_operation_with_timeout(
            lambda: worksheet.get_all_values(),
            timeout=20, operation_name="지명키워드 시트 읽기"
        )
        if not existing:
            headers = ['지명', '키워드', '주제', '서비스', '지명키워드', '하나노란', '사용아이디', '폴더']
            gspread_operation_with_timeout(
                lambda: worksheet.append_rows([headers], value_input_option='USER_ENTERED'),
                timeout=20, operation_name="지명키워드 헤더 추가"
            )
            existing = [headers]

        headers = existing[0]
        저장_사용아이디 = str(사용_아이디).strip() if 사용_아이디 else str(result_df.iloc[0].get('사용아이디', '')).strip()
        row_data = _kw_행_데이터_생성(result_df, headers, 저장_사용아이디, None)
        new_row_num = len(existing) + 1
        _kw_시트_행_쓰기(worksheet, headers, new_row_num, row_data)
        print(f"지명키워드 구글 스프레드시트 {new_row_num}행에 새 데이터 추가 (사용아이디: {저장_사용아이디})")
        print(f"   https://docs.google.com/spreadsheets/d/{지명키워드_구글시트_ID}")
        return True
    except Exception as e:
        print(f"지명키워드 구글 스프레드시트 저장 중 오류: {e}")
        return False
    finally:
        _socket.setdefaulttimeout(원래_타임아웃)


def _지명키워드_이력_gc_열기():
    """지명키워드 구글시트 인증 및 클라이언트 반환 (내부 헬퍼)"""
    import socket as _socket
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
    gc = gspread_authorize_with_timeout(creds)
    spreadsheet = gspread_operation_with_timeout(
        lambda: gc.open_by_key(지명키워드_구글시트_ID),
        timeout=20, operation_name="이력 스프레드시트 열기"
    )
    return spreadsheet


def _지명키워드_이력_시트_열기(spreadsheet):
    """이력 시트(GID=지명키워드_이력_시트_GID) 열기. 없으면 새로 생성"""
    try:
        ws = spreadsheet.get_worksheet_by_id(지명키워드_이력_시트_GID)
        return ws
    except Exception:
        pass
    # GID로 못 찾으면 '지명키워드이력' 이름으로 찾거나 생성
    titles = [ws.title for ws in spreadsheet.worksheets()]
    if '지명키워드이력' in titles:
        return spreadsheet.worksheet('지명키워드이력')
    ws = spreadsheet.add_worksheet(title='지명키워드이력', rows=10000, cols=len(_지명키워드_이력_헤더))
    ws.append_row(_지명키워드_이력_헤더, value_input_option='USER_ENTERED')
    return ws


def _지명키워드_이력_행_정규화(headers, row):
    """이력 시트 canonical 헤더 순서로 행 값 재배치"""
    padded = list(row) + [''] * max(0, len(headers) - len(row))
    value_map = {
        headers[i]: padded[i] if i < len(padded) else ''
        for i in range(len(headers))
    }
    return [value_map.get(col, '') for col in _지명키워드_이력_헤더]


def _지명키워드_이력_헤더_보장(ws, existing):
    """이력 시트 헤더·컬럼 순서 보장 (사용아이디 다음 폴더)"""
    canonical = list(_지명키워드_이력_헤더)
    if not existing:
        gspread_operation_with_timeout(
            lambda: ws.append_rows([canonical], value_input_option='USER_ENTERED'),
            timeout=20, operation_name="이력 시트 헤더 추가"
        )
        return canonical

    headers = [h.strip() for h in existing[0]]
    merged_headers = list(headers)
    for col_name in canonical:
        if col_name not in merged_headers:
            merged_headers.append(col_name)

    if merged_headers == canonical:
        return canonical

    normalized = [canonical]
    for row in existing[1:]:
        normalized.append(_지명키워드_이력_행_정규화(merged_headers, row))

    gspread_operation_with_timeout(
        lambda: ws.update(
            values=normalized,
            range_name='A1',
            value_input_option='USER_ENTERED',
        ),
        timeout=30, operation_name="이력 시트 컬럼 순서 정규화"
    )
    return canonical


def _지명키워드_이력_시트_일괄_저장(지명키워드_값, 사용아이디, 글유형='', 세부유형='', 아이피='', 링크=''):
    """포스팅 완료 후 이력 시트(GID=39603624)에 한 행 일괄 기록"""
    import socket as _socket
    원래_타임아웃 = _socket.getdefaulttimeout()
    try:
        _socket.setdefaulttimeout(30)
        spreadsheet = _지명키워드_이력_gc_열기()
        ws = _지명키워드_이력_시트_열기(spreadsheet)
        existing = gspread_operation_with_timeout(
            lambda: ws.get_all_values(),
            timeout=20, operation_name="이력 시트 읽기"
        )
        headers = _지명키워드_이력_헤더_보장(ws, existing)
        if existing:
            existing[0] = headers
        날짜 = datetime.datetime.now().strftime('%Y-%m-%d')
        new_row = [''] * len(headers)
        col_map = {h: i for i, h in enumerate(headers)}
        new_row[col_map.get('지명키워드', 0)] = str(지명키워드_값)
        new_row[col_map.get('날짜', 1)] = 날짜
        new_row[col_map.get('사용아이디', 2)] = str(사용아이디)
        if '폴더' in col_map:
            new_row[col_map['폴더']] = _작업_폴더명()
        if '글유형' in col_map and 글유형:
            new_row[col_map['글유형']] = str(글유형)
        if '세부유형' in col_map and 세부유형:
            new_row[col_map['세부유형']] = str(세부유형)
        if '아이피' in col_map and 아이피:
            new_row[col_map['아이피']] = str(아이피).strip()
        if '링크' in col_map and 링크:
            new_row[col_map['링크']] = str(링크).strip()
        gspread_operation_with_timeout(
            lambda: ws.append_rows([new_row], value_input_option='USER_ENTERED'),
            timeout=20, operation_name="이력 시트 일괄 행 추가"
        )
        ip_val = str(아이피).strip() if 아이피 else '-'
        print(
            f"지명키워드 이력 일괄 기록: '{지명키워드_값}' / {날짜} / {사용아이디} / "
            f"글유형={글유형 or '-'} / 세부유형={세부유형 or '-'} / 폴더={_작업_폴더명()} / IP={ip_val} / "
            f"링크={'(있음)' if 링크 else '-'}"
        )
    except Exception as e:
        print(f"지명키워드 이력 일괄 기록 오류: {e}")
    finally:
        _socket.setdefaulttimeout(원래_타임아웃)





# 블로그 제목·원고 글유형 (제목/원고 생성 시 사용)
유형_목록 = ["정보형", "설치후기형", "FAQ·비교·모델 소개형"]
# 하루 3건 이상 시 이상적 배분 순서: 설치후기 1건 -> 정보형 1건 -> FAQ 1건
글유형_우선순위 = ["설치후기형", "정보형", "FAQ·비교·모델 소개형"]
# 지명키워드 재사용 소진 판단에만 사용 (FAQ·비교·모델 소개형은 소진 집계 제외)
소진_글유형_목록 = ["정보형", "설치후기형"]
FAQ_글유형 = "FAQ·비교·모델 소개형"
FAQ_아이디_당일_한도 = 1
블로그_제목_최소_글자 = 25
블로그_제목_최대_글자 = 35
설치후기형_제목_최대_글자 = 40
설치후기형_제목_허용_표현_목록 = [
    '설치 후기', '설치후기',
    '설치 사례', '설치 현장', '{대상업종} 설치 사례', '현장 후기', '고객 사례',
    '설치 현장 스케치', '설치 이야기', '설치 리포트', '활용사례', '운영 사례',
    '도입 사례', '적용 사례', '고객 경험담', '고객 인터뷰', '설치 현장 스토리',
    '설치 현장 탐방', '설치 비하인드', '설치 과정', '설치과정 공개',
    'Before & After', '설치 전후 비교',
]
블로그_제목_생성_후보_개수 = 3
블로그_제목_생성_최소_통과_개수 = 1
블로그_제목_선택_개수 = 1
FAQ_세부유형_목록 = ["FAQ형", "비교형", "모델 소개형"]
FAQ_질문_목록 = [
    "복합기 렌탈과 구매, 어떤 것이 더 저렴할까요?",
    "프린터 렌탈 계약기간은 보통 몇 년인가요?",
    "토너는 무상으로 제공되나요?",
    "A3 복합기와 A4 복합기 차이는?",
    "컬러복합기 월 렌탈료는 얼마인가요?",
    "복합기 고장 시 AS는 얼마나 걸리나요?",
    "흑백 출력이 많은데 어떤 모델이 좋나요?",
    "소규모 사무실에는 어떤 복합기를 추천하나요?",
]
FAQ_비교_주제_목록 = [
    "컬러복합기 vs 흑백복합기",
    "잉크젯 vs 레이저 프린터",
    "렌탈 vs 구매 비용 비교",
    "새제품 vs 리퍼 제품",
    "리코 vs 캐논 vs 엡손",
]
FAQ_모델소개_주제_목록 = [
    "특징 및 장점",
    "추천 업종",
    "토너 비용",
    "실제 설치 사례",
    "사용 후기",
    "자주 발생하는 오류 해결법",
]


def _FAQ_비교_주제_생성(추천모델):
    """비교형 세부주제: 모델 간 비교 또는 일반 비교 주제"""
    if random.random() < 0.45:
        others = [m for m in 추천모델_목록 if m != 추천모델]
        if others:
            return f"{추천모델} vs {random.choice(others)} 차이점"
    return random.choice(FAQ_비교_주제_목록)


def _현재_작업_사용아이디():
    """작업큐 캐시 또는 설정에서 현재 사용아이디 반환"""
    try:
        if _지명키워드_캐시_df is not None and '사용아이디' in _지명키워드_캐시_df.columns:
            uid = str(_지명키워드_캐시_df.iloc[0]['사용아이디']).strip()
            if uid and uid.lower() not in ('nan', 'none', ''):
                return uid
    except Exception:
        pass
    if 설정_사용아이디:
        for _part in str(설정_사용아이디).split(','):
            _part = _part.strip()
            if _part and _part != '*':
                return _part
    return ''


def _아이디_당일_FAQ_세부유형_사용_카운트(사용아이디, 기준_날짜=None):
    """이력 시트에서 해당 아이디의 당일 FAQ 세부유형별 사용 횟수 dict 반환"""
    import socket as _socket
    원래 = _socket.getdefaulttimeout()
    uid_str = str(사용아이디).strip()
    결과 = {t: 0 for t in FAQ_세부유형_목록}
    if not uid_str:
        return 결과
    if 기준_날짜 is None:
        기준_날짜 = datetime.datetime.now().strftime('%Y-%m-%d')
    try:
        _socket.setdefaulttimeout(30)
        spreadsheet = _지명키워드_이력_gc_열기()
        try:
            ws = spreadsheet.get_worksheet_by_id(지명키워드_이력_시트_GID)
        except Exception:
            return 결과
        all_values = gspread_operation_with_timeout(
            lambda: ws.get_all_values(),
            timeout=20, operation_name="이력 시트 읽기 (FAQ 세부유형)"
        )
        if not all_values or len(all_values) < 2:
            return 결과
        headers = [h.strip() for h in all_values[0]]
        date_idx = headers.index('날짜') if '날짜' in headers else 1
        uid_idx = headers.index('사용아이디') if '사용아이디' in headers else 2
        type_idx = headers.index('글유형') if '글유형' in headers else -1
        sub_idx = headers.index('세부유형') if '세부유형' in headers else -1
        if type_idx < 0:
            return 결과
        for row in all_values[1:]:
            if len(row) <= max(date_idx, uid_idx, type_idx):
                continue
            if row[uid_idx].strip() != uid_str:
                continue
            if not _이력_날짜_당일_여부(row[date_idx], 기준_날짜):
                continue
            if row[type_idx].strip() != FAQ_글유형:
                continue
            sub = row[sub_idx].strip() if sub_idx >= 0 and len(row) > sub_idx else ''
            if sub in 결과:
                결과[sub] += 1
        return 결과
    except Exception as e:
        print(f"FAQ 세부유형 당일 사용 횟수 조회 오류: {e}")
        return 결과
    finally:
        _socket.setdefaulttimeout(원래)


def _FAQ_세부유형_균등_선택(사용아이디, 추가_카운트=None):
    """FAQ 세부유형(FAQ형/비교형/모델 소개형) 중 당일 사용 횟수가 가장 적은 유형 선택"""
    카운트 = _아이디_당일_FAQ_세부유형_사용_카운트(사용아이디)
    if 추가_카운트:
        for k, v in 추가_카운트.items():
            if k in 카운트:
                카운트[k] += v
    최소 = min(카운트.get(t, 0) for t in FAQ_세부유형_목록)
    동률 = [t for t in FAQ_세부유형_목록 if 카운트.get(t, 0) == 최소]
    선택 = random.choice(동률)
    요약 = ', '.join(f"{t}:{카운트.get(t, 0)}" for t in FAQ_세부유형_목록)
    print(f"FAQ 세부유형 균등 선택 (당일 사용 - {요약}) -> {선택}")
    return 선택


def _FAQ_세부유형_배정(추천모델, 사용아이디=None, 추가_카운트=None):
    """FAQ·비교·모델 소개형 작성 시 세부유형·세부주제 균등 배정"""
    if not 사용아이디:
        사용아이디 = _현재_작업_사용아이디()
    세부유형 = _FAQ_세부유형_균등_선택(사용아이디, 추가_카운트)
    if 추가_카운트 is not None:
        추가_카운트[세부유형] = 추가_카운트.get(세부유형, 0) + 1
    if 세부유형 == "FAQ형":
        세부주제 = random.choice(FAQ_질문_목록)
    elif 세부유형 == "비교형":
        세부주제 = _FAQ_비교_주제_생성(추천모델)
    else:
        각도 = random.choice(FAQ_모델소개_주제_목록)
        세부주제 = f"{추천모델} {각도}"
    return 세부유형, 세부주제


def _FAQ_제목_유형_지침(세부유형, 세부주제):
    """FAQ·비교·모델 소개형 제목 생성용 세부 지침"""
    if 세부유형 == "FAQ형":
        return (
            f"FAQ형 — 고객이 가장 많이 묻는 질문에 답하는 제목 (네이버 AI 브리핑 친화적).\n"
            f"이번 핵심 질문: '{세부주제}'\n"
            "예: '익산 복합기렌탈 토너 무상인가요? 리코 IM C2010 FAQ', "
            "'군산 복합기렌탈 A3와 A4 차이 캐논 iR C3322'\n"
            "'FAQ', '자주 묻는 질문', '궁금', '얼마', '몇 년', '차이' 처럼 질문·답변형 어조."
        )
    if 세부유형 == "비교형":
        return (
            f"비교형 — 검색량 높은 비교 콘텐츠 제목 (체류시간 확보).\n"
            f"이번 비교 주제: '{세부주제}'\n"
            "예: '익산 복합기 렌탈 캐논 iR C3322와 브라더 임대 비용 비교', "
            "'군산 복합기 렌탈 컬러 vs 흑백 캐논 iR C3322 렌탈 비용 비교'\n"
            "비용 비교 시 '임대 비', '렌탈 비' 축약 금지. 반드시 '임대 비용', '렌탈 비용'으로 쓴다.\n"
            "'vs', '비교', '차이', '어떤 게' 처럼 비교·대조가 드러나는 어조."
        )
    return (
        f"모델 소개형 — 실제 문의가 많은 모델 중심 소개 제목.\n"
        f"이번 소개 각도: '{세부주제}'\n"
        "예: '익산 복합기렌탈 리코 IM C2010 토너 비용 정리', "
        "'군산 복합기렌탈 캐논 iR C3322 추천 업종과 특징'\n"
        "'특징', '장점', '토너', '설치 사례', '후기', '오류' 처럼 모델 하나를 깊게 다루는 어조."
    )


def _이력_날짜_당일_여부(날짜_값, 기준_날짜=None):
    """이력 시트 날짜 값이 기준일(기본: 오늘)과 같은지 확인"""
    if 기준_날짜 is None:
        기준_날짜 = datetime.datetime.now().strftime('%Y-%m-%d')
    s = str(날짜_값).strip()
    if not s or s.lower() in ('nan', 'none', ''):
        return False
    return s[:10] == str(기준_날짜).strip()[:10]


def _아이디_당일_FAQ_유형_사용횟수(사용아이디, 기준_날짜=None):
    """이력 시트에서 해당 아이디가 당일 FAQ·비교·모델 소개형으로 기록된 횟수"""
    카운트 = _아이디_당일_글유형_사용_카운트(사용아이디, 기준_날짜)
    return 카운트.get(FAQ_글유형, 0)


def _아이디_당일_글유형_사용_카운트(사용아이디, 기준_날짜=None):
    """이력 시트에서 해당 아이디의 당일 글유형별 사용 횟수 dict 반환"""
    import socket as _socket
    원래 = _socket.getdefaulttimeout()
    uid_str = str(사용아이디).strip()
    결과 = {t: 0 for t in 유형_목록}
    if not uid_str:
        return 결과
    if 기준_날짜 is None:
        기준_날짜 = datetime.datetime.now().strftime('%Y-%m-%d')
    try:
        _socket.setdefaulttimeout(30)
        spreadsheet = _지명키워드_이력_gc_열기()
        try:
            ws = spreadsheet.get_worksheet_by_id(지명키워드_이력_시트_GID)
        except Exception:
            return 결과
        all_values = gspread_operation_with_timeout(
            lambda: ws.get_all_values(),
            timeout=20, operation_name="이력 시트 읽기 (당일 글유형)"
        )
        if not all_values or len(all_values) < 2:
            return 결과
        headers = [h.strip() for h in all_values[0]]
        date_idx = headers.index('날짜') if '날짜' in headers else 1
        uid_idx = headers.index('사용아이디') if '사용아이디' in headers else 2
        type_idx = headers.index('글유형') if '글유형' in headers else -1
        if type_idx < 0:
            return 결과
        for row in all_values[1:]:
            if len(row) <= max(date_idx, uid_idx, type_idx):
                continue
            if row[uid_idx].strip() != uid_str:
                continue
            if not _이력_날짜_당일_여부(row[date_idx], 기준_날짜):
                continue
            t = row[type_idx].strip()
            if t in 결과:
                결과[t] += 1
        return 결과
    except Exception as e:
        print(f"당일 글유형 사용 횟수 조회 오류: {e}")
        return 결과
    finally:
        _socket.setdefaulttimeout(원래)


def _글유형_우선순위_선택(후보, 사용아이디):
    """후보 중 당일 미사용 유형을 우선순위(설치후기형->정보형->FAQ)대로 선택.
    지명키워드_한도로 후보에서 빠진 유형은 건너뛰고 다음 순위를 선택한다."""
    if not 후보:
        return random.choice(유형_목록)
    if len(후보) == 1:
        return 후보[0]
    카운트 = _아이디_당일_글유형_사용_카운트(사용아이디)
    요약 = ', '.join(f"{t}:{카운트.get(t, 0)}" for t in 글유형_우선순위)
    for t in 글유형_우선순위:
        if t in 후보 and 카운트.get(t, 0) == 0:
            print(f"글유형 우선순위 선택 (당일 사용 - {요약}) -> {t}")
            return t
    for t in 글유형_우선순위:
        if t in 후보:
            print(f"글유형 우선순위 선택 (당일 모두 사용, 후보 중 최우선 - {요약}) -> {t}")
            return t
    선택 = 후보[0]
    print(f"글유형 우선순위 선택 (후보 fallback - {요약}) -> {선택}")
    return 선택


def _FAQ_유형_당일_선택_가능(사용아이디):
    """아이디당 하루 FAQ·비교·모델 소개형 1회 제한 (순서 무관)"""
    if not str(사용아이디).strip():
        return True
    return _아이디_당일_FAQ_유형_사용횟수(사용아이디) < FAQ_아이디_당일_한도


def _글유형_선택_후보_정리(사용가능_유형, 사용아이디):
    """FAQ 당일 한도 등 후처리 후 선택 가능 유형 목록 반환"""
    후보 = list(사용가능_유형)
    if 사용아이디 and not _FAQ_유형_당일_선택_가능(사용아이디):
        if FAQ_글유형 in 후보:
            print(f"FAQ·비교·모델 소개형 당일 한도({FAQ_아이디_당일_한도}회) 도달: {사용아이디}")
        후보 = [t for t in 후보 if t != FAQ_글유형]
    if not 후보:
        후보 = [t for t in 소진_글유형_목록]
    return 후보


def _지명키워드_사용자_소진_set(사용아이디, 한도=1):
    """이력 시트에서 해당 사용아이디가 소진_글유형_목록 조합을 한도 이상 사용한 지명키워드 set 반환
    - (지명키워드 + 글유형) 조합별로 집계
    - 정보형·설치후기형 모두 한도 이상 사용된 경우에만 소진 (FAQ 유형은 소진 미포함)
    """
    import socket as _socket
    원래_타임아웃 = _socket.getdefaulttimeout()
    글유형_전체 = set(소진_글유형_목록)
    try:
        _socket.setdefaulttimeout(30)
        spreadsheet = _지명키워드_이력_gc_열기()
        try:
            ws = spreadsheet.get_worksheet_by_id(지명키워드_이력_시트_GID)
        except Exception:
            return set()
        all_values = gspread_operation_with_timeout(
            lambda: ws.get_all_values(),
            timeout=20, operation_name="이력 시트 전체 읽기"
        )
        if not all_values or len(all_values) < 2:
            return set()
        headers = [h.strip() for h in all_values[0]]
        kw_idx      = headers.index('지명키워드') if '지명키워드' in headers else 0
        uid_idx     = headers.index('사용아이디') if '사용아이디' in headers else 2
        글유형_idx  = headers.index('글유형')    if '글유형'    in headers else -1
        uid_str = str(사용아이디).strip()

        # (지명키워드, 글유형) 조합별 사용 횟수 집계
        카운트 = {}
        for row in all_values[1:]:
            if len(row) <= max(kw_idx, uid_idx):
                continue
            if row[uid_idx].strip() != uid_str:
                continue
            kw      = row[kw_idx].strip()
            글유형  = row[글유형_idx].strip() if 글유형_idx >= 0 and len(row) > 글유형_idx else ''
            key = (kw, 글유형)
            카운트[key] = 카운트.get(key, 0) + 1

        # 소진_글유형_목록(정보형·설치후기형)이 모두 한도 이상 사용된 지명키워드만 소진 처리
        모든_kw = {kw for (kw, _) in 카운트}
        소진 = set()
        for kw in 모든_kw:
            if all(카운트.get((kw, t), 0) >= 한도 for t in 글유형_전체):
                소진.add(kw)
        return 소진
    except Exception as e:
        print(f"지명키워드 소진 목록 조회 오류: {e}")
        return set()
    finally:
        _socket.setdefaulttimeout(원래_타임아웃)


def _지명키워드_사용가능_글유형(사용아이디, 지명키워드, 한도=1):
    """이력 시트에서 해당 (사용아이디, 지명키워드) 기준으로 선택 가능한 글유형 목록 반환
    - 소진_글유형_목록: 한도 미달인 유형만 포함
    - FAQ·비교·모델 소개형: 지명키워드 소진 미포함, 아이디당 당일 1회만 선택 가능
    """
    import socket as _socket
    원래 = _socket.getdefaulttimeout()
    try:
        _socket.setdefaulttimeout(30)
        spreadsheet = _지명키워드_이력_gc_열기()
        try:
            ws = spreadsheet.get_worksheet_by_id(지명키워드_이력_시트_GID)
        except Exception:
            return _글유형_선택_후보_정리(list(유형_목록), 사용아이디)
        all_values = gspread_operation_with_timeout(
            lambda: ws.get_all_values(),
            timeout=20, operation_name="이력 시트 읽기 (글유형 확인)"
        )
        if not all_values or len(all_values) < 2:
            return _글유형_선택_후보_정리(list(유형_목록), 사용아이디)
        headers = [h.strip() for h in all_values[0]]
        kw_idx      = headers.index('지명키워드') if '지명키워드' in headers else 0
        uid_idx     = headers.index('사용아이디') if '사용아이디' in headers else 2
        글유형_idx  = headers.index('글유형')    if '글유형'    in headers else -1
        uid_str = str(사용아이디).strip()
        kw_str  = str(지명키워드).strip()
        카운트 = {}
        for row in all_values[1:]:
            if len(row) <= max(kw_idx, uid_idx):
                continue
            if row[uid_idx].strip() != uid_str:
                continue
            if row[kw_idx].strip() != kw_str:
                continue
            t = row[글유형_idx].strip() if 글유형_idx >= 0 and len(row) > 글유형_idx else ''
            if t:
                카운트[t] = 카운트.get(t, 0) + 1
        사용가능 = [t for t in 소진_글유형_목록 if 카운트.get(t, 0) < 한도]
        for t in 유형_목록:
            if t not in 소진_글유형_목록 and t not in 사용가능:
                if t == FAQ_글유형 and not _FAQ_유형_당일_선택_가능(사용아이디):
                    continue
                사용가능.append(t)
        if not 사용가능:
            사용가능 = [t for t in 유형_목록 if t != FAQ_글유형 or _FAQ_유형_당일_선택_가능(사용아이디)]
        return _글유형_선택_후보_정리(사용가능, 사용아이디)
    except Exception as e:
        print(f"사용가능 글유형 조회 오류 (전체 허용): {e}")
        return _글유형_선택_후보_정리(list(유형_목록), 사용아이디)
    finally:
        _socket.setdefaulttimeout(원래)


def _유효_키워드_값(값):
    """빈값, None, nan, 'None' 문자열 등 무효 키워드 제외"""
    if 값 is None or (isinstance(값, float) and pd.isna(값)):
        return None
    s = str(값).strip()
    if not s or s.lower() in ('none', 'nan', 'null'):
        return None
    return s


def _유효_키워드_인덱스_목록(df):
    """df에서 유효한 키워드가 있는 행 인덱스 목록"""
    return [idx for idx in df.index if _유효_키워드_값(df.loc[idx, '키워드'])]


def _키워드생성_result_df_만들기(df_지명, df_키워드풀, min_사용_인덱스, selected_지명, selected_하나노란, selected_사용아이디, 저장_사용아이디):
    """지명/키워드/서비스 조합으로 result_df 생성 (키워드·서비스는 전체 풀에서 랜덤)"""
    random_키워드 = _유효_키워드_값(df_지명.loc[min_사용_인덱스, '키워드'])
    random_키워드_idx = min_사용_인덱스 if random_키워드 else None

    if not random_키워드:
        유효_인덱스 = _유효_키워드_인덱스_목록(df_키워드풀)
        if 유효_인덱스:
            random_키워드_idx = random.choice(유효_인덱스)
            random_키워드 = _유효_키워드_값(df_키워드풀.loc[random_키워드_idx, '키워드'])

    if not random_키워드:
        풀_수 = len(_유효_키워드_인덱스_목록(df_키워드풀))
        지명_수 = len(_유효_키워드_인덱스_목록(df_지명))
        print(f"유효한 키워드를 찾을 수 없습니다. (지명필터 {지명_수}개, 전체풀 {풀_수}개)")
        return None, None

    random_주제 = ''
    if '주제' in df_키워드풀.columns and random_키워드_idx is not None:
        raw_주제 = df_키워드풀.loc[random_키워드_idx, '주제']
        if pd.notna(raw_주제):
            s = str(raw_주제).strip()
            if s and s.lower() not in ('none', 'nan', 'null'):
                random_주제 = s

    print(f"\n선택된 항목:")
    print(f"지명: {selected_지명} (사용횟수: {df_지명.loc[min_사용_인덱스, '사용']})")
    print(f"키워드: {random_키워드}")
    if random_주제:
        print(f"주제: {random_주제}")

    uid = 저장_사용아이디 or selected_사용아이디

    if '서비스' in df_키워드풀.columns:
        서비스_목록 = [_유효_키워드_값(v) for v in df_키워드풀['서비스']]
        서비스_목록 = [v for v in 서비스_목록 if v]
        random_서비스 = random.choice(서비스_목록) if 서비스_목록 else None
        if random_서비스 and str(random_서비스).strip() != '':
            print(f"서비스: {random_서비스}")
            지명키워드 = f"{selected_지명} {random_키워드} {random_서비스}"
            return pd.DataFrame({
                '지명': [selected_지명], '키워드': [random_키워드], '주제': [random_주제],
                '서비스': [random_서비스], '지명키워드': [지명키워드],
                '하나노란': [selected_하나노란], '사용아이디': [uid],
            }), 지명키워드

    지명키워드 = f"{selected_지명} {random_키워드}"
    cols = {
        '지명': [selected_지명], '키워드': [random_키워드], '주제': [random_주제],
        '지명키워드': [지명키워드], '하나노란': [selected_하나노란], '사용아이디': [uid],
        '폴더': [os.path.basename(os.getcwd())],
    }
    return pd.DataFrame(cols), 지명키워드


def 키워드생성_실행(사용_아이디=None):
    """지명업체키워드에서 지명 선택 후 지명키워드 구글시트에 저장 (포스팅.py 내장)"""
    uid_label = str(사용_아이디).strip() if 사용_아이디 else '전체'
    print(f"키워드생성 시작 (사용아이디: {uid_label})")

    try:
        df = None
        max_retries = 5
        retry_delay = 30
        for retry_count in range(max_retries):
            print(f"Google Sheets 데이터 읽기 시도 {retry_count + 1}/{max_retries}")
            df = 구글_시트_읽기(지명업체키워드_스프레드시트_ID)
            if df is not None:
                print("Google Sheets 데이터 읽기 성공!")
                break
            print(f"Google Sheets 데이터 읽기 실패 (시도 {retry_count + 1}/{max_retries})")
            if retry_count < max_retries - 1:
                print(f"{retry_delay}초 후 재시도합니다...")
                time.sleep(retry_delay)
                retry_delay += 5
            else:
                print("Google Sheets 데이터 읽기 최종 실패.")
                return False

        if df is None:
            return False

        if '지명' not in df.columns or '키워드' not in df.columns or '사용' not in df.columns:
            print("지명, 키워드, 사용 컬럼을 찾을 수 없습니다.")
            print("실제 컬럼명:", df.columns.tolist())
            return False

        df['사용'] = pd.to_numeric(df['사용'], errors='coerce').fillna(0)

        print("\n월작업 완료 업체 필터링 시작...")
        완료된_하나노란_목록 = 월작업_완료_업체_목록_가져오기()
        if 완료된_하나노란_목록 and '하나노란' in df.columns:
            필터_전_수 = len(df)
            df = df[~df['하나노란'].astype(str).isin(완료된_하나노란_목록)].copy()
            print(f"월작업 완료 업체 제외: {필터_전_수}개 -> {len(df)}개")
        if df.empty:
            print("모든 업체가 이번 달 월작업을 완료했습니다.")
            중요_작업_로그_저장("모든 업체 월작업 완료")
            return False

        df_키워드풀 = df.copy()

        df, 예약_사용아이디 = _kw_지명선택_사용아이디_필터_적용(df, 사용_아이디)
        if df is None or df.empty:
            return False

        # 이 사용자가 이미 사용한 지명키워드 조합 목록 (중복 방지)
        _uid_for_dup = 예약_사용아이디 or (str(사용_아이디).strip() if 사용_아이디 else None)
        소진_지명키워드_set = set()
        if _uid_for_dup and 설정_지명키워드_한도 > 0:
            소진_지명키워드_set = _지명키워드_사용자_소진_set(_uid_for_dup, 설정_지명키워드_한도)
            if 소진_지명키워드_set:
                print(f"  '{_uid_for_dup}' 재사용 불가 지명키워드 {len(소진_지명키워드_set)}건 제외 (한도: {설정_지명키워드_한도}회)")

        # 중복 없는 지명키워드 조합 탐색 (지명별 최대 5회 서비스 랜덤, 지명은 최대 30개까지)
        제외_지명_set = set()
        result_df = None
        지명키워드 = None
        min_사용_인덱스 = None
        selected_지명 = None
        selected_하나노란 = ""
        selected_사용아이디 = ""
        저장_사용아이디 = None
        max_지명_시도 = min(len(df['지명'].unique()) + 1, 30)

        for _지명_시도 in range(max_지명_시도):
            df_후보 = df[~df['지명'].isin(제외_지명_set)].copy() if 제외_지명_set else df
            if df_후보.empty:
                print("모든 지명의 키워드 조합이 이미 사용되었습니다.")
                break

            _idx = df_후보['사용'].idxmin()
            _지명 = str(df_후보.loc[_idx, '지명'])
            _하나노란 = str(df_후보.loc[_idx, '하나노란']).strip() if '하나노란' in df_후보.columns else ""
            if _하나노란 == 'nan': _하나노란 = ""
            _suid = str(df_후보.loc[_idx, '사용아이디']).strip() if '사용아이디' in df_후보.columns else ""
            if _suid == 'nan': _suid = ""
            _저장uid = 예약_사용아이디 or (str(사용_아이디).strip() if 사용_아이디 else _suid)

            _성공 = False
            for _kw_시도 in range(5):
                _rdf, _kw = _키워드생성_result_df_만들기(
                    df_후보, df_키워드풀, _idx, _지명, _하나노란, _suid, _저장uid)
                if _rdf is None or not _kw:
                    break
                if 소진_지명키워드_set and _kw in 소진_지명키워드_set:
                    print(f"  '{_kw}' 이미 사용됨({_저장uid}), 서비스 재선택 ({_kw_시도+1}/5)")
                    continue
                result_df = _rdf
                지명키워드 = _kw
                min_사용_인덱스 = _idx
                selected_지명 = _지명
                selected_하나노란 = _하나노란
                selected_사용아이디 = _suid
                저장_사용아이디 = _저장uid
                _성공 = True
                break

            if _성공:
                break

            print(f"  '{_지명}' 지명 사용 가능한 미사용 조합 없음 -> 다음 지명 탐색")
            제외_지명_set.add(_지명)

        if result_df is None or not 지명키워드:
            print("지명키워드 생성 실패: 사용 가능한 미사용 지명키워드가 없습니다.")
            return False

        print(f"지명, 하나노란, 사용아이디 함께 선택: '{selected_지명}' / '{selected_하나노란}' / '{selected_사용아이디}'")
        저장_사용아이디 = 저장_사용아이디 or selected_사용아이디

        현재_사용_횟수 = int(df.loc[min_사용_인덱스, '사용'])
        새_사용_횟수 = 현재_사용_횟수 + 1
        print(f"지명 선택 후 사용 횟수 업데이트: {현재_사용_횟수} -> {새_사용_횟수}")

        업데이트_성공 = False
        for 재시도 in range(3):
            if 구글_시트_특정_행_업데이트(지명업체키워드_스프레드시트_ID, selected_지명, min_사용_인덱스, '사용', 새_사용_횟수):
                print(f"Google Sheets에서 지명 '{selected_지명}'의 사용 횟수가 {새_사용_횟수}로 업데이트되었습니다.")
                업데이트_성공 = True
                break
            print(f"Google Sheets 업데이트 실패 (재시도 {재시도 + 1}/3)")
            if 재시도 < 2:
                time.sleep(3)
        if not 업데이트_성공:
            print("Google Sheets 사용 횟수 업데이트 실패.")
            return False

        print(f"\n생성된 지명키워드: '{지명키워드}'")
        중요_작업_로그_저장(f"지명키워드 생성 완료: {지명키워드}")
        _키워드생성_후_원고캐시_초기화(지명키워드)

        if not 지명키워드_로컬파일_저장(result_df, 사용_아이디=저장_사용아이디):
            return False
        작업_로그_저장(f"지명키워드 로컬파일 저장 완료: {len(result_df)}개 데이터")

        하나노란_값 = selected_하나노란
        if 하나노란_값:
            try:
                작업관리_df = 구글_시트_읽기(작업관리_스프레드시트_ID)
                if 작업관리_df is not None and 월작업갯수_확인(하나노란_값, 작업관리_df):
                    print(f"해당 하나노란의 월작업갯수에 도달했습니다. (하나노란: {하나노란_값})")
                    중요_작업_로그_저장(f"월작업갯수 도달 (하나노란: {하나노란_값})")
                    return False
            except Exception as e:
                print(f"작업관리 스프레드시트 처리 중 오류: {e}")

        print("지명키워드 생성 완료!")
        return True

    except Exception as e:
        print(f"키워드생성 중 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


def _예약_키워드생성_실행(대상_아이디=None, 스케줄_항목=None):
    """예약시간 도래 시 작업시트(GID=1679797725) 우선 확인, 없으면 키워드생성_실행()"""
    uid = 대상_아이디
    if 스케줄_항목 and 스케줄_항목.get('사용아이디'):
        uid = 스케줄_항목.get('사용아이디')
    print(f"예약시간 도래 - 작업시트 우선 확인 (사용아이디: {uid or '전체'})")
    디버그_로그_저장(f"예약 작업 확인 시작 - 사용아이디={uid}, 스케줄항목={스케줄_항목}")
    try:
        if _예약_시트_작업_가져오기(uid, 스케줄_항목):
            return True
        print(f"작업시트에 등록 작업 없음 - 키워드생성 실행 (사용아이디: {uid or '전체'})")
        디버그_로그_저장(f"키워드생성 시작 - 사용아이디={uid}, 스케줄항목={스케줄_항목}")
        ok = 키워드생성_실행(uid)
        디버그_로그_저장(f"키워드생성 결과 - 사용아이디={uid}, ok={ok}")
        if 스케줄_항목 is not None and ok:
            스케줄_항목['키워드생성됨'] = True
            # 방금 저장된 로컬 작업큐에서 지명키워드 가져와 스케줄 항목에 기록
            try:
                큐 = _로컬_작업큐_읽기()
                for q in reversed(큐):
                    if _사용아이디_일치(q.get('사용아이디', ''), uid or ''):
                        스케줄_항목['지명키워드'] = q.get('지명키워드', '')
                        디버그_로그_저장(f"스케줄항목 지명키워드 업데이트: {스케줄_항목['지명키워드']}")
                        break
            except Exception:
                pass
            _스케줄_파일_저장()
            _스케줄_시트_동기화_비동기()
        return ok
    except Exception as e:
        오류_로그_저장(f"키워드생성 실행 오류: {e}")
        print(f"키워드생성 실행 오류: {e}")
        return False



def _전용PC_작업_행_준비(설정_아이디, 폴더명):
    """전용 PC: 스케줄 등록된 작업 대기 -> 30초 간격 무한 폴링 -> 로컬 작업큐에서 항목 반환"""
    global _지명키워드_캐시_df
    print(f"전용 PC 모드: 예약시간 도래 시 키워드생성 후 '{설정_아이디}' 작업 처리")
    대기_횟수 = 0
    _마지막_시트_동기화 = datetime.datetime.now()

    while True:
        _스케줄_주기_갱신_확인()
        if _스케줄_계획_금지시간() and not _로컬_작업_스케줄:
            대기_횟수 += 1
            if 대기_횟수 == 1 or 대기_횟수 % 4 == 0:
                print(f"23시~1시 - 스케줄 갱신 대기 중... ({대기_횟수}회, 30초 간격)")
            time.sleep(30)
            continue

        if _예약시간_도래_스켈레톤_있음(None, None, 설정_아이디):
            kw_item = _로컬_스케줄_다음_키워드생성_항목(설정_아이디)
            _예약_키워드생성_실행(설정_아이디, kw_item)
            time.sleep(5)
            continue

        idx, q_item = _로컬_작업큐_항목_선택(폴더명, 설정_아이디)
        if idx is not None:
            _로컬_작업큐_폴더_업데이트(idx, 폴더명)
            _캐시_설정_로컬(q_item, idx)
            print(f"작업 확인 완료 (큐 인덱스 {idx}, 대기 {대기_횟수}회)")
            return

        대기_횟수 += 1
        if 대기_횟수 == 1 or 대기_횟수 % _스케줄_현황_출력_간격 == 0:
            _로컬_스케줄_현황_출력(설정_아이디)

        # 30분 간격 시트 동기화 + 전용아이디 재등록
        if (datetime.datetime.now() - _마지막_시트_동기화).total_seconds() >= 1800:
            _스케줄_시트_동기화_비동기()
            try:
                _전용아이디_시트_기록()
            except Exception as _uid_re_e:
                디버그_로그_저장(f"전용아이디 시트 주기 재등록 오류 (무시): {_uid_re_e}")
            _마지막_시트_동기화 = datetime.datetime.now()

        time.sleep(30)


def _공용PC_작업_행_가져오기(폴더명):
    """공용 PC: 스케줄 기준 키워드 생성 후 로컬 작업큐에서 항목 가져오기 (30초 간격)"""
    global _지명키워드_캐시_df
    print("공용 PC: 예약시간 도래 시 키워드생성 실행 후 포스팅합니다. (30초 간격 확인)")
    대기_횟수 = 0
    _마지막_시트_동기화 = datetime.datetime.now()

    while True:
        _스케줄_주기_갱신_확인()
        if _스케줄_계획_금지시간() and not _로컬_작업_스케줄:
            대기_횟수 += 1
            if 대기_횟수 == 1 or 대기_횟수 % 4 == 0:
                print(f"23시~1시 - 스케줄 갱신 대기 중... ({대기_횟수}회, 30초 간격)")
            time.sleep(30)
            continue

        _공용PC_스케줄_재계획_시도()

        if _예약시간_도래_스켈레톤_있음(None, None):
            _전용아이디_목록_가져오기()
            kw_item = _로컬_스케줄_다음_키워드생성_항목()
            _예약_키워드생성_실행(kw_item['사용아이디'] if kw_item else None, kw_item)
            time.sleep(5)
            continue

        idx, q_item = _로컬_작업큐_항목_선택(폴더명)
        if q_item is not None:
            _로컬_작업큐_폴더_업데이트(idx, 폴더명)
            _캐시_설정_로컬(q_item, idx)
            print(f"작업 항목 확인 완료 (큐 인덱스 {idx}, 대기 {대기_횟수}회)")
            return

        대기_횟수 += 1
        if 대기_횟수 == 1 or 대기_횟수 % _스케줄_현황_출력_간격 == 0:
            _로컬_스케줄_현황_출력()

        # 30분 간격 시트 동기화
        if (datetime.datetime.now() - _마지막_시트_동기화).total_seconds() >= 1800:
            _스케줄_시트_동기화_비동기()
            _마지막_시트_동기화 = datetime.datetime.now()

        time.sleep(30)


print("=== 포스팅.py 시작 ===")
print("지명키워드 구글시트에서 데이터를 읽어 포스팅을 시작합니다.")

_작업_허용_아이피_대기()

디버그_로그_저장(
    f"=== 프로그램 시작 === "
    f"폴더={os.path.basename(os.getcwd())}, "
    f"사용아이디={설정_사용아이디!r}, "
    f"Python={sys.version.split()[0]}, "
    f"PID={os.getpid()}"
)

try:
    _전용아이디_시트_기록()
except Exception as _uid_sheet_e:
    오류_로그_저장(f"전용아이디 시트 기록 오류: {_uid_sheet_e}")
    print(f"전용아이디 시트 기록 중 오류 (포스팅은 계속 진행): {_uid_sheet_e}")

try:
    if not _스케줄_파일_불러오기():
        _작업스케줄_일일_등록()
except Exception as _sched_e:
    오류_로그_저장(f"작업스케줄 등록 오류: {_sched_e}")
    print(f"작업스케줄 등록 중 오류 (포스팅은 계속 진행): {_sched_e}")

# === 지명키워드 구글시트: 전용/공용 PC 분기 ===
try:
    _폴더명 = os.path.basename(os.getcwd())
    _전용_모드 = bool(설정_사용아이디) and str(설정_사용아이디).strip() != '*'

    if _전용_모드:
        _전용PC_작업_행_준비(설정_사용아이디.strip(), _폴더명)
    else:
        if not 설정_사용아이디 or str(설정_사용아이디).strip() == '*':
            print("공용 PC 모드: 지명키워드가 채워진 행에서 작업합니다.")
        _공용PC_작업_행_가져오기(_폴더명)
except SystemExit:
    raise
except Exception as _e:
    중요_작업_로그_저장(f"오류: 지명키워드 구글시트 읽기 실패 - 프로그램 종료: {_e}")
    print(f"오류: 지명키워드 구글시트 읽기/예약 실패 - {_e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

if _지명키워드_캐시_df is None or _지명키워드_캐시_df.empty:
    print("오류: 지명키워드 데이터가 없습니다.")
    sys.exit(1)

# === 원고 재사용 모드 비활성화 (실패·대기 재시작 시에도 IP/제목/원고 재생성) ===
_재사용_키워드 = _현재_작업_지명키워드()
_원고_재사용_모드 = False
if _포스팅만_재시도_플래그_확인():
    _포스팅만_재시도_플래그_해제()
    print("재시도 플래그 해제 - 원고 재사용 없이 제목·원고를 새로 생성합니다.")
    중요_작업_로그_저장("원고 재사용 비활성 - 재시도 플래그 해제, 제목·원고 재생성")

# === IP 교체 시스템 실행 ===
_MAX_IP_RETRIES = 10
_INITIAL_DELAY = 30
_DELAY_INCREMENT = 30
_ip_success = (설정_아이피교체 != 1) or _원고_재사용_모드
if _원고_재사용_모드:
    print("기존 원고 재사용 모드이므로 IP 교체를 건너뜁니다.")
elif 설정_아이피교체 != 1:
    if 설정_작업_허용_아이피:
        print(f"[설정.xlsx] 아이피교체={설정_작업_허용_아이피} (고정 IP) - IP 교체를 건너뜁니다.")
    else:
        print("[설정.xlsx] 아이피교체 OFF - IP 교체를 건너뜁니다.")
else:
    print("\n지명키워드 파일 확인 후 IP 교체를 실행합니다...")
    중요_작업_로그_저장("포스팅.py 시작 - IP 교체 시스템 시작")
    print(f"IP 교체를 성공할 때까지 시도합니다. (최대 {_MAX_IP_RETRIES}회)")
_retry = 0
while not _ip_success and _retry < _MAX_IP_RETRIES:
    _retry += 1
    print(f"\nIP 교체 시도 {_retry}번째...")
    중요_작업_로그_저장(f"IP 교체 {_retry}번째 시도 시작")
    try:
        if auto_ip_change_system():
            print("IP 교체 성공!")
            중요_작업_로그_저장(f"IP 교체 성공 (시도 {_retry}번째)")
            _ip_success = True
        else:
            print(f"IP 교체 {_retry}번째 시도 실패")
            if _retry < _MAX_IP_RETRIES:
                _wait = _INITIAL_DELAY + (_retry - 1) * _DELAY_INCREMENT
                print(f"{_wait}초 후 재시도합니다... ({_retry}/{_MAX_IP_RETRIES})")
                time.sleep(_wait)
            else:
                print("최대 재시도 횟수 도달. 프로그램을 종료합니다.")
                sys.exit(1)
    except Exception as _e2:
        print(f"IP 교체 오류: {_e2}")
        if _retry < _MAX_IP_RETRIES:
            _wait = _INITIAL_DELAY + (_retry - 1) * _DELAY_INCREMENT
            print(f"{_wait}초 후 재시도합니다...")
            time.sleep(_wait)
        else:
            print("최대 재시도 횟수 도달. 프로그램을 종료합니다.")
            sys.exit(1)

if not _ip_success:
    print("IP 교체 실패로 프로그램이 종료됩니다.")
    sys.exit(1)
elif 설정_아이피교체 == 1:
    print("IP 교체 성공! 블로그 제목 생성 단계로 진행합니다.")

# ==============================================================================
# 이하: 블로그 제목 생성 → 원고 생성 → 포스팅 루프
# (뷰순위 체크 제외)
# ==============================================================================

# 네이버 검색 결과 분석 프로그램
# 돌쇠가 만든 셀레니움 네이버 검색 프로그램입니다!

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import time
import urllib.parse
import os
import subprocess
import sys

def 다음_스크립트_실행(스크립트명):
    """다음 스크립트를 실행하는 함수"""
    try:
        스크립트_경로 = resource_path(스크립트명)
        if os.path.exists(스크립트_경로):
            print(f"{스크립트명} 파일을 찾았습니다. 실행을 시작합니다...")
            # 작업 디렉토리를 현재 스크립트 디렉토리로 변경
            subprocess.run([sys.executable, 스크립트_경로], 
                         cwd=os.path.dirname(os.path.abspath(__file__)), 
                         check=True)
            print(f"{스크립트명} 실행이 완료되었습니다!")
        else:
            print(f"오류: {스크립트_경로} 파일을 찾을 수 없습니다.")
            
    except subprocess.CalledProcessError as e:
        print(f"{스크립트명} 실행 중 오류 발생: {e}")
    except Exception as e:
        print(f"{스크립트명} 실행 중 예상치 못한 오류: {e}")



# ================== 네이버 랜덤 브라우징 시스템 시작 ==================
def 새탭_방지_스크립트_주입(driver):
    """새 탭 열기를 완전히 방지하는 JavaScript 코드 주입"""
    try:
        prevent_new_tab_script = """
        // 새 탭/창 열기 완전 차단
        (function() {
            // window.open 함수 오버라이드
            window.open = function() {
                console.log('새 탭 열기가 차단되었습니다.');
                return window;
            };
            
            // target="_blank" 속성 제거 및 클릭 이벤트 처리
            function preventNewTab() {
                // 모든 링크의 target 속성 제거
                const links = document.querySelectorAll('a[target="_blank"], a[target="blank"]');
                links.forEach(link => {
                    link.removeAttribute('target');
                    link.setAttribute('target', '_self');
                });
                
                // 새로 생성되는 링크도 처리
                const observer = new MutationObserver(function(mutations) {
                    mutations.forEach(function(mutation) {
                        mutation.addedNodes.forEach(function(node) {
                            if (node.nodeType === 1) { // Element node
                                if (node.tagName === 'A') {
                                    if (node.hasAttribute('target')) {
                                        node.removeAttribute('target');
                                        node.setAttribute('target', '_self');
                                    }
                                }
                                // 하위 링크들도 처리
                                const subLinks = node.querySelectorAll ? node.querySelectorAll('a[target]') : [];
                                subLinks.forEach(link => {
                                    link.removeAttribute('target');
                                    link.setAttribute('target', '_self');
                                });
                            }
                        });
                    });
                });
                
                observer.observe(document.body, {
                    childList: true,
                    subtree: true
                });
            }
            
            // DOM 로드 완료 후 실행
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', preventNewTab);
            } else {
                preventNewTab();
            }
            
            // 주기적으로 새 링크 체크
            setInterval(preventNewTab, 1000);
            
        })();
        """
        
        driver.execute_script(prevent_new_tab_script)
        print("새 탭 방지 스크립트가 주입되었습니다.")
        
    except Exception as e:
        print(f"새 탭 방지 스크립트 주입 중 오류: {e}")

def 랜덤_선택자_클릭(driver, 선택자_그룹, 그룹_이름):
    """지정된 선택자 그룹에서 랜덤으로 하나를 선택하여 클릭 (개선된 버전)"""
    try:
        print(f"\n🎯 {그룹_이름} 선택자 그룹에서 랜덤 클릭을 시도합니다...")
        
        # 모든 선택자를 시도해서 실제로 존재하는 요소들 찾기
        사용가능한_요소들 = []
        
        for 선택자 in 선택자_그룹:
            try:
                # :contains() 선택자는 Selenium에서 지원하지 않으므로 XPath로 변환
                if ":contains(" in 선택자:
                    텍스트 = 선택자.split(":contains('")[1].split("')")[0]
                    xpath_선택자 = f"//a[contains(text(), '{텍스트}')]"
                    요소들 = driver.find_elements(By.XPATH, xpath_선택자)
                else:
                    요소들 = driver.find_elements(By.CSS_SELECTOR, 선택자)
                
                for 요소 in 요소들:
                    if 요소.is_displayed() and 요소.is_enabled():
                        href = 요소.get_attribute("href")
                        if href and "naver.com" in href:
                            사용가능한_요소들.append((요소, 선택자, href))
                            
            except Exception as e:
                print(f"  선택자 '{선택자[:30]}...' 확인 중 오류: {e}")
                continue
        
        if not 사용가능한_요소들:
            print(f"❌ {그룹_이름}에서 클릭 가능한 요소를 찾지 못했습니다.")
            
            # 대체 방법: 네이버 메인 페이지의 일반적인 링크들 시도
            print("🔄 대체 방법으로 일반 링크들을 시도합니다...")
            대체_선택자들 = [
                "a[href*='news.naver.com']",
                "a[href*='shopping.naver.com']", 
                "a[href*='cafe.naver.com']",
                "a[href*='blog.naver.com']",
                ".nav_item a",
                ".service_tab a",
                "#gnb a"
            ]
            
            for 대체_선택자 in 대체_선택자들:
                try:
                    요소들 = driver.find_elements(By.CSS_SELECTOR, 대체_선택자)
                    for 요소 in 요소들[:3]:  # 최대 3개만 시도
                        if 요소.is_displayed() and 요소.is_enabled():
                            href = 요소.get_attribute("href")
                            if href and "naver.com" in href:
                                사용가능한_요소들.append((요소, 대체_선택자, href))
                                break
                    if 사용가능한_요소들:
                        break
                except:
                    continue
        
        if not 사용가능한_요소들:
            print(f"❌ 모든 시도가 실패했습니다. {그룹_이름} 클릭을 건너뜁니다.")
            return False
        
        # 랜덤으로 요소 선택
        선택된_요소, 사용된_선택자, href = random.choice(사용가능한_요소들)
        print(f"✅ 클릭할 요소를 찾았습니다!")
        print(f"  선택자: {사용된_선택자[:50]}...")
        print(f"  링크: {href[:60]}...")
        
        # 요소 클릭 시도
        try:
            # 스크롤해서 요소가 보이도록 함
            driver.execute_script("arguments[0].scrollIntoView(true);", 선택된_요소)
            time.sleep(1)
            
            # 부모 링크 요소 찾기
            parent_link = 선택된_요소
            try:
                if 선택된_요소.tag_name in ['span', 'strong', 'h3', 'div']:
                    parent_link = 선택된_요소.find_element(By.XPATH, "./ancestor::a[1]")
                    print("  부모 링크 요소를 사용합니다.")
                elif 선택된_요소.tag_name == 'a':
                    parent_link = 선택된_요소
                    print("  링크 요소를 직접 사용합니다.")
            except:
                parent_link = 선택된_요소
            
            # 강력한 새 탭 방지 처리
            driver.execute_script("""
                arguments[0].removeAttribute('target');
                arguments[0].setAttribute('target', '_self');
                arguments[0].onclick = null;
                arguments[0].addEventListener('click', function(e) {
                    e.preventDefault();
                    if (this.href) {
                        window.location.href = this.href;
                    }
                });
            """, parent_link)
            
            # 클릭 실행
            driver.execute_script("arguments[0].click();", parent_link)
            time.sleep(random.uniform(3, 5))
            
            # 클릭 성공 확인
            새로운_url = driver.current_url
            if 새로운_url != "https://www.naver.com":
                print(f"✅ {그룹_이름} 선택자 클릭이 성공했습니다!")
                print(f"  새 페이지: {새로운_url[:60]}...")
                return True
            else:
                print(f"⚠️ 클릭했지만 페이지가 변경되지 않았습니다.")
                return False
                
        except Exception as e:
            print(f"❌ {그룹_이름} 클릭 중 오류: {e}")
            return False
            
    except Exception as e:
        print(f"❌ {그룹_이름} 전체 과정에서 오류: {e}")
        return False

def 자연스러운_스크롤(driver):
    """사람처럼 자연스러운 스크롤 동작"""
    try:
        # 스크롤 방향과 거리를 랜덤하게 결정
        스크롤_타입 = random.choice(['아래로', '위로', '아래로_크게', '위로_작게'])
        
        if 스크롤_타입 == '아래로':
            스크롤_거리 = random.randint(300, 600)
            driver.execute_script(f"window.scrollBy(0, {스크롤_거리});")
            print(f"아래로 {스크롤_거리}px 스크롤")
            
        elif 스크롤_타입 == '위로':
            스크롤_거리 = random.randint(200, 400)
            driver.execute_script(f"window.scrollBy(0, -{스크롤_거리});")
            print(f"위로 {스크롤_거리}px 스크롤")
            
        elif 스크롤_타입 == '아래로_크게':
            스크롤_거리 = random.randint(800, 1200)
            driver.execute_script(f"window.scrollBy(0, {스크롤_거리});")
            print(f"크게 아래로 {스크롤_거리}px 스크롤")
            
        elif 스크롤_타입 == '위로_작게':
            스크롤_거리 = random.randint(100, 250)
            driver.execute_script(f"window.scrollBy(0, -{스크롤_거리});")
            print(f"조금 위로 {스크롤_거리}px 스크롤")
        
        # 스크롤 후 자연스러운 대기
        time.sleep(random.uniform(1, 3))
        
    except Exception as e:
        print(f"스크롤 중 오류: {e}")

def 페이지_내_링크_클릭(driver):
    """페이지 내에서 랜덤 링크 클릭하여 더 깊이 들어가기"""
    try:
        print("페이지 내 링크를 찾아서 클릭합니다...")
        
        # 다양한 링크 선택자들
        링크_선택자들 = [
            "a[href*='/read']",  # 글 읽기 링크
            "a[href*='/article']",  # 기사 링크
            "a[href*='/post']",  # 포스트 링크
            "a[href*='/view']",  # 보기 링크
            "a.list_title",  # 제목 링크
            "a.title",  # 제목 링크
            ".list_item a",  # 리스트 아이템 링크
            ".item_title a",  # 아이템 제목 링크
            ".news_tit",  # 뉴스 제목
            ".cafe_tit",  # 카페 제목
        ]
        
        links = []
        for selector in 링크_선택자들:
            try:
                found_links = driver.find_elements(By.CSS_SELECTOR, selector)
                links.extend(found_links)
            except:
                continue
        
        # 일반적인 a 태그도 추가로 수집
        try:
            all_links = driver.find_elements(By.TAG_NAME, "a")
            # 클릭 가능하고 href가 있는 링크만 필터링
            clickable_links = [link for link in all_links if 
                             link.is_displayed() and 
                             link.get_attribute("href") and 
                             not link.get_attribute("href").startswith("javascript") and
                             "naver.com" in link.get_attribute("href")]
            links.extend(clickable_links[:15])  # 상위 15개만 추가
        except:
            pass
        
        if links:
            # 중복 제거
            unique_links = list(set(links))
            
            if unique_links:
                # 랜덤하게 링크 선택
                selected_link = random.choice(unique_links[:10])  # 상위 10개 중에서 선택
                href = selected_link.get_attribute("href")
                
                if href and "naver.com" in href:
                    print(f"선택된 링크: {href[:60]}...")
                    
                    # 새 탭 방지 처리
                    driver.execute_script("""
                        arguments[0].removeAttribute('target');
                        arguments[0].setAttribute('target', '_self');
                        arguments[0].onclick = null;
                        arguments[0].addEventListener('click', function(e) {
                            e.preventDefault();
                            if (this.href) {
                                window.location.href = this.href;
                            }
                        });
                    """, selected_link)
                    
                    # 클릭 실행
                    driver.execute_script("arguments[0].click();", selected_link)
                    print("✅ 페이지 내 링크 클릭 성공!")
                    
                    # 링크 클릭 후 페이지 로딩 대기
                    time.sleep(random.uniform(3, 6))
                    
                    return True
        
        print("❌ 클릭 가능한 링크를 찾지 못했습니다.")
        return False
        
    except Exception as e:
        print(f"페이지 내 링크 클릭 중 오류: {e}")
        return False

def 팝업창_정리(driver):
    """현재 페이지에서 열려있는 팝업창들을 확인하고 닫는 함수"""
    try:
        print("🔍 팝업창들을 확인하고 정리합니다...")
        
        # 공통 재시도 유틸: 드라이버 통신 오류 흡수
        def with_driver_retry(op, desc="driver-op", retries=3, delay=2):
            last_e = None
            for r in range(retries):
                try:
                    return op()
                except Exception as e:
                    last_e = e
                    # 세션/연결 끊김/타임아웃류는 잠시 대기 후 재시도
                    if any(k in str(e) for k in [
                        "Read timed out",
                        "Max retries exceeded",
                        "Connection aborted",
                        "ConnectionResetError",
                        "invalid session id",
                        "Disconnected"
                    ]):
                        print(f"⚠️ {desc} 재시도 {r+1}/{retries}: {e}")
                        time.sleep(delay)
                        continue
                    # 기타 오류는 바로 전파
                    raise
            # 모두 실패 시 마지막 예외 전파
            raise last_e

        # 현재 창의 핸들 저장
        메인_창_핸들 = with_driver_retry(lambda: driver.current_window_handle, "get current_window_handle")
        
        # 열려있는 모든 창 핸들 가져오기
        모든_창_핸들 = with_driver_retry(lambda: driver.window_handles, "get window_handles")
        
        if len(모든_창_핸들) > 1:
            print(f"📋 {len(모든_창_핸들)}개의 창이 열려있습니다. 팝업창들을 정리합니다...")
            
            # 메인 창이 아닌 모든 창을 닫기
            for 창_핸들 in 모든_창_핸들:
                if 창_핸들 != 메인_창_핸들:
                    try:
                        # 팝업창으로 전환
                        with_driver_retry(lambda: driver.switch_to.window(창_핸들), "switch_to popup")
                        제목 = with_driver_retry(lambda: driver.title, "get title")
                        print(f"🔒 팝업창 '{제목}'을 닫습니다...")
                        
                        # 팝업창 닫기
                        with_driver_retry(lambda: driver.close(), "close popup")
                        
                    except Exception as e:
                        print(f"⚠️ 팝업창 닫기 중 오류: {e}")
                        continue
            
            # 메인 창으로 다시 전환
            with_driver_retry(lambda: driver.switch_to.window(메인_창_핸들), "switch_to main")
            print("✅ 메인 창으로 돌아왔습니다.")
            
        else:
            print("✅ 팝업창이 없습니다.")
        
        # === 추가 탭 정리 (새로 추가된 기능) ===
        print("🔍 추가 탭들을 확인하고 정리합니다...")
        try:
            # 현재 탭의 URL 확인
            현재_URL = with_driver_retry(lambda: driver.current_url, "get current_url")
            print(f"현재 탭 URL: {현재_URL}")
            
            # 모든 탭 핸들 다시 가져오기 (팝업창 정리 후)
            남은_탭들 = with_driver_retry(lambda: driver.window_handles, "get window_handles (after popup)")
            
            if len(남은_탭들) > 1:
                print(f"📋 {len(남은_탭들)}개의 탭이 남아있습니다. 추가 탭들을 정리합니다...")
                
                # 메인 탭이 아닌 모든 탭을 닫기
                for 탭_핸들 in 남은_탭들:
                    if 탭_핸들 != 메인_창_핸들:
                        try:
                            # 탭으로 전환
                            with_driver_retry(lambda: driver.switch_to.window(탭_핸들), "switch_to tab")
                            탭_URL = with_driver_retry(lambda: driver.current_url, "get tab url")
                            제목 = with_driver_retry(lambda: driver.title, "get title")
                            print(f"🔒 추가 탭 '{제목}' ({탭_URL})을 닫습니다...")
                            
                            # 탭 닫기
                            with_driver_retry(lambda: driver.close(), "close tab")
                            
                        except Exception as e:
                            print(f"⚠️ 추가 탭 닫기 중 오류: {e}")
                            continue
                
                # 메인 탭으로 다시 전환
                with_driver_retry(lambda: driver.switch_to.window(메인_창_핸들), "switch_to main(after tabs)")
                print("✅ 메인 탭으로 돌아왔습니다.")
                
            else:
                print("✅ 추가 탭이 없습니다.")
                
        except Exception as e:
            print(f"⚠️ 추가 탭 정리 중 오류: {e}")
            
        # 현재 페이지에서 모달이나 알림창 닫기 시도
        모달_닫기_시도(driver)
        
        return True
        
    except Exception as e:
        print(f"❌ 팝업창 정리 중 오류 발생: {e}")
        return False

def 모달_닫기_시도(driver):
    """현재 페이지에서 모달이나 알림창을 닫는 함수"""
    try:
        # 일반적인 모달 닫기 버튼들
        모달_닫기_선택자들 = [
            ".modal-close",
            ".close",
            ".btn-close", 
            ".popup-close",
            ".alert-close",
            ".notification-close",
            "[data-dismiss='modal']",
            "[aria-label='Close']",
            ".se-popup-button-cancel",
            ".se-help-panel-close-button",
            ".se-popup-button",
            ".se-popup-close",
            ".se-notification-close"
        ]
        
        for 선택자 in 모달_닫기_선택자들:
            try:
                요소들 = driver.find_elements(By.CSS_SELECTOR, 선택자)
                for 요소 in 요소들:
                    if 요소.is_displayed():
                        print(f"🔒 모달 닫기 버튼 '{선택자}' 클릭")
                        요소.click()
                        time.sleep(1)
            except:
                continue
        
        # ESC 키로 모달 닫기 시도
        try:
            ActionChains(driver).send_keys(Keys.ESCAP).perform()
            time.sleep(1)
        except:
            pass
            
        print("✅ 모달/알림창 정리 완료")
        
    except Exception as e:
        print(f"⚠️ 모달 닫기 중 오류: {e}")

def 네이버_랜덤_브라우징(driver, 브라우징_시간_분=None):
    """네이버에서 랜덤 선택자들을 순서대로 클릭"""
    try:
        print("\n🌐 네이버 랜덤 브라우징을 시작합니다...")
        
        # 현재 페이지가 네이버인지 확인, 아니면 네이버 메인으로 이동
        current_url = driver.current_url
        if "naver.com" not in current_url:
            print("네이버 메인 페이지로 이동합니다...")
            driver.get("https://www.naver.com")
            
            # 페이지 로딩 완료 대기
            try:
                wait = WebDriverWait(driver, 15)
                wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                print("네이버 메인 페이지 로딩 완료")
            except Exception as e:
                print(f"페이지 로딩 대기 중 오류 (계속 진행): {e}")
            
            time.sleep(random.uniform(3, 5))
        
        # 새 탭 방지 스크립트 주입
        새탭_방지_스크립트_주입(driver)
        time.sleep(2)
        
        # A선택자 그룹 (뉴스, 블로그, 카페 관련)
        A선택자_그룹 = [
            "a[href*='news.naver.com']",
            "a[href*='blog.naver.com']", 
            "a[href*='cafe.naver.com']",
            ".service_area a[href*='news']",
            ".service_area a[href*='blog']",
            ".service_area a[href*='cafe']",
            "#shortcutArea a",
            ".shortcut_item a",
            ".service_list a",
        ]
        
        # B선택자 그룹 (쇼핑, 웹툰, 증권 관련)
        B선택자_그룹 = [
            "a[href*='shopping.naver.com']",
            "a[href*='comic.naver.com']",
            "a[href*='finance.naver.com']",
            ".service_area a[href*='shopping']",
            ".service_area a[href*='comic']",
            ".service_area a[href*='finance']",
        ]
        
        # 브라우징 시간 설정 (기본값: 1-2분)
        if 브라우징_시간_분 is None:
            전체_세션_시간 = random.randint(60, 120)  # 1-2분 (초)
        else:
            전체_세션_시간 = 브라우징_시간_분 * 60
            
        print(f"🕐 브라우징 시간: {전체_세션_시간//60}분 {전체_세션_시간%60}초")
        
        세션_시작_시간 = time.time()
        세션_카운트 = 0
        
        # 설정된 시간 동안 계속 브라우징
        while time.time() - 세션_시작_시간 < 전체_세션_시간:
            세션_카운트 += 1
            남은_시간 = 전체_세션_시간 - (time.time() - 세션_시작_시간)
            
            if 남은_시간 < 15:  # 15초 미만 남으면 종료
                print(f"⏰ 남은 시간이 {남은_시간:.0f}초 미만이므로 브라우징을 종료합니다.")
                break
            
            print(f"\n🔄 === 브라우징 라운드 {세션_카운트} === (남은 시간: {남은_시간//60:.0f}분 {남은_시간%60:.0f}초)")
            
            # A그룹과 B그룹 중 랜덤 선택
            모든_선택자_그룹 = A선택자_그룹 + B선택자_그룹
            선택된_그룹_타입 = random.choice(["A그룹", "B그룹", "혼합"])
            
            if 선택된_그룹_타입 == "A그룹":
                선택된_그룹 = A선택자_그룹
            elif 선택된_그룹_타입 == "B그룹":
                선택된_그룹 = B선택자_그룹
            else:  # 혼합
                선택된_그룹 = 모든_선택자_그룹
            
            print(f"🎯 {선택된_그룹_타입} 선택자에서 랜덤 탐색")
            
            # 랜덤 선택자 클릭
            if 랜덤_선택자_클릭(driver, 선택된_그룹, f"라운드{세션_카운트}-{선택된_그룹_타입}"):
                # 간단한 브라우징 (스크롤, 링크 클릭)
                브라우징_동작_수 = random.randint(2, 4)
                for i in range(브라우징_동작_수):
                    동작 = random.choice(['스크롤', '링크클릭', '대기'])
                    
                    if 동작 == '스크롤':
                        자연스러운_스크롤(driver)
                    elif 동작 == '링크클릭':
                        페이지_내_링크_클릭(driver)
                        time.sleep(random.uniform(2, 4))
                    elif 동작 == '대기':
                        대기_시간 = random.uniform(2, 5)
                        print(f"콘텐츠 감상 중... {대기_시간:.1f}초")
                        time.sleep(대기_시간)
                
                print(f"🏁 라운드 {세션_카운트} 완료!")
                
                # 다음 라운드까지 잠시 대기 (마지막 라운드가 아닐 때만)
                현재_경과_시간 = time.time() - 세션_시작_시간
                if 현재_경과_시간 < 전체_세션_시간 - 15:  # 15초 이상 남았을 때만 돌아가기
                    print("🏠 네이버 메인으로 돌아갑니다...")
                    driver.get("https://www.naver.com")
                    
                    # 페이지 로딩 완료 대기
                    try:
                        wait = WebDriverWait(driver, 15)
                        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                        print("네이버 메인 페이지 로딩 완료")
                    except Exception as e:
                        print(f"페이지 로딩 대기 중 오류 (계속 진행): {e}")
                    
                    time.sleep(random.uniform(2, 3))
                    새탭_방지_스크립트_주입(driver)
                    
                    대기_시간 = random.uniform(1, 3)
                    print(f"⏱️ 다음 라운드까지 {대기_시간:.1f}초 대기...")
                    time.sleep(대기_시간)
            else:
                # 선택자 클릭 실패 시 짧은 대기 후 다시 시도
                print("⚠️ 선택자 클릭 실패, 짧은 대기 후 계속...")
                time.sleep(random.uniform(2, 5))
        
        print("\n✅ 네이버 랜덤 브라우징이 완료되었습니다!")
        return True
        
    except Exception as e:
        print(f"네이버 랜덤 브라우징 중 오류: {e}")
        return False
# ================== 네이버 랜덤 브라우징 시스템 끝 ==================

# ================== 서로이웃 작업 시스템 시작 ==================
class 본인_이웃수_초과_예외(Exception):
    """본인의 이웃수가 5,000명을 초과했을 때 발생하는 예외"""
    pass

def 구글스프레드시트_서로이웃작업_확인(아이디):
    """구글 스프레드시트에서 특정 아이디의 서로이웃작업 값을 확인하는 함수
    
    Returns:
        int: 서로이웃작업 값 (0이면 서로이웃 작업 필요, 1 이상이면 랜덤브라우징 진행)
             오류 시 기본값 1 반환 (랜덤브라우징 진행)
    """
    import socket
    # JSON 파일 존재 여부 확인
    json_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(json_파일_경로):
        print("❌ 오류: khon21-534690057aec.json 파일을 찾을 수 없습니다.")
        return 1  # 파일이 없으면 랜덤브라우징 진행
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                if 시도_횟수 > 0:
                    print(f"🔄 구글 스프레드시트 연결 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 인증 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(json_파일_경로, scopes=scope)
                gc = gspread_authorize_with_timeout(creds, timeout=25)
                
                # 계정정보 스프레드시트 열기
                spreadsheet_id = '1JioOQCAlWxCpQnsr43UcQt9gWvCGDeFYlwlmT-m8B6s'
                spreadsheet = gc.open_by_key(spreadsheet_id)
                
                # 첫 번째 워크시트 선택
                worksheet = spreadsheet.get_worksheet(0)
                
                # 모든 데이터 가져오기
                all_values = worksheet.get_all_values()
                
                if len(all_values) < 2:
                    print("계정정보 구글 스프레드시트에 데이터가 없습니다.")
                    return 1  # 데이터가 없으면 랜덤브라우징 진행
                
                # 헤더와 데이터 분리
                headers = all_values[0]
                data = all_values[1:]
                
                # 아이디 컬럼 인덱스 찾기
                if '아이디' not in headers:
                    print("계정정보 구글 스프레드시트에 '아이디' 컬럼이 없습니다.")
                    return 1  # 컬럼이 없으면 랜덤브라우징 진행
                
                아이디_컬럼_인덱스 = headers.index('아이디')
                
                # 서로이웃작업 컬럼 인덱스 찾기
                if '서로이웃작업' not in headers:
                    print("계정정보 구글 스프레드시트에 '서로이웃작업' 컬럼이 없습니다.")
                    return 1  # 컬럼이 없으면 랜덤브라우징 진행
                
                서로이웃작업_컬럼_인덱스 = headers.index('서로이웃작업')
                
                # 해당 아이디 찾기
                for row_idx, row_data in enumerate(data, start=2):  # 2부터 시작 (헤더 다음 행)
                    if len(row_data) > 아이디_컬럼_인덱스 and row_data[아이디_컬럼_인덱스] == 아이디:
                        # 서로이웃작업 값 가져오기
                        if len(row_data) > 서로이웃작업_컬럼_인덱스:
                            서로이웃작업_값 = str(row_data[서로이웃작업_컬럼_인덱스]).strip()
                            
                            # 값이 비어있거나 숫자가 아니면 0으로 처리
                            try:
                                서로이웃작업_숫자 = int(서로이웃작업_값) if 서로이웃작업_값 else 0
                            except ValueError:
                                서로이웃작업_숫자 = 0
                            
                            print(f"아이디 '{아이디}'의 서로이웃작업 값: {서로이웃작업_숫자}")
                            return 서로이웃작업_숫자
                        else:
                            print(f"아이디 '{아이디}'의 서로이웃작업 컬럼이 비어있습니다.")
                            return 0  # 값이 없으면 서로이웃 작업 진행
                
                print(f"아이디 '{아이디}'를 계정정보 구글 스프레드시트에서 찾을 수 없습니다.")
                return 1  # 아이디를 찾을 수 없으면 랜덤브라우징 진행
                
            except (socket.timeout, TimeoutError) as e:
                print(f"⚠️ 타임아웃 발생 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:  # 마지막 시도가 아니면
                    print("⏳ 30초 대기 후 재시도합니다...")
                    time.sleep(30)
                else:
                    print("❌ 최대 재시도 횟수에 도달했습니다.")
                    return 1  # 오류 시 랜덤브라우징 진행
            except Exception as e:
                if 시도_횟수 < 9:  # 마지막 시도가 아니면
                    print(f"⚠️ 오류 발생 (시도 {시도_횟수 + 1}/10): {e}")
                    print("⏳ 30초 대기 후 재시도합니다...")
                    time.sleep(30)
                else:
                    print(f"❌ 구글 스프레드시트 서로이웃작업 확인 실패 (최대 재시도 도달): {e}")
                    return 1  # 오류 시 랜덤브라우징 진행
        
        return 1  # 오류 시 랜덤브라우징 진행
        
    finally:
        # 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def 구글스프레드시트_서로이웃작업_업데이트(아이디):
    """구글 스프레드시트에서 특정 아이디의 서로이웃작업 값을 +1 업데이트하는 함수"""
    import socket
    # JSON 파일 존재 여부 확인
    json_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(json_파일_경로):
        print("❌ 오류: khon21-534690057aec.json 파일을 찾을 수 없습니다.")
        return False
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                if 시도_횟수 > 0:
                    print(f"🔄 구글 스프레드시트 연결 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 인증 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(json_파일_경로, scopes=scope)
                gc = gspread_authorize_with_timeout(creds, timeout=25)
                
                # 계정정보 스프레드시트 열기
                spreadsheet_id = '1JioOQCAlWxCpQnsr43UcQt9gWvCGDeFYlwlmT-m8B6s'
                spreadsheet = gc.open_by_key(spreadsheet_id)
                
                # 첫 번째 워크시트 선택
                worksheet = spreadsheet.get_worksheet(0)
                
                # 모든 데이터 가져오기
                all_values = worksheet.get_all_values()
                
                if len(all_values) < 2:
                    print("계정정보 구글 스프레드시트에 데이터가 없습니다.")
                    return False
                
                # 헤더와 데이터 분리
                headers = all_values[0]
                data = all_values[1:]
                
                # 아이디 컬럼 인덱스 찾기
                if '아이디' not in headers:
                    print("계정정보 구글 스프레드시트에 '아이디' 컬럼이 없습니다.")
                    return False
                
                아이디_컬럼_인덱스 = headers.index('아이디')
                
                # 서로이웃작업 컬럼 인덱스 찾기 (없으면 추가)
                if '서로이웃작업' not in headers:
                    # 헤더에 서로이웃작업 컬럼 추가
                    worksheet.update_cell(1, len(headers) + 1, '서로이웃작업')
                    서로이웃작업_컬럼_인덱스 = len(headers)
                    # 모든 데이터 행에 서로이웃작업 0 추가
                    for row_idx in range(2, len(all_values) + 1):
                        worksheet.update_cell(row_idx, 서로이웃작업_컬럼_인덱스 + 1, 0)
                else:
                    서로이웃작업_컬럼_인덱스 = headers.index('서로이웃작업')
                
                # 해당 아이디 찾기
                for row_idx, row_data in enumerate(data, start=2):  # 2부터 시작 (헤더 다음 행)
                    if len(row_data) > 아이디_컬럼_인덱스 and row_data[아이디_컬럼_인덱스] == 아이디:
                        # 현재 서로이웃작업 값 가져오기
                        current_value = 0
                        if len(row_data) > 서로이웃작업_컬럼_인덱스 and row_data[서로이웃작업_컬럼_인덱스]:
                            try:
                                current_value = int(row_data[서로이웃작업_컬럼_인덱스])
                            except ValueError:
                                current_value = 0
                        
                        # 서로이웃작업 +1
                        new_value = current_value + 1
                        worksheet.update_cell(row_idx, 서로이웃작업_컬럼_인덱스 + 1, new_value)
                        
                        print(f"✅ 아이디 '{아이디}'의 서로이웃작업이 업데이트되었습니다. 현재 서로이웃작업: {new_value}")
                        return True
                
                print(f"아이디 '{아이디}'를 계정정보 구글 스프레드시트에서 찾을 수 없습니다.")
                return False
                
            except (socket.timeout, TimeoutError) as e:
                print(f"⚠️ 타임아웃 발생 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:  # 마지막 시도가 아니면
                    print("⏳ 30초 대기 후 재시도합니다...")
                    time.sleep(30)
                else:
                    print("❌ 최대 재시도 횟수에 도달했습니다.")
                    return False
            except Exception as e:
                if 시도_횟수 < 9:  # 마지막 시도가 아니면
                    print(f"⚠️ 오류 발생 (시도 {시도_횟수 + 1}/10): {e}")
                    print("⏳ 30초 대기 후 재시도합니다...")
                    time.sleep(30)
                else:
                    print(f"❌ 구글 스프레드시트 서로이웃작업 업데이트 실패 (최대 재시도 도달): {e}")
                    return False
        
        return False
        
    finally:
        # 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def 서로이웃_get_current_login_id(driver):
    """네이버 블로그에서 현재 로그인된 사용자 아이디를 가져오는 함수"""
    try:
        print("\n현재 로그인된 아이디 확인 중...")
        
        # 네이버 블로그 메인 페이지 접속
        driver.get("https://blog.naver.com")
        time.sleep(2)
        
        wait = WebDriverWait(driver, 10)
        
        # 여러 방법으로 아이디 추출 시도
        login_id = None
        
        # 방법 1: URL에서 blogId 추출
        try:
            current_url = driver.current_url
            if "blog.naver.com" in current_url:
                # URL에서 blogId 파라미터 찾기
                match = re.search(r'blogId=([^&]+)', current_url)
                if match:
                    login_id = match.group(1)
                    print(f"URL에서 아이디 추출: {login_id}")
        except:
            pass
        
        # 방법 2: 프로필 링크에서 추출
        if not login_id:
            try:
                # 프로필 영역에서 아이디 찾기
                profile_selectors = [
                    "a.profile_area",
                    ".profile_area a",
                    "a[href*='blogId=']",
                    ".area_profile a"
                ]
                
                for selector in profile_selectors:
                    try:
                        profile_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in profile_elements:
                            href = element.get_attribute("href")
                            if href:
                                match = re.search(r'blogId=([^&]+)', href)
                                if match:
                                    login_id = match.group(1)
                                    print(f"프로필 링크에서 아이디 추출: {login_id}")
                                    break
                        if login_id:
                            break
                    except:
                        continue
            except:
                pass
        
        # 방법 3: 블로그 관리 페이지 접속
        if not login_id:
            try:
                driver.get("https://admin.blog.naver.com")
                time.sleep(2)
                current_url = driver.current_url
                match = re.search(r'blogId=([^&]+)', current_url)
                if match:
                    login_id = match.group(1)
                    print(f"관리 페이지에서 아이디 추출: {login_id}")
            except:
                pass
        
        if login_id:
            print(f"확인된 로그인 아이디: {login_id}")
            return login_id
        else:
            print("경고: 로그인 아이디를 자동으로 찾을 수 없습니다.")
            return None
            
    except Exception as e:
        print(f"로그인 아이디 확인 중 오류 발생: {str(e)}")
        return None

def 서로이웃_extract_blog_ids(keyword, driver):
    """네이버 블로그 검색 결과에서 블로그 ID를 추출하는 함수"""
    try:
        import urllib.parse
        
        # URL 생성 (키워드를 URL 인코딩)
        encoded_keyword = urllib.parse.quote(keyword)
        url = f"https://m.blog.naver.com/SectionSearch.naver?searchValue={encoded_keyword}"
        
        print(f"검색 키워드: {keyword}")
        print(f"URL 접속 중: {url}")
        driver.get(url)
        
        # 페이지 로딩 대기
        time.sleep(2)
        
        # 스크롤을 끝까지 이동한 후 0.5초 기다리는 것을 10번 반복
        print("스크롤을 통해 더 많은 결과를 로딩 중...")
        for i in range(10):
            # 페이지 끝까지 스크롤
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
            time.sleep(0.5)
            print(f"스크롤 진행: {i+1}/10")
        
        # 추가 대기 (동적 콘텐츠 로딩을 위해)
        time.sleep(2)
        
        # a.profile_area__riebt 셀렉터로 모든 요소 찾기
        print("블로그 프로필 요소 검색 중...")
        profile_elements = driver.find_elements(By.CSS_SELECTOR, "a.profile_area__riebt")
        print(f"찾은 프로필 요소 개수: {len(profile_elements)}")
        
        # 블로그 ID 추출
        blog_ids = []
        for element in profile_elements:
            try:
                href = element.get_attribute("href")
                if href:
                    # href에서 blogId= 파라미터 값 추출
                    match = re.search(r'blogId=([^&]+)', href)
                    if match:
                        blog_id = match.group(1)
                        blog_ids.append(blog_id)
            except Exception as e:
                print(f"요소 처리 중 오류: {str(e)}")
                continue
        
        # 중복 제거
        unique_blog_ids = list(set(blog_ids))
        
        return unique_blog_ids
        
    except Exception as e:
        print(f"블로그 ID 추출 오류 발생: {str(e)}")
        return []

def 서로이웃_add_buddy_group(driver, login_user_id):
    """블로그 그룹 추가 함수"""
    try:
        # 블로그 그룹 관리 페이지로 이동
        group_manage_url = f"https://admin.blog.naver.com/BuddyGroupManage.naver?blogId={login_user_id}"
        print(f"블로그 그룹 관리 페이지로 이동 중: {group_manage_url}")
        driver.get(group_manage_url)
        time.sleep(2)
        
        wait = WebDriverWait(driver, 10)
        
        # 그룹 추가 버튼 클릭
        print("그룹 추가 버튼 찾는 중...")
        try:
            add_group_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#wrap > div.action2.neighborlist > div.action2_l > span.neighbor_add2 > span > button")))
            time.sleep(0.5)
            add_group_button.click()
            print("그룹 추가 버튼 클릭 완료")
            time.sleep(1)
        except Exception as e:
            print(f"그룹 추가 버튼 클릭 실패: {str(e)}")
            return False
        
        # 그룹명 생성 (오늘 날짜 + 랜덤 숫자)
        today = datetime.datetime.now().strftime("%Y%m%d")
        random_num = random.randint(1, 99)
        group_name = f"{today}{random_num}"
        print(f"그룹명 생성: {group_name}")
        
        # 그룹명 필드에 입력
        print("그룹명 필드 찾는 중...")
        try:
            # 선택자에서 특수문자 이스케이프 처리
            group_name_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#addGroupForm > p > input.txt_3.__lengthForEng\\(2\\~100\\).__lengthForKor\\(2\\~100\\)")))
            time.sleep(0.5)
            
            # send_keys로 값 입력
            group_name_field.click()
            time.sleep(0.3)
            group_name_field.clear()
            time.sleep(0.3)
            group_name_field.send_keys(group_name)
            print(f"그룹명 입력 완료: {group_name}")
            time.sleep(0.5)
        except Exception as e:
            print(f"그룹명 입력 실패: {str(e)}")
            # 다른 선택자 시도
            try:
                group_name_field = driver.find_element(By.CSS_SELECTOR, "#addGroupForm input[type='text']")
                time.sleep(0.5)
                group_name_field.click()
                time.sleep(0.3)
                group_name_field.clear()
                time.sleep(0.3)
                group_name_field.send_keys(group_name)
                print(f"그룹명 입력 완료 (대체 방식): {group_name}")
                time.sleep(0.5)
            except Exception as e2:
                print(f"그룹명 입력 실패 (대체 방식): {str(e2)}")
                return False
        
        # 만들기 버튼 클릭
        print("만들기 버튼 찾는 중...")
        try:
            create_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#addGroupForm > div > input[type=image]")))
            time.sleep(0.5)
            create_button.click()
            print("만들기 버튼 클릭 완료")
            time.sleep(2)  # 그룹 생성 대기
        except Exception as e:
            print(f"만들기 버튼 클릭 실패: {str(e)}")
            # 대체 선택자 시도
            try:
                create_button = driver.find_element(By.CSS_SELECTOR, "#addGroupForm input[type='image']")
                create_button.click()
                print("만들기 버튼 클릭 완료 (대체 방식)")
                time.sleep(2)
            except Exception as e2:
                print(f"만들기 버튼 클릭 실패 (대체 방식): {str(e2)}")
                return False
        
        # 서로이웃 신청 버튼 찾기 및 클릭
        print("서로이웃 신청 버튼 찾는 중...")
        try:
            # 서로이웃 신청 버튼 찾기 (여러 선택자 시도)
            submit_selectors = [
                "#addGroupForm button[type='submit']",
                "#addGroupForm input[type='submit']",
                "#addGroupForm button",
                "button:contains('서로이웃 신청')",
                "button:contains('확인')"
            ]
            
            submit_button = None
            for selector in submit_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        submit_button = elements[0]
                        break
                except:
                    continue
            
            # XPath로 찾기
            if not submit_button:
                try:
                    submit_button = driver.find_element(By.XPATH, "//button[contains(text(), '서로이웃 신청')]")
                except:
                    try:
                        submit_button = driver.find_element(By.XPATH, "//button[contains(text(), '확인')]")
                    except:
                        pass
            
            if submit_button:
                time.sleep(0.5)
                submit_button.click()
                print("서로이웃 신청 버튼 클릭 완료")
                time.sleep(2)
                return True
            else:
                print("서로이웃 신청 버튼을 찾을 수 없습니다.")
                return False
        except Exception as e:
            print(f"서로이웃 신청 버튼 클릭 실패: {str(e)}")
            return False
            
    except Exception as e:
        print(f"그룹 추가 중 오류 발생: {str(e)}")
        return False

def 서로이웃_send_buddy_request(driver, blog_id, message, login_user_id):
    """서로이웃 신청 함수"""
    try:
        # 서로이웃 신청 페이지 URL 생성
        url = f"https://m.blog.naver.com/BuddyAddForm.naver?blogId={blog_id}"
        print(f"\n[{blog_id}] 서로이웃 신청 페이지 접속 중...")
        driver.get(url)
        time.sleep(2)
        
        wait = WebDriverWait(driver, 10)
        
        # 페이지 접속 직후 알림 창 확인 (이웃 수 초과 체크)
        try:
            short_wait = WebDriverWait(driver, 3)
            alert_element = short_wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#lyr6 > div > div.txt_area > p")))
            if alert_element:
                alert_text = alert_element.text
                print(f"[{blog_id}] 알림 창 감지됨: {alert_text}")
                
                # 이웃 수 초과 메시지 확인 (상대방 또는 본인)
                if "상대방의 이웃수가 5,000명이 초과" in alert_text:
                    # 상대방의 이웃수 초과: 다음 블로그로 넘어가기
                    print(f"[{blog_id}] 상대방의 이웃수가 5,000명이 초과되어 서로이웃 신청을 건너뜁니다.")
                    print(f"[{blog_id}] 다음 블로그 ID로 넘어갑니다.")
                    return False
                elif "이미 추가한 이웃" in alert_text:
                    # 이미 이웃으로 추가된 경우: 다음 블로그로 넘어가기
                    print(f"[{blog_id}] 이미 추가한 이웃입니다.")
                    print(f"[{blog_id}] 다음 블로그 ID로 넘어갑니다.")
                    return False
                elif ("이웃수가 5,000명이 초과" in alert_text and "상대방" not in alert_text) or \
                     ("나의 이웃수가" in alert_text and "5,000명이 초과" in alert_text) or \
                     ("나의 이웃수가 5,000명이 초과" in alert_text):
                    # 본인의 이웃수 초과: 작업 마무리 필요
                    print(f"[{blog_id}] 본인의 이웃수가 5,000명이 초과되었습니다.")
                    print("서로이웃 작업을 마무리하고 스프레드시트에 기록한 후 브라우징으로 넘어갑니다.")
                    # 알림창 확인 버튼 클릭
                    try:
                        alert_close_button = driver.find_element(By.CSS_SELECTOR, "#_alertLayerClose")
                        alert_close_button.click()
                        time.sleep(1)
                        print(f"[{blog_id}] 알림창 확인 버튼 클릭 완료")
                    except Exception as e:
                        print(f"[{blog_id}] 알림창 확인 버튼 클릭 실패: {e}")
                    raise 본인_이웃수_초과_예외("본인의 이웃수가 5,000명을 초과했습니다.")
                elif ("더 이상 이웃을 추가할 수 없습니다" in alert_text or \
                      "하루에 신청 가능한 이웃수가 초과" in alert_text) and "상대방" not in alert_text:
                    # 본인의 이웃수 초과 또는 하루 신청 제한
                    if "하루에 신청 가능한 이웃수가 초과" in alert_text:
                        print(f"[{blog_id}] 하루 신청 가능한 이웃수가 초과되었습니다.")
                    else:
                        print(f"[{blog_id}] 이웃 추가가 불가능합니다. 본인의 이웃수 초과 가능성이 있습니다.")
                    print("서로이웃 작업을 마무리하고 스프레드시트에 기록한 후 브라우징으로 넘어갑니다.")
                    # 알림창 확인 버튼 클릭
                    try:
                        alert_close_button = driver.find_element(By.CSS_SELECTOR, "#_alertLayerClose")
                        alert_close_button.click()
                        time.sleep(1)
                        print(f"[{blog_id}] 알림창 확인 버튼 클릭 완료")
                    except Exception as e:
                        print(f"[{blog_id}] 알림창 확인 버튼 클릭 실패: {e}")
                    raise 본인_이웃수_초과_예외("본인의 이웃 신청이 제한되었습니다.")
        except 본인_이웃수_초과_예외:
            # 본인 이웃수 초과 예외는 다시 발생시켜야 함
            raise
        except:
            # 알림 창이 없으면 정상 진행
            pass
        
        # 라디오 버튼 찾기 및 체크 (서로이웃 신청) - 재시도 로직 포함
        print(f"[{blog_id}] 라디오 버튼 찾는 중...")
        
        # 최대 2번 시도 (처음 1회 + 재시도 1회)
        for 시도_횟수 in range(2):
            try:
                # 라디오 버튼 찾기 (정확한 ID 사용)
                radio_button = None
                radio_selectors = [
                    "#bothBuddyRadio",
                    "input#bothBuddyRadio",
                    "input[name='relation'][value='1']",
                    "input[type='radio'][name='relation'][value='1']"
                ]
                
                for selector in radio_selectors:
                    try:
                        radio_button = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                        if radio_button:
                            break
                    except:
                        continue
                
                # ID로 찾지 못한 경우 일반 라디오 버튼 찾기
                if not radio_button:
                    radio_buttons = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                    if radio_buttons:
                        # value="1"인 라디오 버튼 찾기
                        for btn in radio_buttons:
                            if btn.get_attribute("value") == "1" and btn.get_attribute("name") == "relation":
                                radio_button = btn
                                break
                        # 찾지 못하면 첫 번째 라디오 버튼 사용
                        if not radio_button:
                            radio_button = radio_buttons[0]
                
                if radio_button:
                    time.sleep(0.3)
                    try:
                        radio_button.click()
                        print(f"[{blog_id}] 라디오 버튼 체크 완료")
                        time.sleep(0.5)
                        break  # 성공 시 루프 탈출
                    except Exception as click_error:
                        error_msg = str(click_error)
                        print(f"[{blog_id}] 라디오 버튼 클릭 실패: {error_msg}")
                        
                        # element not interactable 에러는 재시도 없이 바로 다음 아이디로
                        if "element not interactable" in error_msg.lower():
                            print(f"[{blog_id}] 요소와 상호작용 불가 - 다음 블로그 ID로 넘어갑니다.")
                            time.sleep(0.5)  # 브라우저 상태 정리를 위한 짧은 대기
                            return False
                        
                        # 다른 에러는 기존처럼 재시도
                        if 시도_횟수 == 0:
                            # 첫 번째 시도 실패 시 페이지 재로드
                            print(f"[{blog_id}] 서로이웃 신청 페이지를 다시 로드합니다...")
                            driver.get(url)
                            time.sleep(2)
                            wait = WebDriverWait(driver, 10)
                            continue
                        else:
                            print(f"[{blog_id}] 다음 블로그 ID로 넘어갑니다.")
                            return False
                else:
                    print(f"[{blog_id}] 라디오 버튼을 찾을 수 없습니다.")
                    if 시도_횟수 == 0:
                        # 첫 번째 시도 실패 시 페이지 재로드
                        print(f"[{blog_id}] 서로이웃 신청 페이지를 다시 로드합니다...")
                        driver.get(url)
                        time.sleep(2)
                        wait = WebDriverWait(driver, 10)
                        continue
                    else:
                        print(f"[{blog_id}] 다음 블로그 ID로 넘어갑니다.")
                        return False
                        
            except Exception as e:
                print(f"[{blog_id}] 라디오 버튼 찾기 실패: {str(e)}")
                if 시도_횟수 == 0:
                    # 첫 번째 시도 실패 시 페이지 재로드
                    print(f"[{blog_id}] 서로이웃 신청 페이지를 다시 로드합니다...")
                    driver.get(url)
                    time.sleep(2)
                    wait = WebDriverWait(driver, 10)
                    continue
                else:
                    print(f"[{blog_id}] 다음 블로그 ID로 넘어갑니다.")
                    return False
        
        # 블로그 그룹 선택 (#buddyGroupSelect)
        print(f"[{blog_id}] 블로그 그룹 선택 중...")
        try:
            group_select = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#buddyGroupSelect")))
            select = Select(group_select)
            options = select.options
            if len(options) > 0:
                # 마지막 옵션 선택
                select.select_by_index(len(options) - 1)
                print(f"[{blog_id}] 블로그 그룹 선택 완료 (마지막 옵션)")
                time.sleep(0.5)
        except Exception as e:
            print(f"[{blog_id}] 블로그 그룹 선택 실패: {str(e)}")
        
        # 서로이웃 신청 메시지 입력
        print(f"[{blog_id}] 메시지 입력 중...")
        try:
            # 메시지 입력 필드 찾기 (여러 선택자 시도)
            message_field = None
            message_selectors = [
                "textarea",
                "textarea[name='message']",
                "textarea[id*='message']",
                "textarea[class*='message']",
                "input[type='text']",
                "input[name='message']",
                ".message",
                "#message"
            ]
            
            for selector in message_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        message_field = elements[0]
                        time.sleep(0.5)
                        break
                except:
                    continue
            
            if message_field:
                try:
                    message_field.click()
                    time.sleep(0.3)
                    message_field.clear()
                    time.sleep(0.3)
                    pyperclip.copy(message)
                    message_field.send_keys(Keys.CONTROL, 'a')
                    time.sleep(0.2)
                    message_field.send_keys(Keys.CONTROL, 'v')
                    print(f"[{blog_id}] 메시지 입력 완료")
                    time.sleep(0.5)
                except Exception as e2:
                    print(f"[{blog_id}] 메시지 입력 실패: {str(e2)}")
            else:
                print(f"[{blog_id}] 메시지 입력 필드를 찾을 수 없습니다.")
        except Exception as e:
            print(f"[{blog_id}] 메시지 입력 실패: {str(e)}")
        
        # 확인 버튼 클릭
        print(f"[{blog_id}] 확인 버튼 클릭 중...")
        try:
            # 확인 버튼 찾기 (여러 형태 시도)
            confirm_button = None
            button_selectors = [
                "body > ui-view > div.head.type1 > a.btn_ok",
                "a.btn_ok",
                ".btn_ok",
                "div.head.type1 > a.btn_ok",
                "button.btn_confirm",
                "input[type='submit']",
                "button[type='submit']",
                ".btn_confirm",
                "a.btn_confirm",
                "input[value='확인']",
                "button[value='확인']",
                ".btn_submit",
                "button.btn_submit",
                "#submitBtn",
                ".submit_btn",
                "button[class*='confirm']",
                "button[class*='submit']"
            ]
            
            # CSS 선택자로 찾기
            for selector in button_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        confirm_button = elements[0]
                        break
                except:
                    continue
            
            # 텍스트로 찾기 (XPath 사용)
            if not confirm_button:
                try:
                    confirm_button = driver.find_element(By.XPATH, "//button[contains(text(), '확인')]")
                except:
                    try:
                        confirm_button = driver.find_element(By.XPATH, "//input[@value='확인']")
                    except:
                        try:
                            confirm_button = driver.find_element(By.XPATH, "//a[contains(text(), '확인')]")
                        except:
                            pass
            
            if confirm_button:
                time.sleep(0.5)
                confirm_button.click()
                print(f"[{blog_id}] 확인 버튼 클릭 완료")
                time.sleep(2)
                
                # 알림 창 감지 확인 (#lyr6 > div > div.txt_area > p)
                try:
                    short_wait = WebDriverWait(driver, 3)
                    alert_element = short_wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#lyr6 > div > div.txt_area > p")))
                    if alert_element:
                        alert_text = alert_element.text
                        print(f"[{blog_id}] 알림 창 감지됨: {alert_text}")
                        
                        # 이웃 수 초과 메시지 확인 (상대방 또는 본인)
                        if "상대방의 이웃수가 5,000명이 초과" in alert_text:
                            # 상대방의 이웃수 초과: 다음 블로그로 넘어가기
                            print(f"[{blog_id}] 상대방의 이웃수가 5,000명이 초과되어 서로이웃 신청을 건너뜁니다.")
                            print(f"[{blog_id}] 다음 블로그 ID로 넘어갑니다.")
                            return False
                        elif ("이웃수가 5,000명이 초과" in alert_text and "상대방" not in alert_text) or \
                             ("나의 이웃수가" in alert_text and "5,000명이 초과" in alert_text) or \
                             ("나의 이웃수가 5,000명이 초과" in alert_text):
                            # 본인의 이웃수 초과: 작업 마무리 필요
                            print(f"[{blog_id}] 본인의 이웃수가 5,000명이 초과되었습니다.")
                            print("서로이웃 작업을 마무리하고 스프레드시트에 기록한 후 브라우징으로 넘어갑니다.")
                            # 알림창 확인 버튼 클릭
                            try:
                                alert_close_button = driver.find_element(By.CSS_SELECTOR, "#_alertLayerClose")
                                alert_close_button.click()
                                time.sleep(1)
                                print(f"[{blog_id}] 알림창 확인 버튼 클릭 완료")
                            except Exception as e:
                                print(f"[{blog_id}] 알림창 확인 버튼 클릭 실패: {e}")
                            raise 본인_이웃수_초과_예외("본인의 이웃수가 5,000명을 초과했습니다.")
                        elif ("더 이상 이웃을 추가할 수 없습니다" in alert_text or \
                              "하루에 신청 가능한 이웃수가 초과" in alert_text) and "상대방" not in alert_text:
                            # 본인의 이웃수 초과 또는 하루 신청 제한
                            if "하루에 신청 가능한 이웃수가 초과" in alert_text:
                                print(f"[{blog_id}] 하루 신청 가능한 이웃수가 초과되었습니다.")
                            else:
                                print(f"[{blog_id}] 이웃 추가가 불가능합니다. 본인의 이웃수 초과 가능성이 있습니다.")
                            print("서로이웃 작업을 마무리하고 스프레드시트에 기록한 후 브라우징으로 넘어갑니다.")
                            # 알림창 확인 버튼 클릭
                            try:
                                alert_close_button = driver.find_element(By.CSS_SELECTOR, "#_alertLayerClose")
                                alert_close_button.click()
                                time.sleep(1)
                                print(f"[{blog_id}] 알림창 확인 버튼 클릭 완료")
                            except Exception as e:
                                print(f"[{blog_id}] 알림창 확인 버튼 클릭 실패: {e}")
                            raise 본인_이웃수_초과_예외("본인의 이웃 신청이 제한되었습니다.")
                        
                        print(f"[{blog_id}] 블로그 그룹 관리 페이지로 이동하여 그룹 추가 중...")
                        
                        # 그룹 추가 함수 호출
                        group_result = 서로이웃_add_buddy_group(driver, login_user_id)
                        if group_result:
                            print(f"[{blog_id}] 그룹 추가 및 서로이웃 신청 완료")
                            return True
                        else:
                            print(f"[{blog_id}] 그룹 추가 실패")
                            return False
                except 본인_이웃수_초과_예외:
                    # 본인 이웃수 초과 예외는 다시 발생시켜야 함
                    raise
                except:
                    # 알림 창이 없으면 정상 처리
                    print(f"[{blog_id}] 알림 창 없음. 정상 처리 완료")
                    return True
            else:
                print(f"[{blog_id}] 확인 버튼을 찾을 수 없습니다.")
                return False
        except Exception as e:
            print(f"[{blog_id}] 확인 버튼 클릭 실패: {str(e)}")
            return False
        
    except 본인_이웃수_초과_예외:
        # 본인 이웃수 초과 예외는 다시 발생시켜야 함
        raise
    except Exception as e:
        print(f"[{blog_id}] 서로이웃 신청 중 오류 발생: {str(e)}")
        return False

def 서로이웃_작업_수행(driver, 로그인_아이디):
    """서로이웃 작업을 수행하는 함수 (기존 driver 사용)
    
    Args:
        driver: WebDriver 인스턴스
        로그인_아이디: 로그인한 네이버 아이디
    
    Returns:
        bool 또는 str: 작업 성공 여부 또는 특별한 반환값
    """
    try:
        print("\n" + "="*50)
        print("서로이웃 작업 시작")
        print("="*50)
        중요_작업_로그_저장(f"서로이웃 작업 시작: 아이디={로그인_아이디}")
        
        # 서로이웃 신청 메시지 목록
        buddy_messages = [
            """안녕하세요. 이제 막 블로그를 시작한 블린이입니다.
아직 이웃도 거의 없고 많이 서툴지만
하나씩 배우면서 정성껏 운영해보려고 합니다.
서로이웃 받아주시면 공감과 댓글로 자주 소통할게요.
부담 없이 받아주시면 정말 감사하겠습니다.""",
            
            """안녕하세요! 블로그 시작한 지 얼마 안 된 초보 블로거예요.
아직 많이 부족하지만 꾸준히 글 올리면서
좋은 이웃분들과 소통하고 싶어서 신청드립니다.
서로이웃이 된다면 자주 방문하고 공감 남길게요.
잘 부탁드립니다.""",
            
            """안녕하세요. 블로그를 이제 막 시작해서
이웃도 거의 없는 상태라 용기 내서 신청드려요
글 하나하나 정성껏 쓰면서 성장해보려고 합니다.
서로이웃 맺어주시면 진심으로 소통하겠습니다.
감사합니다!""",
            
            """안녕하세요
블로그 시작한 지 얼마 안 된 블린이인데
혼자 하다 보니 조금 외롭더라고요.
서로이웃으로 함께 소통하면서
블로그 이야기 나누면 좋겠습니다.
받아주시면 정말 감사할게요!""",
            
            """안녕하세요. 아직 많이 부족한 초보 블로거입니다.
그래도 꾸준히 운영하면서 오래 가는 블로그를
만들어보고 싶어서 이렇게 신청드려요.
서로이웃이 된다면 공감댓글 성실히 남기겠습니다.
잘 부탁드립니다!""",
            
            """안녕하세요! 블로그 막 시작해서
아직 이웃도 없고 배울 것도 많지만
정성껏 운영하려고 노력 중입니다.
서로이웃 받아주시면 자주 찾아뵙고
소통 열심히 하겠습니다.""",
            
            """안녕하세요. 블로그 초보라 부족한 점이 많지만
다른 분들 글 보면서 하나씩 배우고 있어요.
서로이웃으로 인연 맺고
편하게 소통하며 지내고 싶습니다.
부담 없이 받아주세요!""",
            
            """안녕하세요
이제 막 블로그 시작한 블린이입니다.
아직 글도 많지 않지만
앞으로 꾸준히 채워가려고 합니다.
서로이웃이 된다면 공감댓글로
자주 인사드릴게요. 감사합니다!""",
            
            """안녕하세요. 용기 내서 이웃 신청드려요.
블로그 시작한 지 얼마 안 돼서
아직 많이 서툴고 이웃도 거의 없어요
서로이웃 받아주시면
정성껏 소통하겠습니다. 잘 부탁드립니다!""",
            
            """안녕하세요! 초보 블로거라 많이 부족하지만
글 하나하나 진심 담아서 써보려고 합니다.
서로이웃으로 함께 소통하면
더 힘이 날 것 같아요
받아주시면 정말 감사하겠습니다.""",
            
            """안녕하세요. 이제 막 블로그를 시작한 초보 블로거입니다.
아직 많이 부족하지만 하나씩 배워가며 성실하게 운영하려고 합니다.
서로이웃으로 인연 맺어주시면 공감과 댓글로 꾸준히 소통하겠습니다.
부담 없이 받아주시면 정말 감사하겠습니다.""",
            
            """안녕하세요. 블로그를 시작한 지 얼마 안 된 블린이입니다.
이웃도 거의 없고 서툴지만 정성껏 글을 써보려고 노력 중입니다.
서로이웃 맺어주시면 자주 찾아뵙고 공감과 댓글로 소통하겠습니다.
편하게 받아주세요!""",
            
            """안녕하세요. 이제 막 블로그를 시작해서 많이 부족한 상태입니다.
천천히 배우면서 오래 운영해보고 싶어 이렇게 인사드립니다.
서로이웃이 되어주시면 꾸준히 방문하며 소통하겠습니다.
부담 없이 받아주시면 감사하겠습니다.""",
            
            """안녕하세요! 블로그를 처음 시작한 초보입니다.
아직 글도 이웃도 많지 않지만 성실함만큼은 자신 있습니다.
서로이웃으로 함께 소통할 수 있으면 좋겠습니다.
편하게 수락해주시면 감사하겠습니다.""",
            
            """안녕하세요. 블린이로 이제 막 첫걸음을 떼고 있습니다.
아직 많이 서툴지만 하나하나 배우며 정성껏 운영하려고 합니다.
서로이웃으로 인연 맺어주시면 자주 소통하겠습니다.
잘 부탁드립니다!""",
            
            """안녕하세요. 블로그 시작한 지 얼마 안 된 초보입니다.
이웃도 거의 없고 부족하지만 꾸준히 글 쓰며 성장해보려 합니다.
서로이웃이 되어주시면 공감과 댓글로 자주 찾아뵐게요.
부담 없이 받아주세요!""",
            
            """안녕하세요. 새로 블로그를 시작하게 되어 인사드립니다.
아직 많이 부족하지만 성실하게 운영해보려 합니다.
서로이웃으로 함께 소통할 수 있다면 정말 좋겠습니다.
감사합니다!""",
            
            """안녕하세요! 이제 막 블로그를 시작한 블린이입니다.
서툴지만 천천히 배우며 오래 운영해보고 싶습니다.
서로이웃으로 맺어주시면 공감과 댓글로 자주 소통하겠습니다.
편하게 받아주시면 감사하겠습니다.""",
            
            """안녕하세요. 블로그를 시작한 지 얼마 안 된 초보입니다.
아직 부족한 점이 많지만 정성껏 글을 써보려고 합니다.
서로이웃으로 인연 맺어주시면 자주 방문하며 소통할게요.
잘 부탁드립니다!""",
            
            """안녕하세요. 블로그를 처음 시작한 블린이입니다.
이웃도 거의 없고 서툴지만 하나씩 배워가며 운영 중입니다.
서로이웃이 되어주시면 공감과 댓글로 소통하겠습니다.
부담 없이 받아주시면 정말 감사하겠습니다."""
        ]
        
        # 키워드 목록 정의 및 랜덤 선택
        all_keywords = [
            "일상", "데일리", "라이프", "기록", "소확행", "하루", "일기", "루틴", "브이로그", "라이프로그",
            "정보", "꿀팁", "노하우", "정리", "공유", "리뷰", "후기", "가이드", "비교", "추천",
            "여행", "맛집", "카페", "사진", "캠핑", "드라이브", "영화", "음악", "독서", "운동",
            "자영업", "사업", "창업", "운영", "브랜딩", "업무", "실무", "자동화"
        ]
        
        # 랜덤으로 10개 키워드 선택
        keywords = random.sample(all_keywords, min(10, len(all_keywords)))
        print(f"\n선택된 랜덤 키워드 (10개): {', '.join(keywords)}")
        
        # 각 키워드마다 블로그 ID 추출
        all_blog_ids = []
        for keyword in keywords:
            print(f"\n키워드: {keyword} - 블로그 ID 추출 중...")
            try:
                blog_ids = 서로이웃_extract_blog_ids(keyword, driver)
                if blog_ids:
                    # 15개만 선택
                    selected_ids = blog_ids[:15]
                    all_blog_ids.extend(selected_ids)
                    print(f"[{keyword}] 추출된 블로그 ID: {len(selected_ids)}개")
            except Exception as e:
                print(f"[{keyword}] 블로그 ID 추출 중 오류: {str(e)}")
                continue
        
        if not all_blog_ids:
            print("추출된 블로그 ID가 없습니다.")
            return False
        
        print(f"\n전체 추출된 블로그 ID 개수: {len(all_blog_ids)}")
        
        # 서로이웃 신청 시작 (90~99명 사이 랜덤으로 신청 개수 결정)
        target_count = random.randint(90, 99)
        print(f"\n서로이웃 신청 시작 (목표: {target_count}명)")
        
        success_count = 0
        fail_count = 0
        연속_실패_횟수 = 0  # 연속 실패 횟수 추적
        최대_연속_실패 = 5  # 5번 연속 실패 시 브라우저 재시작
        
        for idx, blog_id in enumerate(all_blog_ids, 1):
            # 목표 개수에 도달했는지 먼저 확인
            if success_count >= target_count:
                print(f"\n하루 서로이웃 신청 목표({target_count}명)에 도달했습니다.")
                print("서로이웃 추가 작업을 중단합니다.")
                break
            
            # 연속 실패 횟수가 최대치에 도달하면 브라우저 재시작
            if 연속_실패_횟수 >= 최대_연속_실패:
                print(f"\n⚠️ {최대_연속_실패}번 연속으로 서로이웃 신청에 실패했습니다.")
                print("브라우저를 재시작하여 로그인부터 다시 시도합니다...\n")
                중요_작업_로그_저장(f"서로이웃 {최대_연속_실패}번 연속 실패로 브라우저 재시작")
                
                # 현재까지의 성공 횟수를 반환값에 포함하여 재시작 신호 전달
                return f"브라우저_재시작_필요:{success_count}"
            
            # 진행 상황 표시: 성공 개수/목표 개수
            print(f"\n진행 상황: {success_count}/{target_count} (전체 시도: {idx}/{len(all_blog_ids)})")
            # 랜덤으로 메시지 선택
            message = random.choice(buddy_messages)
            
            try:
                result = 서로이웃_send_buddy_request(driver, blog_id, message, 로그인_아이디)
                if result:
                    success_count += 1
                    연속_실패_횟수 = 0  # 성공 시 연속 실패 카운터 리셋
                    # 하루 신청 제한 확인 (90~99명 랜덤)
                    if success_count >= target_count:
                        print(f"\n하루 서로이웃 신청 목표({target_count}명)에 도달했습니다.")
                        print("서로이웃 추가 작업을 중단합니다.")
                        break
                else:
                    fail_count += 1
                    연속_실패_횟수 += 1  # 실패 시 연속 실패 카운터 증가
                    print(f"[{blog_id}] 서로이웃 신청 실패 - 다음 블로그로 계속 진행... (연속 실패: {연속_실패_횟수}/{최대_연속_실패})")
                    time.sleep(1)  # 다음 시도 전 짧은 대기
            except 본인_이웃수_초과_예외 as e:
                # 본인의 이웃수 초과: 작업 마무리하고 스프레드시트 기록 후 브라우징으로
                print(f"\n본인의 이웃수가 5,000명을 초과했습니다.")
                print("서로이웃 작업을 마무리하고 스프레드시트에 기록한 후 브라우징으로 넘어갑니다.")
                # 결과 요약
                print("\n" + "="*50)
                print("서로이웃 신청 완료 (본인 이웃수 초과로 중단)")
                print("="*50)
                print(f"성공: {success_count}개")
                print(f"실패: {fail_count}개")
                print("="*50)
                중요_작업_로그_저장(f"서로이웃 작업 완료 (본인 이웃수 초과): 성공={success_count}, 실패={fail_count}")
                # 특별한 반환값으로 본인 이웃수 초과를 알림
                return "본인_이웃수_초과"
            except SystemExit:
                # 이웃 수 초과로 인한 프로그램 종료
                print("이웃 수 초과로 인해 서로이웃 작업을 중단합니다.")
                return False
            except Exception as e:
                error_str = str(e)
                # 드라이버 연결 오류 확인 (HTTPConnectionPool, NewConnectionError, Failed to establish 등)
                if ("HTTPConnectionPool" in error_str or 
                    "NewConnectionError" in error_str or 
                    "Failed to establish" in error_str or
                    "대상 컴퓨터에서 연결을 거부" in error_str or
                    "connection refused" in error_str.lower() or
                    "Max retries exceeded" in error_str):
                    # 드라이버 연결 오류: 작업 마무리하고 스프레드시트 기록 후 브라우징으로
                    print(f"\n드라이버 연결 오류가 발생했습니다: {error_str}")
                    print("서로이웃 작업을 마무리하고 스프레드시트에 기록한 후 브라우징으로 넘어갑니다.")
                    # 결과 요약
                    print("\n" + "="*50)
                    print("서로이웃 신청 완료 (드라이버 연결 오류로 중단)")
                    print("="*50)
                    print(f"성공: {success_count}개")
                    print(f"실패: {fail_count}개")
                    print("="*50)
                    중요_작업_로그_저장(f"서로이웃 작업 완료 (드라이버 연결 오류): 성공={success_count}, 실패={fail_count}")
                    # 특별한 반환값으로 드라이버 연결 오류를 알림
                    return "드라이버_연결_오류"
                else:
                    # 일반 오류: 다음 블로그로 넘어가기
                    print(f"서로이웃 신청 중 오류: {error_str}")
                    fail_count += 1
                    continue
            
            # 다음 요청 전 대기 (너무 빠른 요청 방지)
            if idx < len(all_blog_ids):
                time.sleep(1)
        
        # 결과 요약
        print("\n" + "="*50)
        print("서로이웃 신청 완료")
        print("="*50)
        print(f"성공: {success_count}개")
        print(f"실패: {fail_count}개")
        print("="*50)
        
        중요_작업_로그_저장(f"서로이웃 작업 완료: 성공={success_count}, 실패={fail_count}")
        
        return True
        
    except Exception as e:
        print(f"서로이웃 작업 중 오류 발생: {str(e)}")
        오류_로그_저장(f"서로이웃 작업 오류: {str(e)}")
        return False
# ================== 서로이웃 작업 시스템 끝 ==================

def 크롬_드라이버_설정():
    """크롬 드라이버를 설정하는 함수 (undetected-chromedriver)"""
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--window-size=1200,800")
    driver = uc_크롬_드라이버_생성(chrome_options)
    try:
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    except Exception:
        pass
    return driver

def 네이버_사이트_실행(driver):
    """네이버 사이트를 실행하는 함수"""
    try:
        # === 네이버 사이트 실행 ===
        print("\n🌐 네이버 사이트를 실행합니다...")
        driver.get("https://www.naver.com")
        time.sleep(3)
        
        print("✅ 네이버 사이트 로딩 완료")
        print(f"현재 URL: {driver.current_url}")
        
        return True
        
    except Exception as e:
        print(f"❌ 네이버 사이트 실행 중 오류: {e}")
        return False

def 키워드_입력받기():
    """지명키워드.xlsx 파일에서 지명키워드를 읽어오는 함수"""
    try:
        print("\n=== 네이버 카페/블로그 필터링 프로그램 ===")
        print("돌쇠가 만든 셀레니움 네이버 검색 프로그램입니다!")
        print()
        
        # 지명키워드.xlsx 파일 읽기
        print("지명키워드.xlsx 파일을 읽는 중...")
        df = 지명키워드_df_가져오기()
        
        # 지명키워드 컬럼 확인
        if "지명키워드" not in df.columns:
            print("오류: 지명키워드.xlsx 파일에 '지명키워드' 컬럼이 없습니다.")
            print(f"사용 가능한 컬럼: {list(df.columns)}")
            return None
        
        # 지명키워드 목록 가져오기
        지명키워드_목록 = df["지명키워드"].dropna().tolist()
        
        if not 지명키워드_목록:
            print("오류: 지명키워드.xlsx 파일에 데이터가 없습니다.")
            return None
        
        print(f"지명키워드.xlsx 파일에서 {len(지명키워드_목록)}개의 키워드를 읽었습니다.")
        print(f"키워드 목록: {지명키워드_목록}")
        
        # 첫 번째 키워드 반환 (필요시 여러 키워드 처리 가능)
        첫번째_키워드 = 지명키워드_목록[0]
        print(f"처리할 키워드: {첫번째_키워드}")
        
        return 첫번째_키워드
        
    except FileNotFoundError:
        print("오류: 지명키워드.xlsx 파일을 찾을 수 없습니다.")
        print("지명키워드.xlsx 파일이 현재 폴더에 있는지 확인해주세요.")
        return None
    except Exception as e:
        print(f"지명키워드.xlsx 파일 읽기 중 오류: {e}")
        return None

def 네이버_검색_실행(driver, 검색어):
    """네이버에서 검색을 실행하는 함수"""
    try:
        print(f"'{검색어}' 검색을 실행합니다...")
        
        # 검색 시작 로그 저장
        작업_로그_저장(f"네이버 검색 시작: {검색어}")
        
        # 검색창 찾기
        검색창 = driver.find_element(By.CSS_SELECTOR, "#query")
        검색창.clear()
        검색창.send_keys(검색어)
        검색창.send_keys(Keys.RETURN)
        
        time.sleep(3)
        
        print("검색 완료")
        print(f"현재 URL: {driver.current_url}")
        
        # 검색 완료 로그 저장
        작업_로그_저장(f"네이버 검색 완료: {검색어}")
        
        return True
        
    except Exception as e:
        print(f"검색 실행 중 오류: {e}")
        return False

def 카페블로그_상호_크롤링(driver):
    """검색 결과에서 카페/블로그 상호만 크롤링하는 함수"""
    try:
        상호_목록 = []
        
        print("카페/블로그 상호 크롤링을 시작합니다...")
        
        # 상호 선택자들 (우선순위 순)
        상호_선택자들 = [
            # 1순위: 사용자가 확인한 새로운 네이버 검색 결과 선택자
            ".sds-comps-profile-info-title > span > a > span",
            ".sds-comps-profile-info-title span > a > span",
            "div.sds-comps-profile-info-title > span > a > span",
            # 2순위: 기존 선택자
            "a.name",
            "a[class*='name']",
            "a[class*='title']",
            "a[class*='link']",
            # 3순위: URL 기반 선택자
            "a[href*='blog.naver.com']",
            "a[href*='cafe.naver.com']",
            "a[href*='tistory.com']"
        ]
        
        상호_링크들 = []
        사용된_선택자 = None
        
        # 각 선택자를 순서대로 시도
        for 선택자 in 상호_선택자들:
            try:
                찾은_링크들 = driver.find_elements(By.CSS_SELECTOR, 선택자)
                print(f"{선택자} 선택자로 {len(찾은_링크들)}개 찾음")
                
                if len(찾은_링크들) > 0:
                    상호_링크들 = 찾은_링크들
                    사용된_선택자 = 선택자
                    print(f"✅ '{선택자}' 선택자로 {len(상호_링크들)}개의 링크를 찾았습니다.")
                    break
            except Exception as e:
                print(f"⚠️ '{선택자}' 선택자 시도 중 오류: {e}")
                continue
        
        # 카페/블로그 링크만 필터링
        카페블로그_개수 = 0
        for 링크 in 상호_링크들:
            try:
                # span 요소인 경우 부모 a 태그 찾기
                if 링크.tag_name == 'span':
                    a_태그 = 링크.find_element(By.XPATH, "./ancestor::a[1]")
                    URL = a_태그.get_attribute("href")
                    상호 = 링크.text.strip()
                else:
                    URL = 링크.get_attribute("href")
                    상호 = 링크.text.strip()
                
                # URL이 있고 상호가 있는 경우만
                if URL and 상호:
                    # 카페/블로그 URL 필터링
                    if ("cafe.naver.com" in URL or "cafe.daum.net" in URL or 
                        "blog.naver.com" in URL or "blog.daum.net" in URL or "tistory.com" in URL):
                        
                        # 중복 제거
                        if 상호 not in 상호_목록:
                            상호_목록.append(상호)
                            카페블로그_개수 += 1
                            print(f"카페/블로그 발견: {상호}")
                            print(f"URL: {URL}")
                            
                            # 상위 10개만 수집
                            if 카페블로그_개수 >= 10:
                                break
                                
            except Exception as e:
                continue
        
        # 여전히 찾지 못한 경우 추가 선택자 시도
        if not 상호_목록:
            print("기본 선택자로 찾지 못했습니다. 추가 선택자를 시도합니다...")
            
            # 추가 선택자들 시도
            추가_선택자들 = [
                "div.sds-comps-profile.type-basic.size-lg .sds-comps-profile-info-title span a span",
                ".sds-comps-horizontal-layout.sds-comps-profile-info-title span a span"
            ]
            
            for 선택자 in 추가_선택자들:
                try:
                    링크들 = driver.find_elements(By.CSS_SELECTOR, 선택자)
                    print(f"{선택자} 선택자로 {len(링크들)}개 찾음")
                    
                    for 링크 in 링크들:
                        try:
                            URL = 링크.get_attribute("href")
                            상호 = 링크.text.strip()
                            
                            if URL and 상호:
                                if ("cafe.naver.com" in URL or "cafe.daum.net" in URL or 
                                    "blog.naver.com" in URL or "blog.daum.net" in URL or "tistory.com" in URL):
                                    
                                    if 상호 not in 상호_목록:
                                        상호_목록.append(상호)
                                        카페블로그_개수 += 1
                                        print(f"카페/블로그 발견: {상호}")
                                        print(f"URL: {URL}")
                                        
                                        if 카페블로그_개수 >= 10:
                                            break
                        except:
                            continue
                            
                    if 상호_목록:
                        break
                        
                except:
                    continue
        
        print(f"총 카페/블로그 상호: {len(상호_목록)}개")
        
        # 크롤링 완료 로그 저장
        작업_로그_저장(f"카페/블로그 크롤링 완료: {len(상호_목록)}개 상호")
        
        return 상호_목록
        
    except Exception as e:
        print(f"카페/블로그 상호 크롤링 중 오류: {e}")
        return []

def 상호_출력(상호_목록):
    """크롤링된 상호를 출력하는 함수"""
    print("\n=== 카페/블로그 상호 크롤링 결과 ===")
    print(f"총 {len(상호_목록)}개의 상호를 찾았습니다.")
    print()
    
    # 상위 5개만 출력
    상위_5개 = 상호_목록[:5]
    
    print("=== 상위 5개 상호 ===")
    for i, 상호 in enumerate(상위_5개, 1):
        print(f"【{i}등】{상호}")
        print("-" * 50)
    
    print("\n=== 상위 5개 요약 ===")
    for i, 상호 in enumerate(상위_5개, 1):
        print(f"{i}등: {상호}")
    
    return 상위_5개

def 순위_엑셀_저장(검색어, 상위_5개):
    """상위 5개 상호를 뷰순위.xlsx 파일로 저장하는 함수"""
    try:
        if not 상위_5개:
            print("저장할 상호가 없습니다.")
            return
        
        print(f"순위_엑셀_저장 함수 호출됨")
        print(f"검색어: {검색어}")
        print(f"상위_5개: {상위_5개}")
        
        # 순위별로 정리된 데이터
        순위_데이터 = []
        for i, 상호 in enumerate(상위_5개, 1):
            순위_데이터.append({
                "순위": i,
                "상호": 상호,
                "지명키워드": 검색어
            })
        
        print(f"순위_데이터: {순위_데이터}")
        
        # 새로운 데이터로 덮어쓰기 (기존 데이터 삭제)
        통합_df = pd.DataFrame(순위_데이터)
        
        # 저장할 파일 경로 확인
        저장_경로 = resource_path('뷰순위.xlsx')
        print(f"저장할 파일 경로: {저장_경로}")
        
        # 현재 작업 디렉토리 확인
        현재_작업_디렉토리 = os.getcwd()
        print(f"현재 작업 디렉토리: {현재_작업_디렉토리}")
        
        # _internal 폴더 존재 여부 확인
        internal_폴더 = os.path.dirname(저장_경로)
        print(f"_internal 폴더 경로: {internal_폴더}")
        print(f"_internal 폴더 존재 여부: {os.path.exists(internal_폴더)}")
        
        # _internal 폴더가 없으면 생성
        if not os.path.exists(internal_폴더):
            os.makedirs(internal_폴더)
            print(f"_internal 폴더를 생성했습니다: {internal_폴더}")
        
        # 뷰순위.xlsx 파일로 저장 (재시도 로직 포함)
        excel_저장_성공 = False
        최대_재시도 = 3
        
        for 재시도_횟수 in range(최대_재시도):
            try:
                # 파일이 존재하고 사용 중일 수 있으므로 삭제 후 재생성
                if os.path.exists(저장_경로):
                    try:
                        # 파일이 사용 중인지 확인하고 삭제 시도
                        os.remove(저장_경로)
                        print(f"기존 파일 삭제 완료: {저장_경로}")
                        time.sleep(0.5)  # 파일 시스템 동기화 대기
                    except Exception as remove_error:
                        print(f"기존 파일 삭제 중 오류 (재시도 {재시도_횟수 + 1}/{최대_재시도}): {remove_error}")
                        if 재시도_횟수 < 최대_재시도 - 1:
                            time.sleep(1)  # 1초 대기 후 재시도
                            continue
                        else:
                            # 마지막 시도에서도 실패하면 CSV로 저장
                            print(f"파일 삭제 실패로 CSV로 저장합니다.")
                            csv_경로 = 저장_경로.replace('.xlsx', '.csv')
                            통합_df.to_csv(csv_경로, index=False, encoding='utf-8-sig')
                            print(f"CSV 파일로 저장 완료: {csv_경로}")
                            return
                
                # Excel 파일 저장
                통합_df.to_excel(저장_경로, index=False, engine='openpyxl')
                print(f"Excel 파일 저장 성공 (시도 {재시도_횟수 + 1}/{최대_재시도})")
                excel_저장_성공 = True
                break
                
            except PermissionError as perm_error:
                print(f"Excel 저장 중 권한 오류 (재시도 {재시도_횟수 + 1}/{최대_재시도}): {perm_error}")
                if 재시도_횟수 < 최대_재시도 - 1:
                    time.sleep(2)  # 2초 대기 후 재시도
                else:
                    # 마지막 시도에서도 실패하면 CSV로 저장
                    print(f"Excel 저장 실패로 CSV로 저장합니다.")
                    csv_경로 = 저장_경로.replace('.xlsx', '.csv')
                    통합_df.to_csv(csv_경로, index=False, encoding='utf-8-sig')
                    print(f"CSV 파일로 저장 완료: {csv_경로}")
                    return
            except Exception as excel_error:
                print(f"Excel 저장 중 오류 (재시도 {재시도_횟수 + 1}/{최대_재시도}): {excel_error}")
                if 재시도_횟수 < 최대_재시도 - 1:
                    time.sleep(1)  # 1초 대기 후 재시도
                else:
                    # 마지막 시도에서도 실패하면 CSV로 저장
                    print(f"Excel 저장 실패로 CSV로 저장합니다.")
                    csv_경로 = 저장_경로.replace('.xlsx', '.csv')
                    통합_df.to_csv(csv_경로, index=False, encoding='utf-8-sig')
                    print(f"CSV 파일로 저장 완료: {csv_경로}")
                    return
        
        if not excel_저장_성공:
            return
        print(f"\n상위 5개 상호가 뷰순위.xlsx 파일에 저장되었습니다.")
        print(f"총 {len(통합_df)}개의 순위 데이터가 저장되어 있습니다.")
        
        # 파일이 실제로 생성되었는지 확인
        if os.path.exists(저장_경로):
            파일_크기 = os.path.getsize(저장_경로)
            print(f"파일 생성 확인: {저장_경로} (크기: {파일_크기} bytes)")
        else:
            print(f"경고: 파일이 생성되지 않았습니다: {저장_경로}")
        
        # 뷰순위 저장 완료 로그
        작업_로그_저장(f"뷰순위.xlsx 저장 완료: {len(통합_df)}개 순위 데이터")
        
    except Exception as e:
        print(f"뷰순위.xlsx 파일 저장 중 오류: {e}")
        print(f"오류 상세 정보: {traceback.format_exc()}")
        # 오류 로그 저장
        오류_로그_저장(f"뷰순위.xlsx 저장 오류: {e}")

def 구글스프레드시트_아이디_입력(사용_아이디):
    """구글 스프레드시트의 아이디 항목에 사용할 아이디를 입력 (중복 로그인 방지용) - 기록 비활성화"""
    return True

def 구글스프레드시트_아이디_사용중_확인(확인할_아이디):
    """구글 스프레드시트에서 특정 아이디가 사용 중인지 확인"""
    import socket
    import time
    
    # 1. 파일 존재 여부 확인
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(키_파일_경로):
        print(f"오류: {키_파일_경로} 파일을 찾을 수 없습니다.")
        return False
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 2. 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 3. 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                # 5. 진행상황 출력
                if 시도_횟수 > 0:
                    print(f"구글 스프레드시트 아이디 사용중 확인 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 연결 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
                client = gspread_authorize_with_timeout(creds)
                
                # 구글 스프레드시트 열기
                spreadsheet_url = "https://docs.google.com/spreadsheets/d/1w5ubHKn418A9ypJEa9nKjdskOcZ1BImP89xO8PRISgs/edit?usp=sharing"
                spreadsheet = client.open_by_url(spreadsheet_url)
                worksheet = spreadsheet.sheet1
                
                # 현재 데이터 확인
                current_data = worksheet.get_all_values()
                
                if current_data and len(current_data) > 1:
                    # A2부터 A21까지 확인 (20개 아이디 동시 사용 가능)
                    사용중인_아이디들 = []
                    for row_idx in range(1, min(21, len(current_data))):  # A2, A3, A4, ..., A21 확인
                        if current_data[row_idx] and current_data[row_idx][0] and str(current_data[row_idx][0]).strip():
                            사용중인_아이디 = str(current_data[row_idx][0]).strip()
                            사용중인_아이디들.append(사용중인_아이디)
                            if 사용중인_아이디 == 확인할_아이디:
                                print(f"아이디 '{확인할_아이디}'가 이미 사용 중입니다.")
                                print(f"현재 사용 중인 아이디들: {사용중인_아이디들}")
                                return True
                    
                    if 시도_횟수 > 0:
                        print(f"구글 스프레드시트 아이디 사용중 확인 성공! (시도 {시도_횟수 + 1}회)")
                    
                    print(f"아이디 '{확인할_아이디}'는 사용 가능합니다.")
                    if 사용중인_아이디들:
                        print(f"현재 사용 중인 아이디들: {사용중인_아이디들}")
                    else:
                        print("현재 사용 중인 아이디 없음")
                    return False
                else:
                    print(f"아이디 '{확인할_아이디}'는 사용 가능합니다. (구글 스프레드시트가 비어있음)")
                    return False
                    
            except (socket.timeout, TimeoutError):
                # 4. socket.timeout 예외 발생 시 30초 대기 후 재시도
                print(f"연결 타임아웃 발생 (시도 {시도_횟수 + 1}/10). 30초 대기 후 재시도합니다...")
                if 시도_횟수 < 9:
                    time.sleep(30)
                    
            except Exception as e:
                print(f"구글 스프레드시트 아이디 사용중 확인 중 오류 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:
                    time.sleep(5)
        
        print("구글 스프레드시트 아이디 사용중 확인 실패: 최대 재시도 횟수(10회)에 도달했습니다.")
        return False
        
    finally:
        # 6. 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def 구글스프레드시트_아이디_삭제(사용_아이디=None):
    """구글 스프레드시트의 아이디 항목에서 특정 아이디를 삭제"""
    import socket
    import time
    from requests.exceptions import ReadTimeout, ConnectionError as RequestsConnectionError
    from urllib3.exceptions import ReadTimeoutError, ProtocolError
    
    # 1. 파일 존재 여부 확인
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(키_파일_경로):
        print(f"오류: {키_파일_경로} 파일을 찾을 수 없습니다.")
        return False
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 2. 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 재시도 유틸 (네트워크/세션 오류 방어)
        def _retry(op, desc="gs-op", retries=5, delay=3):
            last_e = None
            for r in range(retries):
                try:
                    return op()
                except (socket.timeout, ReadTimeout, RequestsConnectionError, ReadTimeoutError, ProtocolError) as e:
                    last_e = e
                    print(f"⚠️ {desc} 재시도 {r+1}/{retries}: {e}")
                    if r < retries - 1:
                        time.sleep(delay)
                        continue
                    raise
                except Exception as e:
                    last_e = e
                    # 기타 오류도 한 번 정도는 재시도
                    print(f"⚠️ {desc} 재시도 {r+1}/{retries}: {e}")
                    if r < retries - 1:
                        time.sleep(delay)
                        continue
                    raise last_e

        # 3. 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                # 5. 진행상황 출력
                if 시도_횟수 > 0:
                    print(f"구글 스프레드시트 아이디 삭제 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 연결 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
                client = gspread_authorize_with_timeout(creds)
                
                # 구글 스프레드시트 열기
                spreadsheet_url = "https://docs.google.com/spreadsheets/d/1w5ubHKn418A9ypJEa9nKjdskOcZ1BImP89xO8PRISgs/edit?usp=sharing"
                spreadsheet = _retry(lambda: client.open_by_url(spreadsheet_url), "open_by_url")
                worksheet = spreadsheet.sheet1  # 첫 번째 시트 (속성 접근은 즉시 평가됨)
                
                # 아이디 항목에서 아이디 삭제
                print("구글 스프레드시트에서 아이디를 삭제하는 중...")
                
                # 구글 스프레드시트의 현재 데이터 확인
                try:
                    current_data = _retry(lambda: worksheet.get_all_values(), "get_all_values")
                    
                    if current_data and 사용_아이디:
                        # 폴더 컬럼 인덱스 찾기
                        headers = current_data[0] if current_data else []
                        폴더_컬럼_인덱스 = None
                        for idx, header in enumerate(headers):
                            if header == '폴더':
                                폴더_컬럼_인덱스 = idx
                                break
                        
                        # 사용한 아이디를 찾아서 삭제
                        삭제_완료 = False
                        for row_idx, row in enumerate(current_data):
                            if row and row[0] == 사용_아이디:
                                # 해당 행의 아이디를 빈 값으로 설정
                                아이디_셀 = f'A{row_idx + 1}'
                                _retry(lambda: worksheet.update(values=[['']], range_name=아이디_셀), f"update {아이디_셀}")
                                
                                # 폴더 컬럼도 함께 삭제
                                if 폴더_컬럼_인덱스 is not None:
                                    폴더_셀 = f'{chr(65 + 폴더_컬럼_인덱스)}{row_idx + 1}'
                                    _retry(lambda: worksheet.update(values=[['']], range_name=폴더_셀), f"update {폴더_셀}")
                                    print(f"아이디 '{사용_아이디}'와 폴더명을 {아이디_셀}, {폴더_셀}에서 삭제했습니다.")
                                else:
                                    print(f"아이디 '{사용_아이디}'를 {아이디_셀}에서 삭제했습니다.")
                                삭제_완료 = True
                                break
                        
                        if not 삭제_완료:
                            print(f"아이디 '{사용_아이디}'를 구글 스프레드시트에서 찾을 수 없습니다.")
                            # A2부터 A6까지 확인하여 마지막 사용 중인 아이디 삭제
                            if current_data[0] and current_data[0][0] == '아이디':
                                # A2부터 A6까지 역순으로 확인하여 마지막 사용 중인 아이디 찾기
                                마지막_사용중인_행 = None
                                for row_idx in range(6, 1, -1):  # A6, A5, A4, A3, A2 순서로 확인
                                    if row_idx <= len(current_data):
                                        if current_data[row_idx-1] and current_data[row_idx-1][0] and str(current_data[row_idx-1][0]).strip():
                                            마지막_사용중인_행 = row_idx
                                            break
                                
                                if 마지막_사용중인_행:
                                    아이디_셀 = f'A{마지막_사용중인_행}'
                                    _retry(lambda: worksheet.update(values=[['']], range_name=아이디_셀), f"update {아이디_셀}")
                                    
                                    # 폴더 컬럼도 함께 삭제
                                    if 폴더_컬럼_인덱스 is not None:
                                        폴더_셀 = f'{chr(65 + 폴더_컬럼_인덱스)}{마지막_사용중인_행}'
                                        _retry(lambda: worksheet.update(values=[['']], range_name=폴더_셀), f"update {폴더_셀}")
                                        print(f"마지막 사용 중인 아이디와 폴더명을 {아이디_셀}, {폴더_셀}에서 삭제했습니다.")
                                    else:
                                        print(f"마지막 사용 중인 아이디를 {아이디_셀}에서 삭제했습니다.")
                                else:
                                    print("사용 중인 아이디가 없습니다.")
                            else:
                                _retry(lambda: worksheet.update(values=[['']], range_name='A1'), "update A1")
                    else:
                        # 사용한 아이디가 없으면 기존 방식으로 처리
                        if current_data:
                            if current_data[0] and current_data[0][0] == '아이디':
                                # 폴더 컬럼 인덱스 찾기
                                headers = current_data[0] if current_data else []
                                폴더_컬럼_인덱스 = None
                                for idx, header in enumerate(headers):
                                    if header == '폴더':
                                        폴더_컬럼_인덱스 = idx
                                        break
                                
                                _retry(lambda: worksheet.update(values=[['']], range_name='A2'), "update A2")
                                
                                # 폴더 컬럼도 함께 삭제
                                if 폴더_컬럼_인덱스 is not None:
                                    폴더_셀 = f'{chr(65 + 폴더_컬럼_인덱스)}2'
                                    _retry(lambda: worksheet.update(values=[['']], range_name=폴더_셀), f"update {폴더_셀}")
                            else:
                                _retry(lambda: worksheet.update(values=[['']], range_name='A1'), "update A1")
                        else:
                            _retry(lambda: worksheet.update(values=[['']], range_name='A1'), "update A1")
                        
                except Exception as e:
                    print(f"구글 스프레드시트 데이터 확인 중 오류: {e}")
                    # 오류 발생 시 안전하게 첫 번째 행에서 삭제
                    try:
                        _retry(lambda: worksheet.update(values=[['']], range_name='A1'), "update A1(fallback)")
                    except Exception as e2:
                        print(f"최종 업데이트 실패: {e2}")
                
                if 시도_횟수 > 0:
                    print(f"구글 스프레드시트 아이디 삭제 성공! (시도 {시도_횟수 + 1}회)")
                
                print("구글 스프레드시트에서 아이디가 성공적으로 삭제되었습니다.")
                return True
                
            except (socket.timeout, TimeoutError):
                # 4. socket.timeout 예외 발생 시 30초 대기 후 재시도
                print(f"연결 타임아웃 발생 (시도 {시도_횟수 + 1}/10). 30초 대기 후 재시도합니다...")
                if 시도_횟수 < 9:
                    time.sleep(30)
                    
            except Exception as e:
                print(f"구글 스프레드시트 아이디 삭제 중 오류 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:
                    time.sleep(5)
        
        print("구글 스프레드시트 아이디 삭제 실패: 최대 재시도 횟수(10회)에 도달했습니다.")
        return False
        
    finally:
        # 6. 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def 메인_프로그램():
    """메인 프로그램"""
    driver = None
    try:
        # 키워드 입력받기 (프로그램 시작 전)
        검색어 = 키워드_입력받기()
        
        if 검색어 is None:
            print("키워드를 읽어올 수 없어 프로그램을 종료합니다.")
            return False
        
        # 크롬 드라이버 설정
        print("크롬 드라이버를 설정 중...")
        driver = 크롬_드라이버_설정()
        
        # 네이버 사이트 실행
        if not 네이버_사이트_실행(driver):
            print("네이버 사이트 실행에 실패했습니다.")
            return False
        
        # 네이버 검색 실행
        if not 네이버_검색_실행(driver, 검색어):
            print("검색 실행에 실패했습니다.")
            return False
        
        # 카페/블로그 상호 크롤링
        상호_목록 = 카페블로그_상호_크롤링(driver)
        
        if 상호_목록:
            상위_5개 = 상호_출력(상호_목록)
            순위_엑셀_저장(검색어, 상위_5개)
            return True
        else:
            print("카페/블로그 상호를 찾을 수 없습니다.")
            return False
        
    except Exception as e:
        print(f"프로그램 실행 중 오류 발생: {e}")
        return False
    finally:
        # 작업 완료 후 크롬창 닫기
        if driver is not None:
            try:
                print("작업이 완료되어 크롬창을 닫습니다...")
                driver.quit()
                print("크롬창이 성공적으로 닫혔습니다.")
            except Exception as e:
                print(f"크롬창 닫기 중 오류: {e}")

# 뷰순위 크롤링은 별도로 실행하지 않음 (main() 함수 내에서 처리)
# if __name__ == "__main__":
#     result = 메인_프로그램()

import pandas as pd
import time
import datetime
import sys
import os
import subprocess

def 다음_스크립트_실행(스크립트명):
    """다음 스크립트를 실행하는 함수"""
    try:
        if os.path.exists(스크립트명):
            print(f"{스크립트명} 파일을 찾았습니다. 실행을 시작합니다...")
            # 작업 디렉토리를 현재 스크립트 디렉토리로 변경
            subprocess.run([sys.executable, 스크립트명], 
                         cwd=os.path.dirname(os.path.abspath(__file__)), 
                         check=True)
            print(f"{스크립트명} 실행이 완료되었습니다!")
        else:
            print(f"오류: {스크립트명} 파일을 찾을 수 없습니다.")
            
    except subprocess.CalledProcessError as e:
        print(f"{스크립트명} 실행 중 오류 발생: {e}")
    except Exception as e:
        print(f"{스크립트명} 실행 중 예상치 못한 오류: {e}")

def 작업아이디_포스팅수순_가져오기():
    """아이디2 구글 시트에서 실시간 포스팅수 기준으로 아이디를 가져오는 함수.
    작업아이디.xlsx 파일 없이 구글 시트를 직접 조회하여 항상 최신 포스팅수 반영."""
    try:
        # 1. 아이디2 구글 스프레드시트에서 최신 계정정보 가져오기
        print("아이디2 구글 시트에서 실시간 계정정보 가져오는 중...")
        df = 구글스프레드시트_계정정보_가져오기()
        if df.empty:
            print("구글 스프레드시트에서 계정정보를 가져올 수 없습니다.")
            return pd.DataFrame()
        print(f"구글 스프레드시트에서 {len(df)}개의 아이디를 가져왔습니다.")

        # 2. 지명키워드 캐시에서 사용아이디 값 읽어 필터링
        사용아이디_값 = ""
        try:
            지명키워드_df = 지명키워드_df_가져오기()
            if not 지명키워드_df.empty and '사용아이디' in 지명키워드_df.columns:
                _raw = str(지명키워드_df.iloc[0]['사용아이디']).strip()
                if _raw.lower() not in ['nan', 'none', '']:
                    사용아이디_값 = _raw
        except Exception as e:
            print(f"사용아이디 읽기 중 오류 (필터링 건너뜀): {e}")

        if 사용아이디_값:
            print(f"사용아이디 '{사용아이디_값}'로 계정 필터링")
            df = 사용아이디로_계정_필터링(사용아이디_값, df)
            print(f"필터링 후 {len(df)}개의 아이디가 남았습니다.")

        # 3. 필수 컬럼 결측치가 있는 행 제거
        df = df.dropna(subset=['아이디', '비번', '홍보문구', '하나노란'])

        if len(df) == 0:
            print("유효한 계정 정보가 없습니다.")
            return pd.DataFrame()

        # 4. 하루최대포스팅수가 0인 아이디들 제외
        if '하루최대포스팅수' in df.columns:
            df['하루최대포스팅수'] = pd.to_numeric(df['하루최대포스팅수'], errors='coerce')
            제외된_아이디들 = df[
                (df['하루최대포스팅수'] <= 0) |
                (df['하루최대포스팅수'].isna())
            ]
            if len(제외된_아이디들) > 0:
                print("하루최대포스팅수가 0 이하로 제외된 아이디들:")
                for _, row in 제외된_아이디들.iterrows():
                    print(f"  {row['아이디']}: 하루최대포스팅수 = {row['하루최대포스팅수']}")
            df = df[
                (df['하루최대포스팅수'] > 0) &
                (df['하루최대포스팅수'].notna())
            ]
            print(f"하루최대포스팅수가 0 이하인 아이디를 제외한 후 {len(df)}개의 아이디가 남았습니다.")

        if len(df) == 0:
            print("하루최대포스팅수 제한으로 인해 사용 가능한 아이디가 없습니다.")
            return pd.DataFrame()

        # 5. 포스팅수가 적은 순서로 정렬 (실시간 값 기준)
        if '포스팅수' in df.columns:
            df['포스팅수'] = pd.to_numeric(df['포스팅수'], errors='coerce').fillna(0)
            df = df.sort_values('포스팅수', ascending=True)
            print("포스팅수가 적은 순서로 아이디를 정렬했습니다.")
            print("포스팅수 순서:")
            for idx, row in df.iterrows():
                print(f"  {row['아이디']}: {row['포스팅수']}개")
        else:
            print("포스팅수 컬럼이 없어 기본 순서로 진행합니다.")
            df['포스팅수'] = 0

        # 6. 필수 컬럼 없으면 기본값 추가
        if '로그인간격_분' not in df.columns:
            df['로그인간격_분'] = 30
        if '마지막로그인시간' not in df.columns:
            df['마지막로그인시간'] = ''

        return df

    except Exception as e:
        print(f"계정정보 가져오기 실패: {e}")
        return pd.DataFrame()

def 지명키워드에서_지명_추출():
    """지명키워드.xlsx에서 지명 값을 추출하는 함수"""
    try:
        # 지명키워드.xlsx 파일 읽기
        df = 지명키워드_df_가져오기()
        
        if "지명키워드" not in df.columns:
            print("오류: 지명키워드.xlsx에 '지명키워드' 컬럼이 없습니다.")
            return None
        
        # 첫 번째 지명키워드에서 지명 부분만 추출
        첫번째_지명키워드 = df["지명키워드"].dropna().iloc[0]
        
        # 지명키워드에서 지명 부분만 분리 (예: "서울맛집" → "서울")
        # 이 부분은 지명키워드 형식에 따라 로직이 달라져야 함
        지명 = 지명키워드에서_지명_분리(첫번째_지명키워드)
        
        print(f"지명키워드.xlsx에서 추출된 지명: {지명}")
        return 지명
        
    except Exception as e:
        print(f"지명키워드에서 지명 추출 실패: {e}")
        return None

def 지명키워드에서_지명_분리(지명키워드):
    """지명키워드에서 지명 부분만 분리하는 함수"""
    try:
        # Google Sheets에서 가능한 지명 목록 가져오기
        df = 구글_시트_읽기(지명업체키워드_스프레드시트_ID)
        if df is None:
            print("Google Sheets에서 데이터를 읽어올 수 없습니다.")
            return None
        
        if "지명" not in df.columns:
            print("오류: Google Sheets에 '지명' 컬럼이 없습니다.")
            return None
        
        가능한_지명들 = df["지명"].dropna().tolist()
        
        # 지명키워드에서 가장 긴 지명을 찾기 (예: "서울강남맛집" → "서울강남")
        찾은_지명 = None
        최대_길이 = 0
        
        for 지명 in 가능한_지명들:
            if 지명 in 지명키워드 and len(지명) > 최대_길이:
                찾은_지명 = 지명
                최대_길이 = len(지명)
        
        if 찾은_지명:
            print(f"지명키워드 '{지명키워드}'에서 지명 '{찾은_지명}' 추출")
            return 찾은_지명
        else:
            print(f"지명키워드 '{지명키워드}'에서 지명을 찾을 수 없습니다.")
            return None
            
    except Exception as e:
        print(f"지명키워드에서 지명 분리 실패: {e}")
        return None


def 사용아이디_중복_필터링(지명_행, 계정정보_df):
    """지명 행의 사용아이디와 중복되는 계정만 필터링"""
    try:
        # 지명 행에서 사용아이디 값 가져오기
        if "사용아이디" not in 지명_행.index:
            print("오류: 지명 행에 '사용아이디' 컬럼이 없습니다.")
            return 계정정보_df  # 필터링 실패 시 전체 반환
        
        사용아이디_목록 = str(지명_행["사용아이디"]).split(",")  # 쉼표로 구분된 아이디들
        사용아이디_목록 = [아이디.strip() for 아이디 in 사용아이디_목록 if 아이디.strip()]
        
        print(f"지명 '{지명_행['지명']}'의 사용아이디: {사용아이디_목록}")
        
        # 중복되는 아이디만 필터링
        중복_계정 = 계정정보_df[계정정보_df["아이디"].isin(사용아이디_목록)]
        
        print(f"중복되는 계정 수: {len(중복_계정)}개")
        return 중복_계정
        
    except Exception as e:
        print(f"사용아이디 중복 필터링 실패: {e}")
        return 계정정보_df  # 필터링 실패 시 전체 반환

def main():
    global 겹치는_상호_제거_사용, 겹치는_개수, 포스팅작업요청_값_있음
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    순위_파일 = resource_path("뷰순위.xlsx")
    
    # 포스팅 작업요청 스프레드시트에 값이 있는지 확인 (전역 변수 사용)
    if 포스팅작업요청_값_있음:
        print("\n포스팅 작업요청 스프레드시트에 값이 있어 '포스팅 작업요청' 경로로 진행합니다.")
        if 포스팅작업요청_처리():
            print("\n포스팅 작업요청 처리 완료. 작업아이디.xlsx 파일을 가지고 다음 단계로 진행합니다.")
        else:
            print("\n포스팅 작업요청 처리 실패 또는 작업 가능한 행이 없습니다. 원래 경로로 진행합니다.")
            # 원래 경로로 진행
            # 작업아이디.xlsx 파일 생성 완료 후 기존 로직 계속 진행
            # 기준 개수를 3으로 고정 (겹치는 상호 제거 기능 사용 시에만 체크)
            if 겹치는_상호_제거_사용:
                기준_개수 = 3
                print(f"기준 개수: {기준_개수}")
                
                if 겹치는_개수 >= 기준_개수:
                    print(f"겹치는 상호가 {기준_개수}개 이상입니다. 프로그램 시작으로 돌아갑니다.")
                    프로그램_같은_터미널_재시작("겹치는 상호 기준 초과 (분기 경로)")
                else:
                    print(f"겹치는 상호가 {기준_개수}개 미만입니다. 다음 단계로 진행합니다.")
            else:
                print("겹치는 상호 제거 기능을 사용하지 않아 겹치는 개수 체크를 건너뜁니다. 다음 단계로 진행합니다.")
            
            # 다음 단계로 진행 (블로그 제목 생성)
            # 분기경로에서는 뷰순위 확인 불필요 (작업아이디.xlsx만 생성)
            # 메인_프로그램() 호출 제거
    else:
        # 포스팅 작업요청 스프레드시트에 값이 없어 기존 경로로 진행 (이미 전역 레벨에서 확인 완료)
        # 원래 경로: 지명키워드 파일 생성 후 뷰순위 확인 및 생성
        print("\n=== 원래 경로: 지명키워드 파일 생성 완료 후 뷰순위 확인 ===")
        try:
            메인_프로그램()
            print("✅ 뷰순위 확인 및 뷰순위.xlsx 파일 생성 완료")
        except Exception as e:
            print(f"⚠️ 뷰순위 확인 중 오류 발생: {e}")
            중요_작업_로그_저장(f"뷰순위 확인 중 오류: {e}")
    
    # 겹치는_상호_제거_사용이 True이고 겹치는_개수가 아직 계산되지 않았으면 계산
    if 겹치는_상호_제거_사용 and 겹치는_개수 == 0:
        겹치는_개수 = 엑셀_상호_비교(순위_파일)
    
    # 분기 경로에서는 포스팅작업요청_처리()에서 이미 작업아이디.xlsx를 생성했으므로 건너뜀
    # 원래 경로에서만 "새로운 공식으로 작업아이디.xlsx 생성" 실행
    if not 포스팅작업요청_값_있음:
        # 새로운 공식으로 작업아이디.xlsx 생성
        try:
            print("\n=== 새로운 공식으로 작업아이디.xlsx 생성 시작 ===")
            
            # 1. 구글 스프레드시트 → 계정정보 가져오기
            print("1단계: 구글 스프레드시트에서 계정정보 가져오기")
            id_df = 구글스프레드시트_계정정보_가져오기()
            if id_df.empty:
                print("구글 스프레드시트에서 계정정보를 가져올 수 없습니다.")
                return
            
            # 2-3. 겹치는 상호 제거 (선택적)
            if 겹치는_상호_제거_사용:
                # 2. 뷰순위.xlsx → 이미 작업된 상호 확인
                print("2단계: 뷰순위.xlsx에서 이미 작업된 상호 확인")
                rank_df = pd.read_excel(순위_파일)
                
                # 3. 겹치는 상호 제거 → 중복 작업 방지
                print("3단계: 겹치는 상호 제거")
                id_titles = set(id_df['상호'].astype(str).str.strip())
                rank_titles = set(rank_df['상호'].astype(str).str.strip())
                겹치는_상호 = id_titles & rank_titles
                작업_df = id_df[~id_df['상호'].astype(str).str.strip().isin(겹치는_상호)]
                print(f"겹치는 상호 제거 후 남은 계정 수: {len(작업_df)}개")
            else:
                print("2-3단계: 겹치는 상호 제거 기능을 사용하지 않아 전체 계정을 사용합니다.")
                작업_df = id_df.copy()
                print(f"전체 계정 수: {len(작업_df)}개")
            
            # 4. 지명키워드.xlsx 파일에서 지명 값 가져오기
            print("4단계: 지명키워드.xlsx에서 지명 값 가져오기")
            현재_지명 = 지명키워드에서_지명_추출()
            지명_행 = None  # 지명_행 변수 초기화
            
            if 현재_지명 is None:
                print("지명을 추출할 수 없어 전체 계정을 사용합니다.")
            else:
                # 5. 지명키워드.xlsx에서 사용아이디 값 가져오기
                print(f"5단계: 지명키워드.xlsx에서 사용아이디 값 가져오기")
                try:
                    지명키워드_df = 지명키워드_df_가져오기()
                    if not 지명키워드_df.empty and '사용아이디' in 지명키워드_df.columns:
                        사용아이디_값 = str(지명키워드_df.iloc[0]['사용아이디']).strip()
                        if 사용아이디_값 == 'nan':
                            사용아이디_값 = ""
                        print(f"지명키워드.xlsx에서 사용아이디 값 가져오기 성공: '{사용아이디_값}'")
                        
                        if 사용아이디_값 and 사용아이디_값.strip():
                            # 6. 사용아이디 값으로 계정 필터링
                            print("6단계: 사용아이디로 계정 필터링")
                            작업_df = 사용아이디로_계정_필터링(사용아이디_값, 작업_df)
                            print(f"사용아이디 '{사용아이디_값}'에 해당하는 계정 수: {len(작업_df)}개")
                        else:
                            print("사용아이디 값이 비어있어 전체 계정을 사용합니다.")
                    else:
                        print("지명키워드.xlsx 파일이 비어있거나 사용아이디 컬럼이 없어 전체 계정을 사용합니다.")
                except Exception as e:
                    print(f"작업큐 캐시 읽기 중 오류 발생: {e}")
                    print("오류로 인해 전체 계정을 사용합니다.")
            
            # 7. 필수 컬럼 추가 → 작업 진행에 필요한 정보
            print("7단계: 필수 컬럼 추가")
            if '포스팅수' not in 작업_df.columns:
                작업_df['포스팅수'] = 0
            if '로그인간격_분' not in 작업_df.columns:
                작업_df['로그인간격_분'] = 30
            if '마지막로그인시간' not in 작업_df.columns:
                작업_df['마지막로그인시간'] = ''
            
            # 7-0. 하루최대포스팅수가 0인 아이디 제외
            print("7-0단계: 하루최대포스팅수 필터링")
            if '하루최대포스팅수' in 작업_df.columns:
                # 하루최대포스팅수를 숫자로 변환 (문자열일 수 있으므로)
                작업_df['하루최대포스팅수'] = pd.to_numeric(작업_df['하루최대포스팅수'], errors='coerce')
                
                # 하루최대포스팅수가 0 이하인 아이디들 필터링
                필터링_전_개수 = len(작업_df)
                작업_df = 작업_df[
                    (작업_df['하루최대포스팅수'] > 0) & 
                    (작업_df['하루최대포스팅수'].notna())
                ]
                필터링_후_개수 = len(작업_df)
                print(f"하루최대포스팅수가 0 이하인 아이디를 제외한 후 {필터링_후_개수}개의 아이디가 남았습니다. (제외: {필터링_전_개수 - 필터링_후_개수}개)")
                
                if 필터링_후_개수 == 0:
                    print("하루최대포스팅수 제한으로 인해 사용 가능한 아이디가 없습니다.")
                    return
            else:
                print("하루최대포스팅수 컬럼이 없어 필터링을 건너뜁니다.")
            
            # 7-1. 로그인금지시간대 필터링 → 현재 시간에 로그인 불가능한 아이디 제외
            print("7-1단계: 로그인금지시간대 필터링")
            print(f"현재 시간: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일'][datetime.datetime.now().weekday()]})")
            
            시간제한_아이디들 = []
            for idx, row in 작업_df.iterrows():
                아이디 = row['아이디']
                if not 로그인금지시간대_확인(아이디, 작업_df):
                    시간제한_아이디들.append(아이디)
                    print(f"  → 아이디 '{아이디}'는 현재 시간에 로그인이 금지되어 제외됩니다.")
                else:
                    print(f"  → 아이디 '{아이디}'는 현재 시간에 로그인 가능합니다.")
            
            # 시간 제한에 걸린 아이디들 제외
            작업_df = 작업_df[~작업_df['아이디'].isin(시간제한_아이디들)]
            print(f"로그인금지시간대 확인 후 남은 계정 수: {len(작업_df)}개")
            
            if len(작업_df) == 0:
                print("로그인금지시간대 제한으로 인해 사용 가능한 아이디가 없습니다.")
                print("다른 시간에 다시 시도해주세요.")
                return
            
            # 8. 계정 필터링 완료 (구글 시트 직접 사용, xlsx 저장 없음)
            print(f"8단계: 계정 필터링 완료 - 사용 가능 계정 {len(작업_df)}개")
            
            if 현재_지명:
                중요_작업_로그_저장(f"계정 필터링 완료 - 현재 작업 지명: {현재_지명}, 계정 수: {len(작업_df)}개")
            
            # 지명_행을 전역 변수로 저장하여 이미지 삽입에서 사용
            global 현재_지명_행
            if 지명_행 is not None:
                현재_지명_행 = 지명_행
                print(f"지명 행 정보를 전역 변수로 저장했습니다. 하나노란 값: {지명_행.get('하나노란', '없음')}")
            else:
                현재_지명_행 = None
            
        except Exception as e:
            print(f"계정 필터링 중 오류 발생: {e}")
            return
    else:
        print("분기 경로에서는 포스팅작업요청_처리()에서 이미 계정 필터링을 완료했으므로 건너뜁니다.")
    
    # 기준 개수를 3으로 고정 (겹치는 상호 제거 기능 사용 시에만 체크)
    if 겹치는_상호_제거_사용:
        기준_개수 = 3
        print(f"기준 개수: {기준_개수}")
        
        if 겹치는_개수 >= 기준_개수:
            print(f"겹치는 상호가 {기준_개수}개 이상입니다. 프로그램 시작으로 돌아갑니다.")
            # 현재 파일을 다시 실행 (프로그램 시작으로 돌아가기)
            print("현재 프로그램을 처음부터 다시 실행합니다.")
            프로그램_같은_터미널_재시작("겹치는 상호 기준 초과")
        else:
            print(f"겹치는 상호가 {기준_개수}개 미만입니다. 다음 단계로 진행합니다.")
    else:
        print("겹치는 상호 제거 기능을 사용하지 않아 겹치는 개수 체크를 건너뜁니다. 다음 단계로 진행합니다.")
        # 현재 파일의 다음 단계 실행 (블로그 제목 생성)
        메인_프로그램()

# 함수 정의 완료 후 실행

import google.generativeai as genai
# 공식 최신 방식: configure 함수로 API 키 직접 입력
genai.configure(api_key="AIzaSyAAVuPcNDmzs_2I0eIdprja-IqNEYSaXpo")
from google.generativeai.generative_models import GenerativeModel

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import time
import random
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import os
import sys
import subprocess

# 현재 스크립트의 디렉토리를 기준으로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def 파일_경로_생성(파일명):
    """스크립트 디렉토리 기준으로 파일 경로 생성"""
    return resource_path(파일명)

def 다음_스크립트_실행(스크립트명):
    """다음 스크립트를 실행하는 함수"""
    try:
        스크립트_경로 = 파일_경로_생성(스크립트명)
        
        if os.path.exists(스크립트_경로):
            print(f"{스크립트명} 파일을 찾았습니다. 실행을 시작합니다...")
            # 작업 디렉토리를 스크립트 디렉토리로 변경
            subprocess.run([sys.executable, 스크립트_경로], 
                         cwd=SCRIPT_DIR, check=True)
            print(f"{스크립트명} 실행이 완료되었습니다!")
        else:
            print(f"오류: {스크립트_경로} 파일을 찾을 수 없습니다.")
            
    except subprocess.CalledProcessError as e:
        print(f"{스크립트명} 실행 중 오류 발생: {e}")
    except Exception as e:
        print(f"{스크립트명} 실행 중 예상치 못한 오류: {e}")

# 모델 설정 (Gemini 2.5 Flash)
GEMINI_텍스트_모델 = 'gemini-2.5-flash'
GEMINI_텍스트_모델_폴백 = 'gemini-pro'
try:
    model = GenerativeModel(GEMINI_텍스트_모델)
    print(f"{GEMINI_텍스트_모델} 모델 로드 성공")
except Exception as e:
    print(f"{GEMINI_텍스트_모델} 로드 실패: {e}")
    try:
        model = GenerativeModel(GEMINI_텍스트_모델_폴백)
        print(f"{GEMINI_텍스트_모델_폴백} 모델 로드 성공 (폴백)")
    except Exception as e2:
        print(f"{GEMINI_텍스트_모델_폴백} 로드 실패: {e2}")
        try:
            model = GenerativeModel('gemini-pro')
            print("gemini-pro 모델 로드 성공 (폴백)")
        except Exception as e3:
            print(f"gemini-pro 로드 실패: {e3}")
            print("모든 모델 로드에 실패했습니다.")
            model = None

def 크롬_드라이버_설정():
    """크롬 드라이버를 설정하는 함수 (undetected-chromedriver)"""
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--window-size=1200,800")
    driver = uc_크롬_드라이버_생성(chrome_options)
    try:
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    except Exception:
        pass
    return driver

def 네이버_사이트_실행(driver):
    """네이버 사이트를 실행하는 함수"""
    try:
        # === 네이버 사이트 실행 ===
        print("\n🌐 네이버 사이트를 실행합니다...")
        driver.get("https://www.naver.com")
        time.sleep(3)
        
        print("✅ 네이버 사이트 로딩 완료")
        print(f"현재 URL: {driver.current_url}")
        
        return True
        
    except Exception as e:
        print(f"❌ 네이버 사이트 실행 중 오류: {e}")
        return False

def 키워드_입력받기():
    """지명키워드.xlsx 파일에서 지명키워드를 가져오는 함수"""
    print("\n=== 블로그 제목 학습 및 생성 프로그램 ===")
    print("돌쇠가 만든 네이버 검색 + Gemini AI 블로그 제목 생성기입니다!")
    print()
    
    try:
        # 지명키워드.xlsx 파일 읽기
        지명키워드_df = 지명키워드_df_가져오기()
        
        # 키워드 컬럼이 있는지 확인
        if '지명키워드' in 지명키워드_df.columns:
            지명키워드_목록 = 지명키워드_df['지명키워드'].dropna().astype(str).unique().tolist()
            print(f"지명키워드.xlsx에서 {len(지명키워드_목록)}개의 지명키워드를 찾았습니다.")
            
            if 지명키워드_목록:
                print("사용 가능한 지명키워드:")
                for i, 지명키워드 in enumerate(지명키워드_목록[:10], 1):  # 처음 10개만 표시
                    print(f"{i}. {지명키워드}")
                if len(지명키워드_목록) > 10:
                    print(f"... 외 {len(지명키워드_목록) - 10}개 더")
                
                # 첫 번째 키워드 사용
                선택된_지명키워드 = 지명키워드_목록[0]
                print(f"\n선택된 지명키워드: {선택된_지명키워드}")
                return 선택된_지명키워드
            else:
                print("지명키워드가 없습니다.")
                return None
        else:
            print("지명키워드.xlsx 파일에 '지명키워드' 컬럼이 없습니다.")
            print("사용 가능한 컬럼:", list(지명키워드_df.columns))
            return None
            
    except FileNotFoundError:
        print("지명키워드.xlsx 파일을 찾을 수 없습니다.")
        return None
    except Exception as e:
        print(f"지명키워드.xlsx 파일 읽기 중 오류: {e}")
        return None

def 네이버_검색_실행(driver, 검색어):
    """네이버에서 검색을 실행하는 함수"""
    try:
        print(f"'{검색어}' 검색을 실행합니다...")
        
        # 검색창 찾기
        검색창 = driver.find_element(By.CSS_SELECTOR, "#query")
        검색창.clear()
        검색창.send_keys(검색어)
        검색창.send_keys(Keys.RETURN)
        
        time.sleep(3)
        
        print("검색 완료")
        print(f"현재 URL: {driver.current_url}")
        
        # 블로그 탭 클릭
        try:
            print("블로그 탭을 클릭합니다...")
            블로그_탭 = driver.find_element(By.CSS_SELECTOR, "a[href*='tab.blog.all']")
            블로그_탭.click()
            time.sleep(2)
            print("블로그 탭 클릭 완료")
        except Exception as e:
            print(f"블로그 탭 클릭 중 오류: {e}")
            # 블로그 탭을 찾지 못한 경우 다른 방법 시도
            try:
                블로그_탭들 = driver.find_elements(By.CSS_SELECTOR, "a.tab")
                for 탭 in 블로그_탭들:
                    if "블로그" in 탭.text:
                        탭.click()
                        time.sleep(2)
                        print("블로그 탭 클릭 완료 (대안 방법)")
                        break
            except:
                print("블로그 탭을 찾을 수 없습니다. 전체 검색 결과에서 블로그를 찾습니다.")
        
        return True
        
    except Exception as e:
        print(f"검색 실행 중 오류: {e}")
        return False

def 블로그_제목_크롤링(driver):
    """검색 결과에서 블로그 제목만 크롤링하는 함수"""
    try:
        제목_목록 = []
        
        print("블로그 제목 크롤링을 시작합니다...")
        
        # 네이버 검색 결과의 블로그 제목 영역 선택자들 (우선순위 순)
        블로그_선택자들 = [
            # 1순위: 실제 네이버 블로그 제목 선택자 (가장 정확)
            "a.title_link[href*='blog.naver.com']",
            "a.title_link[href*='tistory.com']",
            "a.title_link[href*='ader.naver.com']",
            # 2순위: detail_box 내의 title_area 영역
            ".detail_box .title_area a.title_link",
            ".detail_box .title_area a",
            # 3순위: 네이버 블로그 제목 영역 (백업 선택자들)
            "a[href*='blog.naver.com']",
            "a[href*='tistory.com']",
            "a[href*='ader.naver.com']",
            ".name a[href*='blog.naver.com']",
            ".name a[href*='tistory.com']",
            ".title a[href*='blog.naver.com']",
            ".title a[href*='tistory.com']",
            ".link a[href*='blog.naver.com']",
            ".link a[href*='tistory.com']",
            # 4순위: 일반적인 제목 영역
            ".name",
            ".title",
            ".link",
            # 5순위: 추가 선택자들
            "a[class*='name']",
            "a[class*='title']",
            "a[class*='link']",
            "a[class*='tit']",
            "a[class*='txt']"
        ]
        
        블로그_개수 = 0
        
        for 선택자 in 블로그_선택자들:
            try:
                링크들 = driver.find_elements(By.CSS_SELECTOR, 선택자)
                print(f"{선택자} 선택자로 {len(링크들)}개 찾음")
                
                for 링크 in 링크들:
                    try:
                        URL = 링크.get_attribute("href")
                        제목 = 링크.text.strip()
                        
                        # mark 태그 제거 (검색어 하이라이트 제거)
                        if "<mark>" in 제목 or "</mark>" in 제목:
                            # 간단한 마크 태그 제거
                            제목 = 제목.replace("<mark>", "").replace("</mark>", "")
                        
                        # URL이 있고 제목이 있는 경우만
                        if URL and 제목 and len(제목) > 5:
                            # 블로그 URL 필터링 (ader.naver.com도 포함)
                            if ("blog.naver.com" in URL or "tistory.com" in URL or "ader.naver.com" in URL):
                                # 블로그 제목 필터링 (너무 긴 내용 제외)
                                if len(제목) <= 100 and not "..." in 제목:
                                    # 중복 제거
                                    if 제목 not in 제목_목록:
                                        제목_목록.append(제목)
                                        블로그_개수 += 1
                                        print(f"블로그 발견: {제목}")
                                        print(f"URL: {URL}")
                                        
                                        # 상위 10개만 수집
                                        if 블로그_개수 >= 10:
                                            break
                                        
                    except Exception as e:
                        continue
                        
                if 블로그_개수 >= 10:
                    break
                    
            except Exception as e:
                continue
        
        # 블로그를 찾지 못한 경우 더 넓은 범위로 검색
        if not 제목_목록:
            print("블로그 제목을 찾지 못했습니다. 더 넓은 범위로 검색합니다...")
            
            # detail_box 내의 모든 링크에서 블로그 찾기
            try:
                detail_boxes = driver.find_elements(By.CSS_SELECTOR, ".detail_box")
                print(f"detail_box 개수: {len(detail_boxes)}개")
                
                for box in detail_boxes:
                    try:
                        title_links = box.find_elements(By.CSS_SELECTOR, "a.title_link")
                        for 링크 in title_links:
                            try:
                                URL = 링크.get_attribute("href")
                                제목 = 링크.text.strip()
                                
                                # mark 태그 제거
                                if "<mark>" in 제목 or "</mark>" in 제목:
                                    제목 = 제목.replace("<mark>", "").replace("</mark>", "")
                                
                                if URL and 제목 and len(제목) > 5:
                                    if ("blog.naver.com" in URL or "tistory.com" in URL or "ader.naver.com" in URL):
                                        if len(제목) <= 100 and not "..." in 제목:
                                            if 제목 not in 제목_목록:
                                                제목_목록.append(제목)
                                                블로그_개수 += 1
                                                print(f"블로그 발견: {제목}")
                                                print(f"URL: {URL}")
                                                
                                                if 블로그_개수 >= 10:
                                                    break
                                            
                            except Exception as e:
                                continue
                                
                        if 블로그_개수 >= 10:
                            break
                            
                    except Exception as e:
                        continue
                        
            except Exception as e:
                print(f"detail_box 검색 중 오류: {e}")
                
                # 기존 방법으로 백업
                모든_링크들 = driver.find_elements(By.TAG_NAME, "a")
                print(f"전체 링크: {len(모든_링크들)}개")
                
                for 링크 in 모든_링크들:
                    try:
                        URL = 링크.get_attribute("href")
                        제목 = 링크.text.strip()
                        
                        if URL and 제목 and len(제목) > 5:
                            if ("blog.naver.com" in URL or "tistory.com" in URL or "ader.naver.com" in URL):
                                if len(제목) <= 100 and not "..." in 제목:
                                    if 제목 not in 제목_목록:
                                        제목_목록.append(제목)
                                        블로그_개수 += 1
                                        print(f"블로그 발견: {제목}")
                                        print(f"URL: {URL}")
                                        
                                        if 블로그_개수 >= 10:
                                            break
                                        
                    except Exception as e:
                        continue
        
        print(f"총 블로그 제목: {len(제목_목록)}개")
        return 제목_목록
        
    except Exception as e:
        print(f"블로그 제목 크롤링 중 오류: {e}")
        return []

추천모델_목록 = [
    "리코 IM C2010",
    "리코 IM C3010",
    "캐논 iR C3322",
    "캐논 iR C3326",
    # "삼성 SL-X6250LX",
    "리코 IM 2500",
    "후지 제록스 Apeos C325z",
    "브라더 MFC-L8900CDW",
    "엡손 EM-C800",
    "브라더 MFC-L6900DW",
    # "브라더 HL-L6400DW",
    "브라더 MFC-J3940DW",
]

# 설치후기형 제목·원고 생성용 대상 업종 예시
대상업종_목록 = [
    # 의료·헬스케어
    "동네 병원", "치과", "한의원", "안과", "피부과", "정형외과", "소아과",
    "산부인과", "이비인후과", "비뇨기과", "내과", "외과", "재활의학과",
    "요양병원", "동물병원",
    # 교육
    "영어학원", "보습학원", "수학학원", "태권도장", "피아노학원",
    "미술학원", "코딩학원", "입시학원", "어린이집", "유치원",
    # 법률·회계·금융
    "법무사 사무소", "법률사무소", "변호사 사무소", "회계사무소",
    "세무사 사무소", "공인노무사 사무소", "보험대리점", "증권사 지점",
    "은행 지점", "신용협동조합",
    # 부동산·건설
    "부동산 중개사무소", "건설현장 사무실", "건축사 사무소", "인테리어 업체",
    "분양사무소", "임대관리업체",
    # 제조·물류
    "제조업 공장", "물류창고 사무실", "인쇄소", "포장재 업체",
    "식품 제조업체", "의류 제조업체", "금속 가공업체",
    # 서비스업
    "헬스장", "필라테스 센터",
    "자동차 정비소", "사진관", "여행사",
    # IT·미디어·전문직
    "광고기획사", "IT 스타트업", "소프트웨어 개발사", "디자인 스튜디오",
    "영상 제작사", "웹 에이전시", "컨설팅 회사",
    # 무역·유통
    "무역회사", "도매상", "온라인 쇼핑몰 사무실", "편의점 본사",
    # 공공·단체
    "비영리 단체", "협동조합", "복지관", "교회·종교시설",
    # 기타
    "출판사", "번역회사", "렌터카 업체", "경비·보안업체",
]

설치후기_업종_원표시_확률 = 0.5


def _설치후기_대상업종_표기(대상업종):
    """설치후기형: 일정 확률로 대상업종 앞에 ○ 2~3개(띄어쓰기 없이) 붙이거나 원문 그대로 반환."""
    base = re.sub(r'^○+', '', str(대상업종).strip())
    if not base or base.lower() in ('nan', 'none'):
        return base
    if random.random() >= 설치후기_업종_원표시_확률:
        return base
    return '○' * random.randint(2, 3) + base


def _제목_글자수(제목):
    """블로그 제목 글자수 (앞 #·공백 제외, 띄어쓰기 포함)"""
    return len(str(제목).strip().lstrip('#').strip())


def _제목_최대_글자(유형=None):
    """유형별 제목 최대 글자수 (설치후기형은 업종·모델명 포함으로 상한 완화)"""
    if 유형 == "설치후기형":
        return 설치후기형_제목_최대_글자
    return 블로그_제목_최대_글자


def _제목_글자수_적합(제목, 유형=None):
    """블로그 제목 글자수 범위 확인 (유형별 최대 글자수 적용)"""
    n = _제목_글자수(제목)
    return 블로그_제목_최소_글자 <= n <= _제목_최대_글자(유형)


def _지명키워드_포함_서비스_단어(지명키워드):
    """지명키워드에 포함된 서비스 단어 (렌탈 또는 임대)"""
    kw = str(지명키워드).strip()
    if '렌탈' in kw:
        return '렌탈'
    if '임대' in kw:
        return '임대'
    return None


def _제목_서비스_단어_중복(제목, 지명키워드):
    """지명키워드에 렌탈/임대가 있을 때 제목에 같은 단어가 2회 이상이면 True"""
    서비스 = _지명키워드_포함_서비스_단어(지명키워드)
    if not 서비스:
        return False
    return str(제목).strip().count(서비스) >= 2


def _제목_서비스_단어_교정(제목, 지명키워드):
    """지명키워드 외 문구의 중복 렌탈/임대를 대체 단어로 1회 교정"""
    서비스 = _지명키워드_포함_서비스_단어(지명키워드)
    if not 서비스 or not _제목_서비스_단어_중복(제목, 지명키워드):
        return 제목
    대체 = '임대' if 서비스 == '렌탈' else '렌탈'
    kw = str(지명키워드).strip()
    t = str(제목).strip()
    idx = t.find(kw)
    if idx >= 0:
        앞 = t[:idx + len(kw)]
        뒤 = t[idx + len(kw):]
        if 서비스 in 뒤:
            뒤 = 뒤.replace(서비스, 대체, 1)
            return 앞 + 뒤
    first = t.find(서비스)
    if first >= 0:
        second = t.find(서비스, first + len(서비스))
        if second >= 0:
            return t[:second] + 대체 + t[second + len(서비스):]
    return t


def _제목_설치후기_표현_검사_키워드(표현):
    """프롬프트용 패턴을 제목 검증용 키워드로 변환"""
    if 표현 == '{대상업종} 설치 사례':
        return '설치 사례'
    return 표현


def _제목_설치후기_표현_포함(제목):
    """설치후기형 제목에 허용 표현이 1개 이상 포함되어 있는지"""
    t = str(제목).strip()
    return any(
        _제목_설치후기_표현_검사_키워드(expr) in t
        for expr in 설치후기형_제목_허용_표현_목록
    )


def _제목_설치후기_표현_부적합(제목):
    """설치후기형 제목이 허용 표현을 쓰지 않거나 금지 어투면 True"""
    t = str(제목).strip()
    금지 = ('설치했어요', '설치했습니다', '설치 다녀왔습니다', '설치하고 온', '설치하고 왔')
    if any(g in t for g in 금지):
        return True
    return not _제목_설치후기_표현_포함(제목)


def _제목_임대비_축약(제목):
    """제목 끝이 '임대 비', '렌탈 비'처럼 비용이 축약된 형태면 True"""
    import re
    t = str(제목).strip()
    return bool(re.search(r'(?:임대|렌탈)\s+비\s*$', t))


def _제목_임대비_교정(제목):
    """제목 끝 '임대 비'·'렌탈 비'를 '임대 비용'·'렌탈 비용'으로 교정"""
    import re
    t = str(제목).strip()
    t = re.sub(r'임대\s+비\s*$', '임대 비용', t)
    t = re.sub(r'렌탈\s+비\s*$', '렌탈 비용', t)
    return t


def _제목_서비스_단어_대체_지침(지명키워드):
    """지명키워드 서비스 단어 중복 방지 프롬프트 문구"""
    서비스 = _지명키워드_포함_서비스_단어(지명키워드)
    if 서비스 == '렌탈':
        return (
            "8. 지명키워드에 이미 '렌탈'이 포함되어 있으므로, 지명키워드·모델명 외 나머지 문구에는 "
            "'렌탈'을 다시 쓰지 말고 반드시 '임대'로 표현하세요 "
            "(예: '김해 복합기 렌탈 브라더 MFC-L8900CDW 사무실에 맞는 임대 방법' O, "
            "'...맞는 렌탈 방법' X)\n"
        )
    if 서비스 == '임대':
        return (
            "8. 지명키워드에 이미 '임대'가 포함되어 있으므로, 지명키워드·모델명 외 나머지 문구에는 "
            "'임대'를 다시 쓰지 말고 '렌탈'로 표현하세요 "
            "(예: '익산 복합기 임대 캐논 iR C3322 렌탈 전 체크리스트' O)\n"
        )
    return ""


def _유형별_블로그_제목_생성(유형, 개수, 지명키워드_목록, 학습_제목_텍스트, 최소_통과_개수=None):
    """특정 유형의 블로그 제목 후보를 생성·검증한다.
    최소_통과_개수 이상 검증 통과 시 성공 (개수는 AI 요청·후보 상한)."""
    if 개수 <= 0:
        return []
    if 최소_통과_개수 is None:
        최소_통과_개수 = 블로그_제목_생성_최소_통과_개수
    최소_통과_개수 = max(1, min(최소_통과_개수, 개수))
    try:
        배정_키워드 = [지명키워드_목록[0]] * 개수 if 지명키워드_목록 else [''] * 개수
        배정_모델 = [random.choice(추천모델_목록) for _ in range(개수)]
        배정_세부 = []
        배정_업종 = []
        if 유형 == FAQ_글유형:
            _faq_uid = _현재_작업_사용아이디()
            _faq_배정_카운트 = {}
            for i in range(개수):
                세부유형, 세부주제 = _FAQ_세부유형_배정(
                    배정_모델[i], _faq_uid, _faq_배정_카운트
                )
                배정_세부.append((세부유형, 세부주제))
            배정_텍스트 = "\n".join(
                [f"{i+1}) 지명키워드: {배정_키워드[i]} / 추천모델: {배정_모델[i]} / "
                 f"세부유형: {배정_세부[i][0]} / 세부주제: {배정_세부[i][1]}"
                 for i in range(개수)]
            )
        elif 유형 == "설치후기형":
            for i in range(개수):
                배정_업종.append(_설치후기_대상업종_표기(random.choice(대상업종_목록)))
            배정_텍스트 = "\n".join(
                [f"{i+1}) 지명키워드: {배정_키워드[i]} / 추천모델: {배정_모델[i]} / "
                 f"대상업종: {배정_업종[i]}"
                 for i in range(개수)]
            )
        else:
            배정_텍스트 = "\n".join(
                [f"{i+1}) 지명키워드: {배정_키워드[i]} / 추천모델: {배정_모델[i]}" for i in range(개수)]
            )

        if 유형 == "설치후기형":
            _허용_표현_예시 = ', '.join(설치후기형_제목_허용_표현_목록[:6])
            유형_지침 = (
                "설치후기형 — 하나렌탈 설치 담당자가 고객사에 복합기를 직접 설치한 현장 후기 제목.\n"
                "예: '익산 ○○영어학원 삼성 SL-X6250LX 복합기 렌탈 설치 후기', "
                "'군산 ○법률사무소 캐논 iR C3322 설치 현장 스토리', "
                "'전주 영어학원 리코 IM C3010 설치 사례' ({대상업종} 설치 사례 형태)\n"
                f"제목에 허용 표현 중 1개 이상 포함 ({_허용_표현_예시} 등).\n"
                "'설치했어요', '설치했습니다', '설치 다녀왔습니다'는 쓰지 않는다.\n"
                "배정된 대상업종(앞에 ○가 붙어 있으면 띄어쓰기 없이 그대로)을 제목에 정확히 1번 포함한다."
            )
        elif 유형 == FAQ_글유형:
            if not 배정_세부:
                세부유형, 세부주제 = _FAQ_세부유형_배정(
                    배정_모델[0] if 배정_모델 else '', _현재_작업_사용아이디()
                )
                유형_지침 = _FAQ_제목_유형_지침(세부유형, 세부주제)
            else:
                유형_지침 = (
                    "FAQ·비교·모델 소개형 — 아래 배정별 세부유형(FAQ형/비교형/모델 소개형)에 맞는 제목.\n"
                    "FAQ형: 고객 FAQ·질문 답변 / 비교형: vs·비교·차이 (비용은 '임대 비용'·'렌탈 비용', '임대 비' 축약 금지) "
                    "/ 모델 소개형: 모델 특징·토너·후기 등\n"
                    "각 제목은 배정된 세부유형·세부주제에 맞게 작성."
                )
        else:
            유형_지침 = (
                "정보형 — 복합기렌탈 정보를 정리해 주는 정보성 제목.\n"
                "예: '익산 복합기 렌탈 리코 IM C2010 비용부터 계약까지 총정리', "
                "'군산 복합기 렌탈 캐논 iR C3322 임대 전 체크리스트'\n"
                "'총정리', '비용', '방법', '비교', '체크리스트' 처럼 정보를 제공하는 어조로 쓴다."
            )

        _배정_kw = 배정_키워드[0] if 배정_키워드 else ''
        서비스_단어_요구 = _제목_서비스_단어_대체_지침(_배정_kw)
        설치후기_업종_요구 = ""
        if 유형 == "설치후기형":
            _허용_표현_전체 = ', '.join(설치후기형_제목_허용_표현_목록)
            설치후기_업종_요구 = (
                "9. 각 제목에 지정된 대상업종을 정확히 1번 포함 (○ 기호·개수·띄어쓰기 원문 그대로, 임의 변경 금지)\n"
                f"10. 각 제목에 허용 표현 1개 이상 포함: {_허용_표현_전체}\n"
                "    ('설치했어요', '설치 다녀왔습니다' 등 금지)\n"
            )
        faq_비용_요구 = ""
        if 유형 == FAQ_글유형:
            faq_비용_요구 = (
                "9. 비교형·비용 관련 제목은 '임대 비용'·'렌탈 비용'으로 쓰고 '임대 비', '렌탈 비' 축약 금지\n"
            )

        _제목_최대 = _제목_최대_글자(유형)
        프롬프트 = f"""다음은 참고용으로 검색된 블로그 제목들입니다:
{학습_제목_텍스트}

위 스타일을 참고하되, 복합기렌탈 블로그 제목을 정확히 {개수}개 생성하세요.
유형: {유형_지침}

**중요**: 현재는 2026년입니다. 2025년을 최신이라고 하지 마세요.

각 제목에는 아래에 순서대로 지정한 지명키워드와 추천모델을 각각 정확히 1번씩 넣으세요:
{배정_텍스트}

요구사항:
1. 각 제목에 지정된 지명키워드 1번, 지정된 추천모델명 1번을 정확히 포함
2. 지명키워드는 반드시 띄어쓰기 포함 원문 그대로 사용하세요 (예: '전주 복합기 임대'를 '전주복합기임대'로 붙여쓰기 금지)
3. 상호명 사용 금지, 쉼표(,) 콜론(:) 세미콜론(;) 사용 금지
4. "최고", "저렴", "강력 추천" 등 광고성 단어 금지
5. 번호 매기기 금지, 한 줄에 제목 하나씩만
6. 자연스럽고 구체적인 문장형으로 작성
7. 각 제목 글자수는 반드시 {블로그_제목_최소_글자}자 이상 {_제목_최대}자 이하 (띄어쓰기 포함, # 기호 제외)
{서비스_단어_요구}{설치후기_업종_요구}{faq_비용_요구}
제목 {개수}개만 한 줄에 하나씩 출력하세요."""

        재시도_횟수 = 0
        정리된 = []
        while True:
            try:
                print(f"[{유형}] 제목 {개수}개 생성 요청 중... (시도 {재시도_횟수 + 1})")
                response = model.generate_content(프롬프트)
                줄_목록 = response.text.strip().split('\n')
                후보 = []
                for 줄 in 줄_목록:
                    줄 = 줄.strip()
                    if not 줄 or len(줄) <= 5:
                        continue
                    if 줄.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.')):
                        줄 = 줄[2:].strip()
                    줄 = 줄.lstrip('·-•').strip()
                    if _제목_서비스_단어_중복(줄, _배정_kw):
                        교정 = _제목_서비스_단어_교정(줄, _배정_kw)
                        if (
                            not _제목_서비스_단어_중복(교정, _배정_kw)
                            and _제목_글자수_적합(교정, 유형)
                        ):
                            print(f"  제목 서비스단어 교정: {줄} -> {교정}")
                            줄 = 교정
                        else:
                            print(f"  제목 서비스단어 중복: {줄}")
                            continue
                    if _제목_임대비_축약(줄):
                        교정 = _제목_임대비_교정(줄)
                        if not _제목_임대비_축약(교정) and _제목_글자수_적합(교정, 유형):
                            print(f"  제목 임대비 교정: {줄} -> {교정}")
                            줄 = 교정
                        else:
                            print(f"  제목 임대비 축약: {줄}")
                            continue
                    if 유형 == "설치후기형" and _제목_설치후기_표현_부적합(줄):
                        print(f"  제목 설치후기 표현 부적합: {줄}")
                        continue
                    if _제목_글자수_적합(줄, 유형):
                        후보.append(줄)
                    else:
                        print(
                            f"  제목 글자수 불합격({_제목_글자수(줄)}자, "
                            f"허용 {블로그_제목_최소_글자}~{_제목_최대}자): {줄}"
                        )
                if len(후보) >= 최소_통과_개수:
                    정리된 = 후보[:개수]
                    break
                print(
                    f"검증 통과 {len(후보)}개 "
                    f"(최소 {최소_통과_개수}개 필요, 목표 {개수}개). 30초 후 재시도합니다..."
                )
                재시도_횟수 += 1
                time.sleep(30)
            except Exception as api_error:
                print(f"[{유형}] 제목 생성 중 오류: {api_error}")
                print("30초 후 재시도합니다...")
                재시도_횟수 += 1
                time.sleep(30)

        결과 = []
        for i in range(len(정리된)):
            item = {
                "제목": 정리된[i],
                "지명키워드": 배정_키워드[i],
                "유형": 유형,
                "추천모델": 배정_모델[i],
            }
            if 유형 == FAQ_글유형 and i < len(배정_세부):
                item["세부유형"] = 배정_세부[i][0]
                item["세부주제"] = 배정_세부[i][1]
            if 유형 == "설치후기형" and i < len(배정_업종):
                item["대상업종"] = 배정_업종[i]
            결과.append(item)
        return 결과
    except Exception as e:
        print(f"[{유형}] 제목 생성 함수 오류: {e}")
        return []


def 블로그_제목_생성(지명키워드, 학습_제목들, 지명키워드_목록=None):
    """유형_목록 중 이력 기준 사용 가능한 유형을 우선순위 선택해 제목 후보를 생성하고 1개를 선택.
    반환: [{"제목","지명키워드","유형","추천모델"}, ...]"""
    try:
        print("Gemini AI를 사용하여 블로그 제목을 생성합니다...")
        if model is None:
            print("모델이 로드되지 않았습니다. API 키를 확인해주세요.")
            return []

        if not 지명키워드_목록:
            지명키워드_목록 = [지명키워드] if 지명키워드 else [""]
        학습_제목_텍스트 = "\n".join([f"- {제목}" for 제목 in 학습_제목들[:15]])

        # 이력 시트 확인 후 아직 사용 안 한 글유형 우선 선택
        _uid_for_type = ''
        if _지명키워드_캐시_df is not None and '사용아이디' in _지명키워드_캐시_df.columns:
            _uid_for_type = str(_지명키워드_캐시_df.iloc[0]['사용아이디']).strip()
            if _uid_for_type.lower() in ('nan', 'none', ''):
                _uid_for_type = ''
        if not _uid_for_type and 설정_사용아이디:
            for _part in str(설정_사용아이디).split(','):
                _part = _part.strip()
                if _part:
                    _uid_for_type = _part
                    break

        if _uid_for_type and 지명키워드 and 설정_지명키워드_한도 > 0:
            사용가능_유형 = _지명키워드_사용가능_글유형(_uid_for_type, 지명키워드, 설정_지명키워드_한도)
        else:
            사용가능_유형 = _글유형_선택_후보_정리(list(유형_목록), _uid_for_type)

        선택_유형 = _글유형_우선순위_선택(사용가능_유형, _uid_for_type)
        print(f"선택된 유형: {선택_유형} (사용가능: {사용가능_유형})")
        _제목_지명목록 = [지명키워드] if 지명키워드 else (지명키워드_목록 or [''])
        후보 = _유형별_블로그_제목_생성(
            선택_유형, 블로그_제목_생성_후보_개수, _제목_지명목록, 학습_제목_텍스트
        )
        if not 후보:
            print("생성된 블로그 제목: 0개 (검증 통과 없음)")
            return []

        print(f"검증 통과 제목 후보: {len(후보)}개 ({선택_유형})")
        for i, 항목 in enumerate(후보, 1):
            print(f"  후보 {i}. [{항목['유형']}] {항목['제목']} ({_제목_글자수(항목['제목'])}자)")

        선택_수 = min(블로그_제목_선택_개수, len(후보))
        결과 = random.sample(후보, 선택_수)
        print(f"후보 {len(후보)}개 중 {선택_수}개 선택:")
        for i, 항목 in enumerate(결과, 1):
            print(f"{i}. [{항목['유형']}] {항목['제목']} ({_제목_글자수(항목['제목'])}자)")

        중요_작업_로그_저장(
            f"블로그 제목 생성 완료: 후보 {len(후보)}개 중 {선택_수}개 선택 ({선택_유형})"
        )
        return 결과
    except Exception as e:
        print(f"블로그 제목 생성 중 오류: {e}")
        return []

def 블로그제목_엑셀_저장(키워드, 생성된_제목_목록):
    """생성된 블로그 제목을 블로그제목.xlsx 파일로 저장하는 함수.
    생성된_제목_목록: [{"제목","지명키워드","유형","추천모델"}, ...]"""
    try:
        if not 생성된_제목_목록:
            print("저장할 제목이 없습니다.")
            return

        # 제목별로 정리된 데이터 (유형·추천모델 포함 → 원고 생성 시 동일 유형으로 이어짐)
        제목_데이터 = []
        for 항목 in 생성된_제목_목록:
            제목_데이터.append({
                "생성된제목": 항목.get("제목", ""),
                "지명키워드": 항목.get("지명키워드", ""),
                "키워드": 키워드,
                "유형": 항목.get("유형", ""),
                "추천모델": 항목.get("추천모델", ""),
                "대상업종": 항목.get("대상업종", ""),
                "세부유형": 항목.get("세부유형", ""),
                "세부주제": 항목.get("세부주제", ""),
            })

        # 새로운 데이터로 덮어쓰기 (기존 데이터 삭제)
        통합_df = pd.DataFrame(제목_데이터)

        # 블로그제목.xlsx 파일로 저장
        블로그제목_파일 = 파일_경로_생성("블로그제목.xlsx")
        통합_df.to_excel(블로그제목_파일, index=False)
        print(f"\n생성된 블로그 제목이 블로그제목.xlsx 파일에 저장되었습니다.")
        print(f"총 {len(통합_df)}개의 제목이 저장되어 있습니다.")

        # 블로그제목 저장 완료 로그
        작업_로그_저장(f"블로그제목.xlsx 저장 완료: {len(통합_df)}개 제목")

        # 저장된 데이터 확인
        print("\n저장된 데이터:")
        for i, row in 통합_df.iterrows():
            print(f"{i+1}. [{row.get('유형','')}] 생성된제목: {row['생성된제목']}")
            if row.get('세부유형'):
                print(f"   세부유형: {row.get('세부유형','')} / 세부주제: {row.get('세부주제','')}")
            print(f"   지명키워드: {row['지명키워드']}")
            print(f"   추천모델: {row.get('추천모델','')}")
            if row.get('대상업종'):
                print(f"   대상업종: {row.get('대상업종','')}")
            print(f"   키워드: {row['키워드']}")
            print()

    except Exception as e:
        print(f"블로그제목.xlsx 파일 저장 중 오류: {e}")

def 메인_프로그램():
    driver = None
    try:
        # 키워드 입력받기
        키워드 = 키워드_입력받기()
        
        # 키워드가 없으면 프로그램 종료
        if 키워드 is None:
            print("키워드를 가져올 수 없어 프로그램을 종료합니다.")
            return False
        
        # 지명키워드 캐시에서 지명키워드 목록 읽기
        지명키워드_목록 = None
        try:
            지명키워드_df = 지명키워드_df_가져오기()
            if '지명키워드' in 지명키워드_df.columns:
                지명키워드_목록 = 지명키워드_df['지명키워드'].dropna().astype(str).unique().tolist()
                print(f"지명키워드 캐시에서 {len(지명키워드_목록)}개의 지명키워드를 찾았습니다.")
                print(f"지명키워드 목록: {지명키워드_목록}")
            else:
                print("지명키워드 캐시에 '지명키워드' 컬럼이 없습니다.")
        except Exception as e:
            print(f"지명키워드 캐시 읽기 중 오류: {e}")

        # 크롬 드라이버 설정
        print("크롬 드라이버를 설정 중...")
        driver = 크롬_드라이버_설정()
        
        # 네이버 사이트 실행
        if not 네이버_사이트_실행(driver):
            print("네이버 사이트 실행에 실패했습니다.")
            return
        
        # 네이버 검색 실행
        if not 네이버_검색_실행(driver, 키워드):
            print("검색 실행에 실패했습니다.")
            return
        
        # 블로그 제목 크롤링
        학습_제목들 = 블로그_제목_크롤링(driver)
        
        if 학습_제목들:
            print(f"\n학습할 블로그 제목: {len(학습_제목들)}개")
            for i, 제목 in enumerate(학습_제목들[:5], 1):
                print(f"{i}. {제목}")
            
            # 블로그 제목 생성 (현재 작업 지명키워드만 사용)
            생성된_제목_지명_쌍 = 블로그_제목_생성(
                키워드, 학습_제목들, [키워드] if 키워드 else 지명키워드_목록
            )
            
            if 생성된_제목_지명_쌍:
                블로그제목_엑셀_저장(키워드, 생성된_제목_지명_쌍)
            else:
                print("블로그 제목 생성에 실패했습니다.")
        else:
            print("학습할 블로그 제목을 찾을 수 없습니다.")
        
        print("\n브라우저를 닫으려면 아무 키나 누르세요...")
        # input()  # 사용자 입력 대기 삭제
        # driver.quit() # 이미 457번째 줄에 들어가 있으므로 주석 처리
        # print("브라우저가 종료되었습니다.") # 이미 457번째 줄에 들어가 있으므로 주석 처리
        
    except Exception as e:
        print(f"프로그램 실행 중 오류 발생: {e}")
    finally:
        if driver is not None:
            driver.quit()
            print("브라우저가 종료되었습니다.")

if __name__ == "__main__":
    if _원고_재사용_모드:
        print("기존 원고 재사용 모드 - 블로그 제목 생성을 건너뜁니다.")
        중요_작업_로그_저장("기존 원고 재사용 모드 - 블로그 제목 생성 건너뜀")
    else:
        _블로그제목_생성_무한_재시도(메인_프로그램)

try:
    import google.generativeai as genai
    from google.generativeai.generative_models import GenerativeModel
except ImportError:
    print("Google Generative AI 라이브러리가 설치되지 않았습니다.")
    print("pip install google-generativeai 명령어로 설치해주세요.")
    exit(1)

import time
import random
import pandas as pd
import os

# API 키 설정
GOOGLE_API_KEY = "AIzaSyAAVuPcNDmzs_2I0eIdprja-IqNEYSaXpo"
import google.generativeai as genai
try:
    genai.configure(api_key=GOOGLE_API_KEY)
except:
    # 최신 버전에서는 다른 방법 사용
    pass

# 모델 설정 (Gemini 2.5 Flash)
GEMINI_텍스트_모델 = 'gemini-2.5-flash'
GEMINI_텍스트_모델_폴백 = 'gemini-pro'
try:
    model = GenerativeModel(GEMINI_텍스트_모델)
except Exception:
    try:
        model = GenerativeModel(GEMINI_텍스트_모델_폴백)
    except Exception:
        model = GenerativeModel('gemini-pro')

def 연관어_생성(지명키워드):
    """지명키워드를 이용해서 연관어 3~5개를 랜덤 생성하는 함수"""
    try:
        목표_개수 = random.randint(3, 5)
        print(f"연관어 생성 중... (지명키워드: {지명키워드}, 목표: {목표_개수}개)")

        지명키워드_붙임 = 지명키워드.replace(' ', '')
        prompt = f"""{지명키워드}와 관련된 연관어를 정확히 {목표_개수}개 생성해주세요.

요구사항:
1. 정확히 {목표_개수}개의 연관어만 생성
2. 각 연관어 앞에 # 기호를 붙여주세요
3. 한 줄에 하나씩 작성
4. 블로그 포스팅에 활용할 수 있는 키워드들로 구성
5. 검색 최적화(SEO)에 도움이 되는 키워드들로 구성
6. 지역명, 업종, 서비스, 특징 등을 포함
7. 반드시 띄어쓰기 없이 붙여서 작성 (예: #전주프린터임대 O, #전주 프린터 임대 X)

예시 형식:
#{지명키워드_붙임}렌탈
#{지명키워드_붙임}복합기
#{지명키워드_붙임}사무기기
연관어 {목표_개수}개만 생성해주세요."""

        # 생성이 성공할 때까지 30초 간격으로 무한 재시도
        재시도_횟수 = 0
        while True:
            try:
                print(f"연관어 생성 시도 중... (시도 {재시도_횟수 + 1})")
                response = model.generate_content(prompt)
                content = response.text.strip()

                # 줄바꿈으로 분리하고 #이 있는 것만 필터링
                연관어_리스트 = []
                for line in content.split('\n'):
                    line = line.strip()
                    if line.startswith('#') and line != '#':
                        # # 이후 텍스트에서 띄어쓰기 제거
                        line = '#' + line[1:].replace(' ', '')
                        연관어_리스트.append(line)

                # 목표 개수만큼만 추출 후 랜덤 셔플
                연관어_리스트 = 연관어_리스트[:목표_개수]
                random.shuffle(연관어_리스트)

                if 연관어_리스트:
                    print(f"연관어 생성 완료! ({len(연관어_리스트)}개)")
                    작업_로그_저장(f"연관어 생성 완료: {len(연관어_리스트)}개 연관어")
                    return 연관어_리스트
                else:
                    print("생성된 연관어가 없습니다. 30초 후 재시도합니다...")
                    재시도_횟수 += 1
                    time.sleep(30)
            except Exception as api_error:
                print(f"연관어 생성 중 오류가 발생했습니다: {str(api_error)}")
                print("30초 후 재시도합니다...")
                재시도_횟수 += 1
                time.sleep(30)

    except Exception as e:
        print(f"연관어 생성 중 오류가 발생했습니다: {str(e)}")
        return []

def 연관어_txt_저장(연관어_리스트, 지명키워드):
    """연관어를 txt 파일에 저장하는 함수"""
    try:
        # 현재 스크립트가 있는 폴더에 저장
        script_dir = os.path.dirname(os.path.abspath(__file__))
        filename = resource_path("연관어.txt")
        with open(filename, "w", encoding="utf-8") as f:
            # 3개씩 그룹으로 나누어서 줄바꿈
            결과 = []
            for i in range(0, len(연관어_리스트), 3):
                그룹 = 연관어_리스트[i:i+3]
                결과.append(" ".join(그룹))
            f.write("\n".join(결과))
        print(f"연관어가 '{filename}' 파일에 저장되었습니다.")
        return filename
    except Exception as e:
        print(f"txt파일 저장 중 오류가 발생했습니다: {str(e)}")
        return None

def 구글스프레드시트_작업완료확인_가져오기():
    """구글 스프레드시트에서 작업완료확인 데이터를 가져오는 함수"""
    import socket
    import time
    
    # 1. 파일 존재 여부 확인
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(키_파일_경로):
        print(f"오류: {키_파일_경로} 파일을 찾을 수 없습니다.")
        print("구글 스프레드시트 API 인증을 위한 서비스 계정 키 파일이 필요합니다.")
        return pd.DataFrame()
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 2. 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 3. 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                # 5. 진행상황 출력
                if 시도_횟수 > 0:
                    print(f"작업완료확인 가져오기 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 인증 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
                gc = gspread_authorize_with_timeout(creds)
                
                # 작업완료확인 스프레드시트 열기
                spreadsheet_id = '1z0q5NKTStkMm13V6JE8TlookZssrkzEbuca7QQhUI-M'
                spreadsheet = gspread_operation_with_timeout(
                    lambda: gc.open_by_key(spreadsheet_id),
                    timeout=20,
                    operation_name="스프레드시트 열기"
                )
                
                # 첫 번째 워크시트 선택
                worksheet = gspread_operation_with_timeout(
                    lambda: spreadsheet.get_worksheet(0),
                    timeout=20,
                    operation_name="워크시트 가져오기"
                )
                
                # 모든 데이터 가져오기
                all_values = gspread_operation_with_timeout(
                    lambda: worksheet.get_all_values(),
                    timeout=30,
                    operation_name="모든 데이터 가져오기"
                )
                
                if len(all_values) < 2:  # 헤더만 있거나 데이터가 없는 경우
                    print("작업완료확인 구글 스프레드시트에 데이터가 없습니다.")
                    return pd.DataFrame()
                
                # 헤더와 데이터 분리
                headers = all_values[0]
                data = all_values[1:]
                
                # 데이터프레임 생성
                df = pd.DataFrame(data, columns=headers)
                
                # 필요한 컬럼이 있는지 확인하고 기본값 설정
                required_columns = ['지명', '키워드', '지명키워드', '생성된제목', '아이디', '하나노란', '링크', '작성일시']
                for col in required_columns:
                    if col not in df.columns:
                        print(f"경고: '{col}' 컬럼이 작업완료확인 구글 스프레드시트에 없습니다.")
                        df[col] = ''
                
                if 시도_횟수 > 0:
                    print(f"작업완료확인 가져오기 성공! (시도 {시도_횟수 + 1}회)")
                
                print(f"작업완료확인 구글 스프레드시트에서 {len(df)}개의 기록을 가져왔습니다.")
                return df
                
            except (socket.timeout, TimeoutError):
                # 4. socket.timeout 예외 발생 시 30초 대기 후 재시도
                print(f"연결 타임아웃 발생 (시도 {시도_횟수 + 1}/10). 30초 대기 후 재시도합니다...")
                if 시도_횟수 < 9:
                    time.sleep(30)
                    
            except Exception as e:
                print(f"작업완료확인 가져오기 중 오류 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:
                    time.sleep(5)
        
        print("작업완료확인 가져오기 실패: 최대 재시도 횟수(10회)에 도달했습니다.")
        return pd.DataFrame()
        
    finally:
        # 6. 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def 포스팅작업요청_스프레드시트_행_삭제(행_번호):
    """포스팅 작업요청 스프레드시트에서 특정 행을 삭제하는 함수"""
    import socket
    import time
    
    # 1. 파일 존재 여부 확인
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(키_파일_경로):
        print(f"오류: {키_파일_경로} 파일을 찾을 수 없습니다.")
        return False
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 2. 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 3. 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                if 시도_횟수 > 0:
                    print(f"포스팅 작업요청 행 삭제 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 인증 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
                gc = gspread_authorize_with_timeout(creds)
                
                # 포스팅 작업요청 스프레드시트 열기
                spreadsheet = gspread_operation_with_timeout(
                    lambda: gc.open_by_key(포스팅작업요청_스프레드시트_ID),
                    timeout=20,
                    operation_name="스프레드시트 열기"
                )
                
                # 첫 번째 워크시트 선택
                worksheet = gspread_operation_with_timeout(
                    lambda: spreadsheet.get_worksheet(0),
                    timeout=20,
                    operation_name="워크시트 가져오기"
                )
                
                # 행 삭제 (gspread는 1-based 인덱스 사용)
                gspread_operation_with_timeout(
                    lambda: worksheet.delete_rows(행_번호),
                    timeout=20,
                    operation_name="행 삭제"
                )
                
                print(f"✅ 포스팅 작업요청 스프레드시트에서 {행_번호}번째 행을 성공적으로 삭제했습니다.")
                return True
                
            except (socket.timeout, TimeoutError):
                if 시도_횟수 < 9:
                    print(f"연결 타임아웃 발생 (시도 {시도_횟수 + 1}/10). 30초 대기 후 재시도합니다...")
                    time.sleep(30)
                else:
                    print("연결 타임아웃: 최대 재시도 횟수에 도달했습니다.")
                    
            except Exception as e:
                print(f"포스팅 작업요청 행 삭제 중 오류 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:
                    time.sleep(5)
                else:
                    print(f"포스팅 작업요청 행 삭제 실패: {e}")
        
        return False
        
    finally:
        # 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def 구글스프레드시트_작업완료확인_추가(지명, 키워드, 지명키워드, 생성된제목, 아이디, 하나노란, 링크, 작성일시):
    """구글 스프레드시트에 작업완료확인 데이터를 추가하는 함수"""
    import socket
    import time
    import os
    
    # 1. 파일 존재 여부 확인
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(키_파일_경로):
        print(f"오류: {키_파일_경로} 파일을 찾을 수 없습니다.")
        return False
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 2. 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 3. 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                # 5. 진행상황 출력
                if 시도_횟수 > 0:
                    print(f"작업완료확인 추가 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 인증 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
                gc = gspread_authorize_with_timeout(creds)
                
                # 작업완료확인 스프레드시트 열기
                spreadsheet_id = '1z0q5NKTStkMm13V6JE8TlookZssrkzEbuca7QQhUI-M'
                spreadsheet = gspread_operation_with_timeout(
                    lambda: gc.open_by_key(spreadsheet_id),
                    timeout=20,
                    operation_name="스프레드시트 열기"
                )
                
                # 첫 번째 워크시트 선택
                worksheet = gspread_operation_with_timeout(
                    lambda: spreadsheet.get_worksheet(0),
                    timeout=20,
                    operation_name="워크시트 가져오기"
                )
                
                # 헤더 확인 및 추가
                current_headers = gspread_operation_with_timeout(
                    lambda: worksheet.row_values(1),
                    timeout=20,
                    operation_name="헤더 가져오기"
                )
                required_headers = ['지명', '키워드', '지명키워드', '생성된제목', '아이디', '하나노란', '링크', '작성일시', '폴더']
                
                # 헤더가 없으면 추가
                if not current_headers:
                    gspread_operation_with_timeout(
                        lambda: worksheet.append_row(required_headers),
                        timeout=20,
                        operation_name="헤더 추가"
                    )
                    current_headers = required_headers
                
                # 새 데이터 행 추가 (폴더명 포함)
                try:
                    실행_폴더_전체경로 = os.getcwd()
                    실행_폴더명 = os.path.basename(실행_폴더_전체경로)
                except Exception:
                    실행_폴더명 = ""
                new_row = [지명, 키워드, 지명키워드, 생성된제목, 아이디, 하나노란, 링크, 작성일시, 실행_폴더명]
                gspread_operation_with_timeout(
                    lambda: worksheet.append_row(new_row),
                    timeout=20,
                    operation_name="데이터 행 추가"
                )
                
                if 시도_횟수 > 0:
                    print(f"작업완료확인 추가 성공! (시도 {시도_횟수 + 1}회)")
                
                print(f"작업완료확인 데이터가 구글 스프레드시트에 성공적으로 추가되었습니다.")
                print(f"저장된 링크: {링크}")
                
                # 작업완료확인 기록 후 작업 값 +1 증가
                if 하나노란 and 하나노란.strip():
                    print(f"\n🔍 작업완료확인 기록 후 작업 값 업데이트 중... (하나노란: {하나노란})")
                    try:
                        # 작업관리 스프레드시트에서 데이터 읽기
                        작업관리_df = 구글_시트_읽기(작업관리_스프레드시트_ID)
                        if 작업관리_df is not None:
                            # 하나노란 값으로 작업 값 업데이트
                            업데이트_성공, 새_작업값 = 작업값_업데이트(하나노란, 작업관리_df)
                            if 업데이트_성공:
                                print(f"✅ 작업완료확인 후 작업 값 업데이트 성공: {새_작업값}")
                                중요_작업_로그_저장(f"작업완료확인 후 작업 값 업데이트 성공: 하나노란={하나노란}, 새_작업값={새_작업값}")
                            else:
                                print("❌ 작업완료확인 후 작업 값 업데이트 실패")
                                오류_로그_저장(f"작업완료확인 후 작업 값 업데이트 실패: 하나노란={하나노란}")
                        else:
                            print("❌ 작업관리 스프레드시트 데이터 읽기 실패")
                            오류_로그_저장(f"작업관리 스프레드시트 데이터 읽기 실패: 하나노란={하나노란}")
                    except Exception as e:
                        print(f"❌ 작업완료확인 후 작업 값 업데이트 중 오류: {e}")
                        오류_로그_저장(f"작업완료확인 후 작업 값 업데이트 오류: {e}")
                else:
                    print("⚠️ 하나노란 값이 없어 작업 값 업데이트를 건너뜁니다.")
                
                return True
                
            except (socket.timeout, TimeoutError):
                # 4. socket.timeout 예외 발생 시 30초 대기 후 재시도
                print(f"연결 타임아웃 발생 (시도 {시도_횟수 + 1}/10). 30초 대기 후 재시도합니다...")
                if 시도_횟수 < 9:
                    time.sleep(30)
                    
            except Exception as e:
                print(f"작업완료확인 추가 중 오류 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:
                    time.sleep(5)
        
        print("작업완료확인 추가 실패: 최대 재시도 횟수(10회)에 도달했습니다.")
        return False
        
    finally:
        # 6. 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)



_SEO_렌탈_동의어_목록 = ['렌탈', '임대', '대여', '구독']

_SEO_장비_키워드_목록 = [
    'A3컬러복합기', 'A4컬러복합기',
    '흑백복합기', '칼라복합기', '컬러복합기',
    '플로터', '프린터', '복사기', '복합기',
]


def _제목_SEO_렌탈_동의어_지침(제목):
    """제목에 렌탈/임대/대여/구독이 있으면 본문에 나머지 동의어 포함 지침 반환"""
    if not 제목:
        return ''
    t = str(제목)
    제목에_포함 = [w for w in _SEO_렌탈_동의어_목록 if w in t]
    if not 제목에_포함:
        return ''
    포함_set = set(제목에_포함)
    필수_단어 = [w for w in _SEO_렌탈_동의어_목록 if w not in 포함_set]
    if not 필수_단어:
        return ''
    단어_목록 = ', '.join(f'"{w}"' for w in 필수_단어)
    return f"""[SEO 렌탈 동의어 — 반드시 준수]
· 제목에 쓴 표현과 짝이 되는 검색어를 본문 전체에 자연스럽게 각각 2회 이상 포함한다.
· 본문에 반드시 넣을 단어: {단어_목록}
· 키워드 나열처럼 보이지 않게 문장 속에 녹인다."""


def _제목_SEO_장비_동의어_지침(제목):
    """제목에 장비 키워드가 있으면 본문에 나머지 장비 동의어 포함 지침 반환"""
    if not 제목:
        return ''
    t = str(제목)
    제목에_포함 = [kw for kw in _SEO_장비_키워드_목록 if kw in t]
    if not 제목에_포함:
        return ''
    포함_set = set(제목에_포함)
    필수_단어 = [kw for kw in _SEO_장비_키워드_목록 if kw not in 포함_set]
    if not 필수_단어:
        return ''
    단어_목록 = ', '.join(f'"{w}"' for w in 필수_단어)
    return f"""[SEO 장비 동의어 — 반드시 준수]
· 제목에 장비 관련 표현({', '.join(제목에_포함)})이 있으므로, 아래 검색어를 본문 전체에 자연스럽게 각각 2회 이상 포함한다.
· 본문에 반드시 넣을 단어: {단어_목록}
· 키워드 나열처럼 보이지 않게 문장 속에 녹인다."""


def _제목_SEO_동의어_지침(제목):
    """제목 기준 SEO 동의어 지침 (렌탈/장비) 통합 반환"""
    parts = [
        _제목_SEO_렌탈_동의어_지침(제목),
        _제목_SEO_장비_동의어_지침(제목),
    ]
    return '\n\n'.join(p for p in parts if p)


# 전국 서비스 지역 - 기점(허브) 도시 기준 주변 시·군 묶음 (시트 GID=1646398695)
# 지역명은 검색·제목에 쓰이는 형태(군 접미사 생략)로 통일
_SEO_서비스_지역_기본_그룹_정의 = [
    ('익산', [
        '익산', '군산', '김제', '부안', '정읍', '전주',
        '완주', '봉동', '진안', '장수', '임실', '무주',
        '부여', '서천', '남원', '논산',
    ]),
    ('양주', [
        '양주', '의정부', '동두천', '포천', '파주', '부천',
        '구리', '하남', '남양주',
    ]),
    ('서울', [
        '서울', '고양', '일산', '강남', '종로', '구로',
        '서초', '광명',
    ]),
    ('시흥', [
        '시흥', '안산', '군포', '의왕', '인천', '안양',
        '김포',
    ]),
    ('수원', [
        '수원', '성남', '용인', '화성', '평택', '오산',
        '이천', '양평', '안성',
    ]),
    ('서산', [
        '서산', '당진', '태안', '보령', '홍성', '예산',
        '청양',
    ]),
    ('세종', [
        '세종', '대전', '천안', '아산', '공주', '금산',
        '계룡', '청주', '음성', '진천', '증평', '보은',
        '옥천', '영동', '괴산',
    ]),
    ('원주', [
        '원주', '춘천', '제천', '충주', '여주', '횡성',
        '홍천', '단양', '평창',
    ]),
    ('광주광역시', [
        '광주', '나주', '담양', '곡성', '장성', '화순',
        '영광', '고창', '순창',
    ]),
    ('경산', [
        '경산', '대구', '칠곡', '고령', '성주', '김천',
        '구미', '군위', '청도', '창녕', '밀양',
    ]),
    ('안동', [
        '안동', '영주', '예천', '상주', '의성', '청송',
    ]),
    ('목포', [
        '목포', '무안', '신안', '강진', '해남', '영암',
        '완도', '진도', '함평',
    ]),
    ('울산 경주', [
        '울산', '경주', '포항', '영천', '울주',
    ]),
    ('부산', [
        '부산', '김해', '양산', '기장', '해운대',
    ]),
    ('제주', [
        '제주',
    ]),
    ('통영', [
        '통영', '거제', '사천', '고성', '함양', '진주',
        '창원', '의령', '함안',
    ]),
    ('순천', [
        '순천', '여수', '광양', '보성', '하동', '구례',
    ]),
]
# 지역별 추가 검색 별칭 (자동 {지명}시·{지명}군 외 수동 보강)
_SEO_서비스_지역_특수_동의어 = {
    '서울': ['서울특별시'],
    '인천': ['인천광역시'],
    '부산': ['부산광역시'],
    '대구': ['대구광역시'],
    '광주': ['광주광역시'],
    '대전': ['대전광역시'],
    '울산': ['울산광역시'],
    '세종': ['세종특별자치시'],
    '제주': ['제주특별자치도'],
    '전주': ['전주특별자치시'],
    '고양': ['고양시 덕양', '고양시'],
    '일산': ['고양 일산', '고양시 일산', '일산동구', '일산서구'],
    '봉동': ['완주 봉동', '전주 완주', '완주군 봉동'],
    '고성': ['경남 고성', '경남고성'],
    '창원': ['마산', '진해', '창원시'],
}
# 지역묶음 표준명 중 군(gun) 단위 (시트·자동 동의어에서 {지명}군 우선)
_SEO_서비스_지역_군_목록 = frozenset([
    '부안', '고창', '완주', '진안', '장수', '임실', '무주', '순창', '부여', '서천',
    '연천', '가평', '강화', '옹진', '양평', '태안', '홍성', '예산', '금산', '청양',
    '음성', '진천', '증평', '보은', '옥천', '영동', '괴산', '단양',
    '홍천', '횡성', '영월', '평창', '정선', '철원', '화천', '양구', '인제', '양양',
    '담양', '곡성', '구례', '장성', '화순', '영광', '함평',
    '칠곡', '고령', '성주', '군위', '의성', '청송', '영양', '청도', '예천', '봉화', '울릉',
    '울진', '영덕', '무안', '신안',
    '의령', '함안', '창녕', '거제', '사천', '고성', '남해', '하동', '산청', '함양', '거창', '합천',
    '보성', '고흥', '장흥', '강진', '해남', '영암', '완도', '진도',
])
# 표준 지역별 SEO 핫지역(동·읍·상권·역세권) — 원고 안내 문단에만 사용, 제목 매칭에는 미사용
_SEO_서비스_지역_기본_핫지역 = {
    '익산': ['모현', '어양', '신동', '영등', '삼기', '익산역'],
    '군산': ['나운동', '수송', '경장', '조촌', '옥산', '군산항'],
    '김제': ['요촌', '검산', '신풍'],
    '부안': ['부안읍', '변산', '줄포'],
    '정읍': ['수성', '연지', '시기', '정읍역'],
    '고창': ['고창읍', '농소', '아산'],
    '전주': ['효자', '완산', '덕진', '서신', '송천', '전주역', '객사'],
    '완주': ['이서', '봉동', '구이', '삼례'],
    '봉동': ['완주군청', '삼례', '상관'],
    '진안': ['진안읍', '주천'],
    '장수': ['장수읍', '번암'],
    '임실': ['임실읍', '오수'],
    '무주': ['무주읍', '설악'],
    '순창': ['순창읍', '복흥'],
    '부여': ['부여읍', '규암'],
    '서천': ['서천읍', '장항', '마서'],
    '남원': ['남원역', '죽향', '금동', '도통'],
    '양주': ['덕정', '옥정', '회천', '양주역'],
    '의정부': ['의정부역', '가능', '민락', '호원'],
    '동두천': ['지행', '보산', '동두천역'],
    '포천': ['포천', '송우', '내촌'],
    '연천': ['연천읍', '전곡'],
    '가평': ['가평읍', '청평', '설악'],
    '서울': ['강남', '송파', '마포', '영등포', '구로', '강서', '노원', '성수', '잠실', '여의도'],
    '고양': ['일산', '킨텍스', '화정', '백석', '대화', '원당'],
    '일산': ['주엽', '정발', '백석', '대화', '킨텍스'],
    '파주': ['문산', '운정', '금촌', '탄현', '운정신도시'],
    '김포': ['장기', '구래', '풍무동', '사우', '양촌', '김포공항'],
    '부천': ['중동', '상동', '역곡', '송내', '부천역'],
    '광명': ['철산', '하안', '광명역', '소하'],
    '구리': ['교문', '수택', '구리역', '갈매'],
    '하남': ['하남역', '미사', '감일', '덕풍'],
    '남양주': ['다산', '별내', '화도', '금곡', '평내', '도농'],
    '시흥': ['정왕', '배곧', '신천', '대야', '은행', '은행동', '은계지구', '시흥역'],
    '안산': ['고잔', '중앙', '선부', '단원', '한대', '안산역'],
    '군포': ['산본', '금정', '당동', '군포역'],
    '의왕': ['내손', '청계', '포일', '의왕역'],
    '인천': ['송도', '부평', '주안', '연수', '구월', '검단', '인천역', '청라'],
    '강화': ['강화읍', '교동'],
    '옹진': ['북도', '연안'],
    '수원': ['영통', '광교', '팔달', '장안', '세류', '수원역', '인계'],
    '성남': ['분당', '판교', '서현', '야탑', '정자', '모란', '위례'],
    '용인': ['기흥', '수지', '동백', '죽전', '신갈', '에버랜드', '용인역'],
    '화성': ['동탄', '병점', '봉담', '향남', '오산', '화성역'],
    '평택': ['송탄', '비전', '고덕', '안중', '평택역', '포승'],
    '오산': ['오산역', '운암', '궐동'],
    '안양': ['범계', '평촌', '안양역', '관양', '비산'],
    '이천': ['이천역', '부발', '마장', '신둔'],
    '여주': ['여주역', '흥천', '점봉'],
    '양평': ['양평읍', '운길산'],
    '안성': ['안성역', '공도', '죽산'],
    '서산': ['서산역', '읍내', '대산', '석남'],
    '당진': ['당진역', '송악', '합덕'],
    '태안': ['태안읍', '안면도'],
    '보령': ['보령역', '대천', '웅천'],
    '홍성': ['홍성읍', '광천'],
    '예산': ['예산읍', '삽교'],
    '세종': ['나성', '어진', '보람', '조치원', '세종청사', '세종역'],
    '대전': ['둔산', '유성', '서구', '중구', '대전역', '테크노밸리'],
    '천안': ['두정', '불당', '신부', '청당', '천안역', '아산'],
    '아산': ['온양', '배방', '아산역', '탕정', '신창'],
    '공주': ['공주역', '신관', '웅진'],
    '금산': ['금산읍', '추부'],
    '청양': ['청양읍', '정산'],
    '논산': ['논산역', '강경', '연무'],
    '계룡': ['두마', '금암'],
    '청주': ['상당', '흥덕', '서원', '청주역', '오창', '가경'],
    '충주': ['충주역', '교현', '연수'],
    '제천': ['제천역', '장락', '신백'],
    '음성': ['음성읍', '맹동'],
    '진천': ['진천읍', '덕산'],
    '증평': ['증평읍', '도안'],
    '보은': ['보은읍', '삼승'],
    '옥천': ['옥천읍', '이원'],
    '영동': ['영동읍', '추풍령'],
    '괴산': ['괴산읍', '연풍'],
    '단양': ['단양읍', '매포'],
    '원주': ['원주역', '단구', '명륜', '무실', '반곡', '태장'],
    '춘천': ['춘천역', '후평', '석사', '퇴계', '소양'],
    '강릉': ['강릉역', '교동', '포남', '경포', '주문진'],
    '속초': ['속초역', '중앙', '조양', '설악'],
    '동해': ['동해역', '천곡', '북삼'],
    '삼척': ['삼척역', '남양', '정라'],
    '태백': ['태백역', '황지', '문곡'],
    '홍천': ['홍천읍', '화촌'],
    '횡성': ['횡성읍', '둔내'],
    '영월': ['영월읍', '주천'],
    '평창': ['평창읍', '진부', '대관령'],
    '정선': ['정선읍', '고한', '사북'],
    '철원': ['철원읍', '갈말', '동송'],
    '화천': ['화천읍', '간동'],
    '양구': ['양구읍', '남면'],
    '인제': ['인제읍', '기린'],
    '양양': ['양양읍', '설악', '남애'],
    '광주': ['상무', '봉선', '첨단', '수완', '광주역', '동구', '서구'],
    '나주': ['나주역', '빛가람', '금천', '영산'],
    '담양': ['담양읍', '봉산'],
    '곡성': ['곡성읍', '옥과'],
    '구례': ['구례읍', '섬진'],
    '장성': ['장성읍', '삼계'],
    '화순': ['화순읍', '능주'],
    '영광': ['영광읍', '백수'],
    '함평': ['함평읍', '학교'],
    '경산': ['경산역', '중방', '옥산', '사정', '하양'],
    '대구': ['동성로', '수성', '달서', '북구', '대구역', '성서', '혁신도시'],
    '영천': ['영천역', '완산'],
    '칠곡': ['왜관', '북삼', '석적'],
    '고령': ['고령읍', '대가야'],
    '성주': ['성주읍', '초전'],
    '김천': ['김천역', '평화', '아포'],
    '구미': ['구미역', '송정', '인동', '공단', '형곡'],
    '상주': ['상주역', '함창', '낙동'],
    '문경': ['문경역', '점촌', '가은'],
    '군위': ['군위읍', '부계'],
    '의성': ['의성읍', '안계'],
    '청송': ['청송읍', '주왕산'],
    '영양': ['영양읍', '일월'],
    '청도': ['청도읍', '화원'],
    '예천': ['예천역', '효자'],
    '봉화': ['봉화읍', '춘양'],
    '안동': ['안동역', '옥동', '태화'],
    '영주': ['영주역', '풍기', '가흥'],
    '울릉': ['울릉읍', '독도'],
    '목포': ['목포역', '하당', '용당', '산정', '상동'],
    '무안': ['무안읍', '삼향', '몽탄'],
    '신안': ['압해', '지도', '임자'],
    '울산': ['삼산', '남구', '중구', '울산역', '정관', '온산'],
    '울주': ['범서', '온양', '청량', '언양', '삼남'],
    '경주': ['경주역', '황성', '불국사', '첨성대', '외동'],
    '포항': ['포항역', '남구', '북구', '흥해', '구룡포', '연일'],
    '울진': ['울진읍', '후포', '죽변'],
    '영덕': ['영덕읍', '강구', '병곡'],
    '부산': ['서면', '해운대', '센텀', '부산역', '남포', '사상', '연제', '동래'],
    '기장': ['기장읍', '정관', '일광', '장안'],
    '김해': ['김해역', '장유', '내외', '삼안', '공항'],
    '창원': ['상남', '마산', '진해', '성주', '명곡', '창원역'],
    '양산': ['양산역', '물금', '웅상', '덕계'],
    '밀양': ['밀양역', '삼문', '내이'],
    '의령': ['의령읍', '가례'],
    '함안': ['함안읍', '가야'],
    '창녕': ['창녕읍', '남지'],
    '제주': ['제주역', '노형', '연동', '이도', '애월', '공항'],
    '서귀포': ['서귀포항', '중문', '대정', '표선', '성산'],
    '통영': ['통영항', '정량', '북신', '광도'],
    '거제': ['고현', '장승포', '아주', '옥포', '장목'],
    '사천': ['사천읍', '용현', '정동'],
    '고성': ['고성읍', '거류', '하이'],
    '남해': ['남해읍', '삼동'],
    '하동': ['하동읍', '화개'],
    '산청': ['산청읍', '신등'],
    '함양': ['함양읍', '마천'],
    '거창': ['거창읍', '가북'],
    '합천': ['합천읍', '가야'],
    '진주': ['진주역', '상대', '초전', '평거', '충무공'],
    '순천': ['순천역', '연향', '조례', '풍덕', '왕지'],
    '여수': ['여수역', '여서', '웅천', '돌산', '남면', '엑스포'],
    '광양': ['광양항', '중마', '금호', '광양역'],
    '보성': ['보성읍', '벌교'],
    '고흥': ['고흥읍', '도양'],
    '장흥': ['장흥읍', '회진'],
    '강진': ['강진읍', '마량'],
    '해남': ['해남읍', '황산'],
    '영암': ['영암읍', '삼호', '도화'],
    '완도': ['완도읍', '청산'],
    '진도': ['진도읍', '군내면'],
}
# 하위 호환: 전북 14개 flat 목록
_SEO_서비스_지역_기본목록 = [
    '익산', '전주', '군산', '김제', '논산', '서천', '봉동', '완주',
    '부여', '부안', '진안', '장수', '정읍', '임실',
]
_SEO_서비스_지역_그룹_캐시 = None


def _서비스지역_행정_접미사_있음(지역명):
    """지역명 끝에 시·군·광역시 등 행정 접미사가 붙었는지"""
    import re
    return bool(re.search(r'(특별자치시|특별자치도|특별시|광역시|시|군)$', str(지역명).strip()))


def _서비스지역_자동_동의어(지역명):
    """표준 지역명 -> 자동 생성 검색 별칭 (표준명 포함)"""
    name = str(지역명).strip()
    if not name:
        return []
    result = [name]
    if name in _SEO_서비스_지역_특수_동의어:
        result.extend(_SEO_서비스_지역_특수_동의어[name])
    if not _서비스지역_행정_접미사_있음(name):
        result.append(name + '시')
        result.append(name + '군')
        if name in _SEO_서비스_지역_군_목록:
            # 군 지역은 {지명}시 별칭 제거 (익산시 O, 홍천시 X)
            if name + '시' in result:
                result.remove(name + '시')
    seen = set()
    out = []
    for item in result:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _서비스지역_시트_동의어_별칭(지역명):
    """시트 지역동의어 셀용 별칭 (표준명 제외, 시·군 + 특수 별칭)"""
    name = str(지역명).strip()
    if not name:
        return []
    aliases = []
    if name in _SEO_서비스_지역_군_목록:
        aliases.append(name + '군')
    else:
        aliases.append(name + '시')
    for extra in _SEO_서비스_지역_특수_동의어.get(name, []):
        if extra != name and extra not in aliases:
            aliases.append(extra)
    return aliases


def _서비스지역_핫지역_기본_목록(지역명):
    """표준 지역명 -> 핫지역 기본 목록 (미등록 시 군=읍, 시=역)"""
    name = str(지역명).strip()
    curated = _SEO_서비스_지역_기본_핫지역.get(name)
    if curated:
        return list(curated)
    if name in _SEO_서비스_지역_군_목록:
        return [f'{name}읍']
    return [f'{name}역']


def _서비스지역_핫지역_맵_구성(지역목록, 시트_핫지역_텍스트=''):
    """표준 지역명 -> 핫지역 목록 (기본 + 시트 병합)"""
    sheet_map = _서비스지역_동의어_셀_파싱(시트_핫지역_텍스트)
    result = {}
    for region in 지역목록:
        hot = list(_서비스지역_핫지역_기본_목록(region))
        for extra in sheet_map.get(region, []):
            if extra not in hot:
                hot.append(extra)
        if hot:
            result[region] = hot
    return result


def _서비스지역_핫지역_셀_문자열(지역목록):
    """지역목록 -> 시트 '핫지역' 셀 텍스트"""
    items = []
    for region in 지역목록:
        hot = _서비스지역_핫지역_기본_목록(region)
        if hot:
            items.append(f"{region}:{'|'.join(hot)}")
    return ', '.join(items)


def _서비스지역_SEO_지역_표시(표준명, 핫목록):
    """원고 SEO 안내용: 표준명 + 괄호 핫지역 1~2개"""
    if not 핫목록:
        return str(표준명)
    n = min(2, len(핫목록))
    picked = random.sample(list(핫목록), n)
    return f"{표준명}({'·'.join(picked)})"


def _서비스지역_동의어_셀_문자열(지역목록):
    """지역목록 -> 시트 '지역동의어' 셀 텍스트 (표준:별칭1|별칭2, ...)"""
    items = []
    for region in 지역목록:
        aliases = _서비스지역_시트_동의어_별칭(region)
        if aliases:
            items.append(f"{region}:{'|'.join(aliases)}")
    return ', '.join(items)


def _서비스지역_동의어_셀_파싱(텍스트):
    """시트 지역동의어 셀 파싱: '표준:별칭1|별칭2, 표준2:별칭3' -> {표준: [별칭...]}"""
    import re
    s = str(텍스트).strip()
    if not s or s.lower() in ('nan', 'none'):
        return {}
    result = {}
    for part in re.split(r'[,，\n]+', s):
        part = part.strip()
        if not part:
            continue
        if ':' in part:
            std, aliases = part.split(':', 1)
        elif '=' in part:
            std, aliases = part.split('=', 1)
        else:
            continue
        std = std.strip()
        if not std:
            continue
        alias_list = [a.strip() for a in re.split(r'[|/、]+', aliases) if a.strip()]
        result.setdefault(std, []).extend(alias_list)
    return result


def _서비스지역_동의어_맵_구성(지역목록, 시트_동의어_텍스트=''):
    """표준 지역명 -> 검색용 동의어 목록 (자동 + 시트 병합)"""
    sheet_map = _서비스지역_동의어_셀_파싱(시트_동의어_텍스트)
    result = {}
    for region in 지역목록:
        aliases = list(_서비스지역_자동_동의어(region))
        for extra in sheet_map.get(region, []):
            if extra not in aliases:
                aliases.append(extra)
        result[region] = aliases
    return result


def _서비스지역_사용_여부(값):
    """시트 '사용' 컬럼 값이 활성인지 판단"""
    s = str(값).strip().upper()
    if not s or s in ('N', 'NO', '0', 'X', 'FALSE', '미사용', 'OFF'):
        return False
    return True


def _서비스지역_묶음_파싱(텍스트):
    """지역묶음 셀 텍스트를 지역명 리스트로 분리 (쉼표·슬ASH·줄바꿈)"""
    import re
    s = str(텍스트).strip()
    if not s or s.lower() in ('nan', 'none'):
        return []
    parts = re.split(r'[,，/|\n、]+', s)
    return [p.strip() for p in parts if p.strip()]


def _서비스지역_그룹_정의_시트_행(그룹_정의=None):
    """(그룹명, [지역...]) 목록 -> 시트 행 [[그룹명, 지역묶음, 지역동의어, Y, ''], ...]"""
    src = 그룹_정의 if 그룹_정의 is not None else _SEO_서비스_지역_기본_그룹_정의
    return [
        [
            name,
            ', '.join(regions),
            _서비스지역_동의어_셀_문자열(regions),
            _서비스지역_핫지역_셀_문자열(regions),
            'Y',
            '',
        ]
        for name, regions in src
    ]


def _서비스지역_시트_기본_데이터_행():
    """서비스지역 시트 초기 데이터 (허브 도시 기준 주변 시·군 묶음)"""
    return _서비스지역_그룹_정의_시트_행()


def _서비스지역_시트_초기화(ws):
    """서비스지역 시트(GID=1646398695) 헤더 및 기본 지역 묶음 기록"""
    rows = [_서비스지역_시트_헤더] + _서비스지역_시트_기본_데이터_행()
    gspread_operation_with_timeout(
        lambda: ws.update(values=rows, range_name='A1', value_input_option='USER_ENTERED'),
        timeout=30, operation_name="서비스지역 시트 초기화"
    )
    print(f"서비스지역 시트 초기화 완료 (허브 {len(_SEO_서비스_지역_기본_그룹_정의)}개 그룹)")


def _서비스지역_시트_구형_행_수집(all_values, headers):
    """구형(지역 1행 1개) 시트에서 활성 지역명 수집"""
    if '지역' not in headers:
        return []
    지역_idx = headers.index('지역')
    사용_idx = headers.index('사용') if '사용' in headers else -1
    목록 = []
    for row in all_values[1:]:
        if len(row) <= 지역_idx:
            continue
        지역 = str(row[지역_idx]).strip()
        if not 지역 or 지역.lower() in ('nan', 'none', '지역'):
            continue
        if 사용_idx >= 0 and len(row) > 사용_idx and not _서비스지역_사용_여부(row[사용_idx]):
            continue
        if ',' in 지역 or '，' in 지역:
            목록.extend(_서비스지역_묶음_파싱(지역))
        else:
            목록.append(지역)
    return 목록


def _서비스지역_시트_파싱(all_values):
    """서비스지역 시트에서 활성 지역 그룹 목록 추출
    Returns: [{'그룹명': str, '지역목록': [str, ...], '동의어_맵': {표준: [별칭...]}}, ...]
    """
    if not all_values or not all_values[0]:
        return []
    headers = [h.strip() for h in all_values[0]]

    # 신형: 그룹명 + 지역묶음 (+ 지역동의어)
    if '지역묶음' in headers:
        그룹_idx = headers.index('그룹명') if '그룹명' in headers else -1
        묶음_idx = headers.index('지역묶음')
        동의어_idx = headers.index('지역동의어') if '지역동의어' in headers else -1
        핫_idx = headers.index('핫지역') if '핫지역' in headers else -1
        사용_idx = headers.index('사용') if '사용' in headers else -1
        groups = []
        for row in all_values[1:]:
            if len(row) <= 묶음_idx:
                continue
            if 사용_idx >= 0 and len(row) > 사용_idx and not _서비스지역_사용_여부(row[사용_idx]):
                continue
            지역목록 = _서비스지역_묶음_파싱(row[묶음_idx])
            if not 지역목록:
                continue
            그룹명 = ''
            if 그룹_idx >= 0 and len(row) > 그룹_idx:
                그룹명 = str(row[그룹_idx]).strip()
            if not 그룹명:
                그룹명 = 지역목록[0]
            동의어_텍스트 = ''
            if 동의어_idx >= 0 and len(row) > 동의어_idx:
                동의어_텍스트 = str(row[동의어_idx]).strip()
            핫_텍스트 = ''
            if 핫_idx >= 0 and len(row) > 핫_idx:
                핫_텍스트 = str(row[핫_idx]).strip()
            groups.append({
                '그룹명': 그룹명,
                '지역목록': 지역목록,
                '동의어_맵': _서비스지역_동의어_맵_구성(지역목록, 동의어_텍스트),
                '핫지역_맵': _서비스지역_핫지역_맵_구성(지역목록, 핫_텍스트),
            })
        return groups

    # 구형: 지역 1행 1개 -> 전북 1그룹으로 변환
    if '지역' in headers:
        legacy = _서비스지역_시트_구형_행_수집(all_values, headers)
        if legacy:
            return [{
                '그룹명': '전북',
                '지역목록': legacy,
                '동의어_맵': _서비스지역_동의어_맵_구성(legacy),
                '핫지역_맵': _서비스지역_핫지역_맵_구성(legacy),
            }]
    return []


def _SEO_서비스_지역_기본_그룹():
    return [
        {
            '그룹명': name,
            '지역목록': list(regions),
            '동의어_맵': _서비스지역_동의어_맵_구성(list(regions)),
            '핫지역_맵': _서비스지역_핫지역_맵_구성(list(regions)),
        }
        for name, regions in _SEO_서비스_지역_기본_그룹_정의
    ]


def _SEO_서비스_지역_그룹_가져오기(강제_갱신=False):
    """서비스지역 시트(GID=1646398695)에서 지역 그룹 목록 로드 (실패 시 기본 전북 그룹)"""
    global _SEO_서비스_지역_그룹_캐시
    if _SEO_서비스_지역_그룹_캐시 and not 강제_갱신:
        return list(_SEO_서비스_지역_그룹_캐시)
    import socket as _socket
    원래 = _socket.getdefaulttimeout()
    try:
        _socket.setdefaulttimeout(30)
        spreadsheet = _지명키워드_이력_gc_열기()
        ws = gspread_operation_with_timeout(
            lambda: spreadsheet.get_worksheet_by_id(서비스지역_시트_GID),
            timeout=15, operation_name="서비스지역 시트 열기"
        )
        all_values = gspread_operation_with_timeout(
            lambda: ws.get_all_values(),
            timeout=20, operation_name="서비스지역 시트 읽기"
        )
        headers = [h.strip() for h in all_values[0]] if all_values and all_values[0] else []
        needs_init = (
            not all_values
            or '지역묶음' not in headers
            or len(all_values) < 2
        )
        if needs_init and '지역' in headers:
            # 구형 -> 신형 1행 묶음으로 자동 마이그레이션
            legacy = _서비스지역_시트_구형_행_수집(all_values, headers)
            if legacy:
                rows = [_서비스지역_시트_헤더, ['전북', ', '.join(legacy), '', '', 'Y', '구형 시트 자동 변환']]
                gspread_operation_with_timeout(
                    lambda: ws.update(values=rows, range_name='A1', value_input_option='USER_ENTERED'),
                    timeout=30, operation_name="서비스지역 시트 마이그레이션"
                )
                print(f"서비스지역 시트 구형->신형 변환 ({len(legacy)}개 지역 1행 묶음)")
                all_values = gspread_operation_with_timeout(
                    lambda: ws.get_all_values(), timeout=20, operation_name="서비스지역 시트 재읽기"
                )
                needs_init = False
        if needs_init:
            _서비스지역_시트_초기화(ws)
            all_values = gspread_operation_with_timeout(
                lambda: ws.get_all_values(), timeout=20, operation_name="서비스지역 시트 재읽기"
            )
        groups = _서비스지역_시트_파싱(all_values)
        if groups:
            _SEO_서비스_지역_그룹_캐시 = groups
            요약 = ', '.join(
                f"{g['그룹명']}({len(g['지역목록'])})" for g in groups
            )
            print(f"서비스지역 시트 로드: {요약}")
            return list(groups)
        print("서비스지역 시트 데이터 없음 - 기본 전북 그룹 사용")
    except Exception as e:
        print(f"서비스지역 시트 읽기 오류 (기본 그룹 사용): {e}")
    finally:
        _socket.setdefaulttimeout(원래)
    _SEO_서비스_지역_그룹_캐시 = _SEO_서비스_지역_기본_그룹()
    return list(_SEO_서비스_지역_그룹_캐시)


def _제목_지역_매칭(지역목록, 텍스트, 동의어_맵=None, 상세=False):
    """제목 텍스트에 포함된 지역명 매칭 (동의어·긴 이름 우선, 남양주/양주 중복 방지)

    상세=True 이면 [{'표준': str, '매칭어': str}, ...] 반환.
    """
    if not 텍스트:
        return []
    t = str(텍스트)
    if 동의어_맵 is None:
        동의어_맵 = _서비스지역_동의어_맵_구성(지역목록)
    pairs = []
    for canon, aliases in 동의어_맵.items():
        for alias in aliases:
            pairs.append((alias, canon))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    matched_canon = []
    matched_detail = []
    for alias, canon in pairs:
        if alias not in t:
            continue
        if any(canon in m for m in matched_canon):
            continue
        matched_canon.append(canon)
        matched_detail.append({'표준': canon, '매칭어': alias})
    return matched_detail if 상세 else matched_canon


def _제목_지역_매칭_표시(매칭_상세):
    """매칭 상세 -> 제목 지침용 표시 문자열 (별칭이면 별칭 그대로)"""
    parts = []
    for item in 매칭_상세:
        if item['매칭어'] != item['표준']:
            parts.append(item['매칭어'])
        else:
            parts.append(item['표준'])
    return parts


def _제목_서비스_지역_그룹_찾기(제목):
    """제목에 포함된 지역명으로 매칭되는 서비스 지역 그룹 반환 (긴 지명 우선)"""
    if not 제목:
        return None
    t = str(제목)
    best = None
    best_len = 0
    for group in _SEO_서비스_지역_그룹_가져오기():
        동의어_맵 = group.get('동의어_맵') or _서비스지역_동의어_맵_구성(group['지역목록'])
        매칭 = _제목_지역_매칭(group['지역목록'], t, 동의어_맵)
        if not 매칭:
            continue
        max_len = max(len(m) for m in 매칭)
        if max_len > best_len:
            best_len = max_len
            best = {**group, '제목_매칭': 매칭}
    return best


def _제목_서비스_지역_안내_지침(제목, 업체명=''):
    """제목에 서비스 지역 그룹이 매칭되면 해당 그룹 지역만 본문 안내 문구에 포함"""
    if not 제목:
        return ''
    matched = _제목_서비스_지역_그룹_찾기(제목)
    if not matched:
        return ''
    서비스_지역_목록 = matched['지역목록']
    동의어_맵 = matched.get('동의어_맵') or _서비스지역_동의어_맵_구성(서비스_지역_목록)
    핫지역_맵 = matched.get('핫지역_맵') or _서비스지역_핫지역_맵_구성(서비스_지역_목록)
    매칭_상세 = _제목_지역_매칭(서비스_지역_목록, 제목, 동의어_맵, 상세=True)
    제목에_포함 = _제목_지역_매칭_표시(매칭_상세) or matched.get('제목_매칭') or []
    그룹명 = matched.get('그룹명') or ''
    seo_지역_표시 = [
        _서비스지역_SEO_지역_표시(r, 핫지역_맵.get(r, []))
        for r in 서비스_지역_목록
    ]
    지역_목록_섞음 = list(seo_지역_표시)
    장비_목록_섞음 = list(_SEO_장비_키워드_목록)
    random.shuffle(지역_목록_섞음)
    random.shuffle(장비_목록_섞음)
    지역_나열 = ', '.join(지역_목록_섞음)
    장비_나열 = ', '.join(장비_목록_섞음)
    지역_필수 = ', '.join(seo_지역_표시)
    장비_필수 = ', '.join(_SEO_장비_키워드_목록)
    지역_개수 = len(서비스_지역_목록)
    업체 = str(업체명).strip() if 업체명 else '당사'
    그룹_표시 = f"({그룹명} 그룹) " if 그룹명 else ''
    return f"""[서비스 지역 안내 — 반드시 준수]
· 제목에 '{', '.join(제목에_포함)}' 지역이 포함되어 {그룹_표시}아래 지역 그룹 전체를 안내한다. 본문 마무리 또는 ## 업체 소개 섹션에 1문단 포함.
· 각 표준 지역명 뒤 괄호에 핫지역(동·읍·상권) 1~2개 병기: 예) 익산(모현·어양), 전주(효자·완산)
· 안내 문구 순서: (1) {지역_개수}개 지역(핫지역 포함) → (2) 장비 동의어 전체 → (3) 렌탈·설치·A/S·상담
· 지역명·장비명 나열 순서는 매번 다르게 쓴다. 고정 순서·알파벳 순·목록 원본 순서 그대로 나열 금지.
· 예시 형태(이번 글 참고 순서): {업체}은(는) {지역_나열} 지역 {장비_나열} 렌탈(임대) 설치·A/S·상담을 제공합니다.
· 문장은 자연스럽게 다듬되 아래 항목은 빠짐없이 모두 언급: 지역({지역_필수}), 장비({장비_필수})
· 지역명·장비명은 쉼표로 구분하고, 광고성 클로징 문구는 쓰지 않는다."""


def _섹션_묶음_나누기(섹션_개수):
    """연속 ## 섹션을 1~2개 단위로 묶음."""
    묶음 = []
    i = 0
    while i < 섹션_개수:
        크기 = random.randint(1, min(2, 섹션_개수 - i))
        묶음.append(list(range(i, i + 크기)))
        i += 크기
    return 묶음


def _묶음_표기(섹션_인덱스들):
    if len(섹션_인덱스들) == 1:
        return f'섹션 {섹션_인덱스들[0] + 1}'
    return f'섹션 {섹션_인덱스들[0] + 1}~{섹션_인덱스들[-1] + 1}'


def _이미지_최대_개수_맞추기(섹션별_이미지_개수, 섹션_개수):
    """섹션당 1~2장 상한(섹션수+섹션수/2) 초과 시 2장 섹션만 줄임."""
    이미지_최대_개수 = 섹션_개수 + 섹션_개수 // 2
    while sum(섹션별_이미지_개수) > 이미지_최대_개수:
        줄일_후보 = [i for i, v in enumerate(섹션별_이미지_개수) if v == 2]
        if not 줄일_후보:
            break
        섹션별_이미지_개수[random.choice(줄일_후보)] = 1
    return 섹션별_이미지_개수


def _이미지_배치_계획(섹션_개수):
    """섹션별 [이미지] 개수 — 전체 섹션 또는 1~2섹션 묶음 단위 배치."""
    if 섹션_개수 <= 0:
        return [], 0, '섹션 없음', '', 0, 0

    묶음_목록 = _섹션_묶음_나누기(섹션_개수)
    묶음_구분 = ' / '.join(_묶음_표기(g) for g in 묶음_목록)

    if random.choice([True, False]):
        배치_방식 = f'전체 섹션 각 1~2장 (1~2섹션 묶음: {묶음_구분})'
        섹션별_이미지_개수 = [random.randint(1, 2) for _ in range(섹션_개수)]
        섹션별_이미지_개수 = _이미지_최대_개수_맞추기(섹션별_이미지_개수, 섹션_개수)
    else:
        섹션별_이미지_개수 = [0] * 섹션_개수
        활성_묶음 = []
        for g in 묶음_목록:
            if random.random() < 0.55:
                활성_묶음.append(g)
                for i in g:
                    섹션별_이미지_개수[i] = random.randint(1, 2)
        if sum(섹션별_이미지_개수) == 0:
            g = random.choice(묶음_목록)
            활성_묶음 = [g]
            for i in g:
                섹션별_이미지_개수[i] = random.randint(1, 2)
        섹션별_이미지_개수 = _이미지_최대_개수_맞추기(섹션별_이미지_개수, 섹션_개수)
        활성_표기 = ', '.join(_묶음_표기(g) for g in 활성_묶음)
        배치_방식 = (
            f'1~2섹션 묶음 중 {활성_표기}에만 이미지 '
            f'(묶음 구분: {묶음_구분})'
        )

    이미지_개수 = sum(섹션별_이미지_개수)
    이미지_2개_섹션_수 = sum(1 for n in 섹션별_이미지_개수 if n == 2)
    이미지_넣는_섹션_수 = sum(1 for n in 섹션별_이미지_개수 if n > 0)
    상세_줄 = [f'  · 1~2섹션 묶음 구분: {묶음_구분}']
    for i, n in enumerate(섹션별_이미지_개수):
        if n == 0:
            상세_줄.append(f'  · ## 섹션 {i + 1}/{섹션_개수}: [이미지] 0개 — 넣지 않음')
        else:
            상세_줄.append(f'  · ## 섹션 {i + 1}/{섹션_개수}: [이미지] 정확히 {n}개')
    return (
        섹션별_이미지_개수, 이미지_개수, 배치_방식,
        '\n'.join(상세_줄), 이미지_2개_섹션_수, 이미지_넣는_섹션_수,
    )


_원고_메타_마커 = (
    'Self-correction', 'Revision Plan', 'Keyword Count', 'Revision plan',
    '공백 제외 문자 수 확인', 'will perform this with a tool',
    'Need one more', 'Revised sections', "Let's adjust", "Let's re-integrate",
)


def _원고_메타노트_제거(content):
    """AI 자기검토·키워드 점검·수정 계획 등 메타 노트를 원고에서 제거."""
    import re
    if not content:
        return content

    # --- 구분선 뒤 메타 블록(본문 끝에 붙는 경우) 잘라내기
    for sep in ('\n---\n', '\r\n---\r\n'):
        pos = 0
        while True:
            idx = content.find(sep, pos)
            if idx == -1:
                break
            tail = content[idx:idx + 1200]
            if any(m in tail for m in _원고_메타_마커):
                content = content[:idx].rstrip()
                break
            pos = idx + len(sep)

    meta_line_res = [
        re.compile(p, re.I) for p in (
            r'Self-correction',
            r'Revision Plan',
            r'Keyword Count',
            r'공백 제외 문자 수 확인',
            r'will perform this with a tool',
            r'Need one more',
            r'^Revised sections?',
            r"Let\'s (adjust|re-integrate|revise)",
            r'^\s*[-·]\s*["\'].+["\']\s*:\s*used in',
            r'\(\d+\s*times?\)',
        )
    ]

    cleaned = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == '---':
            continue
        if any(m.lower() in line.lower() for m in _원고_메타_마커):
            continue
        if any(r.search(line) for r in meta_line_res):
            continue
        cleaned.append(line)

    result = re.sub(r'\n{3,}', '\n\n', '\n'.join(cleaned)).strip()
    return result


def 블로그_글_생성(지명키워드, 생성된제목, 유형="정보형", 추천모델="", 대상업종="",
                   faq_세부유형="", faq_세부주제=""):
    """복합기렌탈 최종원고를 생성하는 함수 (유형_목록별 프롬프트).
    유형은 제목과 동일하게 맞춰 일괄되게 생성한다."""
    try:
        # 유형·추천모델·대상업종 보정
        if 유형 not in 유형_목록:
            유형 = "정보형"
        if not 추천모델 or str(추천모델).strip().lower() in ('', 'nan'):
            추천모델 = random.choice(추천모델_목록)
        if not 대상업종 or str(대상업종).strip().lower() in ('', 'nan'):
            base = random.choice(대상업종_목록)
            if 유형 == "설치후기형":
                대상업종 = _설치후기_대상업종_표기(base)
            else:
                대상업종 = base
        else:
            대상업종 = str(대상업종).strip()
        if 유형 == FAQ_글유형:
            faq_세부유형 = str(faq_세부유형).strip() if faq_세부유형 else ''
            faq_세부주제 = str(faq_세부주제).strip() if faq_세부주제 else ''
            if faq_세부유형 not in FAQ_세부유형_목록 or not faq_세부주제:
                faq_세부유형, faq_세부주제 = _FAQ_세부유형_배정(추천모델, _현재_작업_사용아이디())
            print(f"[{유형}] 세부유형: {faq_세부유형} / 세부주제: {faq_세부주제}")

        # 하나노란 값으로 업체명 결정
        try:
            _kw_df = 지명키워드_df_가져오기()
            _하나노란_값 = ''
            if _kw_df is not None and not _kw_df.empty and '하나노란' in _kw_df.columns:
                _하나노란_값 = str(_kw_df.iloc[0]['하나노란']).strip()
                if _하나노란_값.lower() in ('', 'nan', 'none'):
                    _하나노란_값 = ''
        except Exception:
            _하나노란_값 = ''

        if _하나노란_값 == '하나렌탈':
            업체명 = '고객과 하나되는 하나렌탈'
        elif _하나노란_값 == '노란우산':
            업체명 = '소기업 소상공인을 위한 노란우산렌탈'
        elif _하나노란_값:
            업체명 = _하나노란_값
        else:
            업체명 = '고객과 하나되는 하나렌탈'

        print(f"[{유형}] 최종원고 생성 중... (추천모델: {추천모델}, 대상업종: {대상업종}, 업체명: {업체명})")

        # 분량·섹션 랜덤화 (이미지 배치용 변수는 그대로 유지)
        목표글자수 = random.choice([1200, 1500, 1800, 2000])
        섹션_개수 = random.randint(5, 7)
        섹션별_글자수 = []
        for i in range(섹션_개수):
            if i == 0:
                섹션별_글자수.append(random.randint(200, 300))
            elif i == 섹션_개수 - 1:
                섹션별_글자수.append(random.randint(300, 400))
            else:
                섹션별_글자수.append(random.randint(300, 400))
        (
            섹션별_이미지_개수, 이미지_개수, 이미지_배치_방식, 이미지_배치_상세,
            이미지_2개_섹션_수, 이미지_넣는_섹션_수,
        ) = _이미지_배치_계획(섹션_개수)
        이미지_섹션_인덱스 = [i for i, n in enumerate(섹션별_이미지_개수) if n > 0]
        문체_스타일 = f"{유형} 톤"
        문단_구조_전략 = "혼합_구조"
        특별_요소_추가 = "없음"
        seo_동의어_지침 = '\n\n'.join(p for p in [
            _제목_SEO_동의어_지침(생성된제목),
            _제목_서비스_지역_안내_지침(생성된제목, 업체명),
        ] if p)
        if seo_동의어_지침:
            print(f"SEO/서비스지역 지침 적용 (제목: {생성된제목})")

        # ---- 유형 공통 지침 ----
        공통_지명 = f"""[지명키워드 배치 — 네이버 SEO 기준]
· 도입부 첫 3문장 안에 지명키워드('{지명키워드}')를 반드시 1번 포함
· 소제목(##)은 전체 중 1~2개에만 지명키워드 또는 연관 키워드 포함
· 마무리 문단에서 자연스럽게 1번 더 언급
· 본문 전체 3~5회면 충분. 지명키워드만 반복하지 말고 연관어(복합기렌탈, 복사기렌탈, 프린터렌탈, 사무기기렌탈, A3복합기, 컬러복합기, 레이저복합기, 월 렌탈료, 무상 AS, 토너 교체, 약정 기간, 스캔·팩스 기능 등) 중 8~12개를 문장 속에 자연스럽게 녹인다. 해시태그·"관련 검색어:" 나열 금지."""

        공통_어조 = """[어조 및 문체 원칙 — 가장 중요. AI가 쓴 티가 나면 실패한 원고입니다]
잘 쓰려고 애쓴 티가 나면 안 됩니다. 이 분야를 오래 한 사람이 무심하게 알려주듯 씁니다.

절대 쓰지 말 것 (하나라도 나오면 실패):
· 판단·분석 상투어: "종합적으로 분석하여", "~라고 판단했습니다", "니즈를 파악하여", "최적의 솔루션", "면밀히 살펴본 결과", "적합한 모델을 추천해 드렸습니다"
· 과장된 감정/반응 묘사: "연신 감탄사를 쏟아내셨습니다", "큰 보람을 느꼈습니다", "만족감을 표하셨습니다"
· 마케팅 클리셰: "안성맞춤", "든든한 파트너", "스마트 오피스 구축", "고객과 하나 되는 마음으로", "가장 합리적인 사무기기 솔루션", "고객의 입장에서", "전문 업체로서"
· 광고성 클로징: "주저 말고 문을 두드려 주세요", "지금 바로 상담받으세요", "고민하지 마세요", "언제든 편하게 연락 주세요"
· 공허한 미사여구: "젊은 에너지가 넘치는", "활기찬 분위기", "생생한 색감", "정돈된 느낌"
· "업무 효율"은 글 전체에서 1번만 사용
· "최고", "저렴", "강력 추천" 등 광고성 단어 금지

반드시 이렇게:
· 추상적으로 좋다고 하지 말고 구체적 숫자·상황으로 대신한다. ("비용이 저렴합니다" X → "한 달에 3~4만 원대부터 시작하는 경우가 많아요" O)
· 종결어미는 "~습니다"와 "~요"를 기본으로 자연스럽게 섞고, "~죠"는 글 전체에서 2~3번 이내. 같은 어미를 3문장 연속 쓰지 않는다.
· 장점만 나열하지 말고 단점·주의점·애매한 부분도 솔직하게 짚는다.
· 짧은 문장(10자 미만)과 긴 문장을 의도적으로 교차한다. 소제목마다 같은 리듬으로 시작/마무리하지 않는다."""

        공통_모바일 = """[모바일 가독성 — 반드시 준수]
· 한 소문단은 100~130자, 의미 단위로 줄바꿈(한 줄 40~60자)
· 소문단 사이에만 빈 줄 1개, 소문단 안 문장들 사이에는 빈 줄을 넣지 않는다"""

        공통_출력 = f"""[출력 규칙 — 반드시 준수]
· 첫 줄은 반드시 아래 제목을 그대로 # 제목으로 쓴다: {생성된제목}
· 본문 소제목은 ## 로 시작. 소제목 문구는 아래 주제를 그대로 베끼지 말고 이번 글 내용에 맞게 매번 다르게 짓는다(단 "복합기 렌탈 FAQ 자주 묻는 질문" 소제목은 그대로 사용).

[이미지 배치 — 이번 글 필수]
· 이번 글 배치: {이미지_배치_방식}
· 본문 ## 섹션 {섹션_개수}개, 총 [이미지] {이미지_개수}개(이미지 있는 섹션 {이미지_넣는_섹션_수}개, 2장 섹션 {이미지_2개_섹션_수}개)
· 섹션별 [이미지] 개수(아래를 정확히 지킬 것):
{이미지_배치_상세}
· [이미지] 0개로 지정된 섹션에는 [이미지] 줄을 절대 넣지 않는다.
· [이미지] 형식: "[이미지] 영어 문장"(20단어 이내). 해당 섹션 내용과 직접 연관된 장면.
· 2개인 섹션은 서로 다른 장면의 [이미지] 줄 2줄(각 줄 앞뒤 빈 줄). "Image generation prompt:" 같은 설명 금지.

· 자기소개 문구("저는 ***입니다", "***로서" 등) 절대 금지
· HTML 태그(<br>, <p> 등)·마크다운 코드블록(```, ''') 절대 금지
· 별표(*) 절대 금지: 굵게(**), 기울임(*), 별표 불릿(* ) 모두 금지. 목록이 필요하면 각 줄 앞에 가운뎃점(·)만 쓴다.
· 순수 텍스트와 #, ## 마크다운 제목, [이미지] 줄만 사용
· FAQ의 질문·답변은 "Q: 질문" / "A: 답변" 평문으로만 쓴다
· 추천 모델은 반드시 {추천모델} 하나만 다룬다(다른 모델명·상호명 등장 금지)
· 공백 제외 {목표글자수}자 이상 작성
· 출력은 # 제목부터 본문만. 작성 과정·자기검토·키워드 횟수 점검·Revision Plan·Self-correction·공백 제외 글자수 확인·--- 메모·영어 편집 노트 절대 금지"""

        공통_종결 = """[문장 종결어미 다양화]
· 같은 어미(~합니다, ~하세요 등)를 3번 이상 연속 사용하지 않는다
· 평서형(~해요, ~이에요, ~랍니다, ~네요), 의문형(~까요?, ~나요?), 감탄형(~군요!)을 자연스럽게 섞는다"""

        if 유형 == "설치후기형":
            prompt = f"""당신은 {업체명} 설치 담당자입니다. 아래는 고객사에 복합기를 직접 설치하고 쓰는 1인칭 현장 후기 블로그 원고입니다. "이번에 다녀왔습니다" 같은 담백한 후기 톤으로 씁니다.

[글쓴이 표기 — 반드시]
· 담당자 이름·직함 자기소개 금지("저는 ○○○입니다" 금지). 첫 문장부터 곧바로 이번 설치 이야기로 들어간다.

[상담·설치 방식 — 반드시]
· {업체명}은 방문 상담을 하지 않는다. 불편사항·사용량 확인·모델 결정은 모두 사전에 전화 상담으로 끝낸다.
· 담당자가 고객사에 가는 것은 '설치하는 날' 딱 한 번뿐이고, 그날 처음 사무실을 본다.
· "현장을 둘러보고 파악했다", "사무실을 한 바퀴 돌며 살폈다", "현장에서 상담하며 모델을 정했다" 같은 서술은 사실과 달라 금지. 불편·모델 선정은 "전화로 상담하면서 들었다/정했다"로 서술한다.

[입력]
· 메인 키워드: 복합기렌탈
· 지역 키워드: {지명키워드}
· 업체명: {업체명}
· 고객사 업종: {대상업종} (○ 기호가 붙어 있으면 제목·본문 모두 띄어쓰기 없이 동일하게 유지)
· 설치 모델: {추천모델}
· 공백 제외 {목표글자수}자 이상

{공통_지명}
{seo_동의어_지침}

{공통_어조}
· 감정은 직접 말하지 말고 구체적 상황으로 대신한다. ("만족하셨습니다" X → "첫 출력물 보시더니 이제 외주 안 맡겨도 되겠다 하시더라고요" O). 글쓴이 감정 직접 서술("제가 뿌듯했죠")도 금지.
· 현장에서만 아는 사소한 디테일(설치 소요 시간, 네트워크 잡다 막힌 일, 케이블 정리, 자리 옮긴 일 등)을 넣는다. 모든 게 완벽했다는 식은 금물.

[구성 — ## 소제목 {섹션_개수}개, 도입부는 ## 없음]
· 첫 줄 # 제목 → 도입(전화 상담을 거쳐 설치하러 가게 된 배경 + 설치 당일 도착 첫인상, ## 없음) → ## 소제목 {섹션_개수}개
· 흐름: (전화 상담으로) 불편 확인·모델 결정 → 설치 방문 → 설치 작업 → 쓰고 난 반응 → 비용·계약. '현장 방문 상담/환경 살핌' 단계는 없다.
· 소제목 주제 후보(분량에 맞게 고르고, FAQ와 마무리는 반드시 포함하고 맨 끝):
  전화 상담에서 들은 불편사항 / {추천모델}을 고른 이유(이 사무실 상황에 왜 맞았는지 근거 1~2개, 스펙 나열 금지) / {추천모델}의 주요 기능과 스펙 / 설치 당일 현장 작업 / 설치 후 고객 반응과 소감 / 비용·계약 조건 / 이 모델이 잘 맞는 업종·환경 / 복합기 렌탈 FAQ 자주 묻는 질문 / 마무리
· '주요 기능과 스펙' 섹션은 각 줄을 "사양명 : 실제 수치 / {대상업종} 활용 이점(명사형 25자 이내)" 형식으로 4~6개 정리하고, 뒤에 담당자 시점 코멘트 한 줄로 마무리한다. '고른 이유' 섹션과 같은 기능을 반복하지 않는다.
· 비용·계약은 두루뭉술하게 넘기지 말고 실제 감이 오는 숫자로(예: "월 3~4만 원대부터", "약정은 보통 36개월", "매수당 얼마"). 마무리는 1~2문장으로 담백하게. 전화번호·"상담 주세요" 류는 넣지 않는다.
· FAQ는 실제 고객이 상담 중 자주 묻는 질문 기준 "Q:/A:" 3~5개.

{공통_종결}

{공통_모바일}

{공통_출력}
"""
        elif 유형 == FAQ_글유형:
            faq_질문_참고 = "\n".join([f"· {q}" for q in FAQ_질문_목록])
            faq_비교_참고 = "\n".join([f"· {q}" for q in FAQ_비교_주제_목록])
            faq_모델_참고 = "\n".join([f"· {추천모델} {t}" for t in FAQ_모델소개_주제_목록])
            if faq_세부유형 == "FAQ형":
                prompt = f"""당신은 복합기렌탈 FAQ 전문 작성자입니다. 고객이 가장 많이 묻는 질문에 바로 답하는 글을 씁니다. 네이버 AI 브리핑에 활용되기 쉬운 Q/A 구조를 우선합니다.

[이번 글 핵심]
· 세부유형: FAQ형
· 핵심 질문: {faq_세부주제}
· 지역: {지명키워드} / 모델: {추천모델} / 업종: {대상업종}

[입력]
· 메인 키워드: 복합기렌탈
· 지역 키워드: {지명키워드}
· 업체명: {업체명}
· 추천 모델: {추천모델}
· 대상 업종: {대상업종}
· 공백 제외 {목표글자수}자 이상

{공통_지명}
{seo_동의어_지침}

{공통_어조}

[원칙]
· 핵심 질문 '{faq_세부주제}'에 도입부 첫 3문장 안에서 결론 또는 방향을 제시한다.
· FAQ가 본문 중심이다. 아래 참고 질문 중 4~6개를 골라 "Q:/A:" 형식으로 답한다(핵심 질문은 반드시 포함).
· 참고 질문:
{faq_질문_참고}
· 각 A: 답변은 2~4문장, 구체적 숫자·조건 포함. {추천모델}은 FAQ 답변 속에서 자연스럽게 1~2회 언급.
· 업체 소개는 마지막 1~2문장.

[구성 — ## 소제목 {섹션_개수}개, 도입부는 ## 없음]
· 첫 줄 # 제목 → 도입(핵심 질문 요약·이 글에서 얻는 답) → ## 소제목 {섹션_개수}개
· 소제목 후보: {지명키워드}에서 자주 묻는 질문 / {faq_세부주제} 답변 / 렌탈·구매·비용 FAQ / 계약·토너·A/S FAQ / {추천모델} 관련 FAQ / {대상업종} 맞춤 FAQ / 복합기 렌탈 FAQ 자주 묻는 질문 / 핵심 요약 / 업체 소개
· '복합기 렌탈 FAQ 자주 묻는 질문' 섹션: "Q:/A:" 5~7개(다른 섹션과 겹치지 않게).

{공통_종결}
{공통_모바일}
{공통_출력}
"""
            elif faq_세부유형 == "비교형":
                prompt = f"""당신은 복합기렌탈 비교 콘텐츠 전문 작성자입니다. 검색량 높은 비교 글로 체류시간을 확보하는 구조를 씁니다.

[이번 글 핵심]
· 세부유형: 비교형
· 비교 주제: {faq_세부주제}
· 지역: {지명키워드} / 모델: {추천모델} / 업종: {대상업종}

[입력]
· 메인 키워드: 복합기렌탈
· 지역 키워드: {지명키워드}
· 업체명: {업체명}
· 추천 모델: {추천모델}
· 대상 업종: {대상업종}
· 공백 제외 {목표글자수}자 이상

{공통_지명}
{seo_동의어_지침}

{공통_어조}

[원칙]
· '{faq_세부주제}' 비교가 본문 중심이다. 장단점·비용·적합 상황을 함께 쓴다.
· 참고 비교 주제(이번 주제와 겹치지 않게 1~2개만 보조로 활용 가능):
{faq_비교_참고}
· 비교는 · 불릿 대비 형식(표 금지). "A 장점 / A 단점 / B 장점 / B 단점" 또는 "항목별 A vs B" 구조.
· {추천모델}은 비교 결론·{대상업종} 추천 근거에 반드시 연결. 다른 모델명은 비교 주제에 필요할 때만.
· 업체 소개는 마지막 1~2문장.

[구성 — ## 소제목 {섹션_개수}개, 도입부는 ## 없음]
· 첫 줄 # 제목 → 도입(비교 결론 한 줄 + 왜 비교가 필요한지) → ## 소제목 {섹션_개수}개
· 소제목 후보: {faq_세부주제} 한눈에 보기 / 항목별 비교(비용·유지·약정·설치) / {대상업종} 기준 어떤 쪽이 맞나 / {추천모델} 관점 정리 / 선택 체크리스트 / 주의사항 / 복합기 렌탈 FAQ 자주 묻는 질문 / 핵심 요약 / 업체 소개
· FAQ 섹션: "Q:/A:" 3~5개(비교와 연관된 질문).

{공통_종결}
{공통_모바일}
{공통_출력}
"""
            else:
                prompt = f"""당신은 복합기렌탈 모델 소개 전문 작성자입니다. 실제 문의가 많은 모델 하나({추천모델})를 깊게 소개합니다.

[이번 글 핵심]
· 세부유형: 모델 소개형
· 소개 각도: {faq_세부주제}
· 지역: {지명키워드} / 업종: {대상업종}

[입력]
· 메인 키워드: 복합기렌탈
· 지역 키워드: {지명키워드}
· 업체명: {업체명}
· 추천 모델: {추천모델}
· 대상 업종: {대상업종}
· 공백 제외 {목표글자수}자 이상

{공통_지명}
{seo_동의어_지침}

{공통_어조}

[원칙]
· '{faq_세부주제}' 각도가 본문 중심이다. 같은 모델({추천모델})만 다룬다.
· 참고 소개 각도(이번 각도와 겹치지 않게 1~2개만 보조):
{faq_모델_참고}
· 스펙은 "사양명 : 수치 / {대상업종}에서의 의미" 형식 4~6개.
· 설치 사례·후기 각도일 때는 과장된 감정 묘사 없이 구체적 상황으로.
· 업체 소개는 마지막 1~2문장.

[구성 — ## 소제목 {섹션_개수}개, 도입부는 ## 없음]
· 첫 줄 # 제목 → 도입(이 모델·이 각도에서 얻는 정보 요약) → ## 소제목 {섹션_개수}개
· 소제목 후보: {추천모델} 개요 / {faq_세부주제} 상세 / {대상업종}에서의 활용 / 스펙과 실사용 포인트 / 비용·토너·약정 / 주의사항·오류 대응 / 복합기 렌탈 FAQ 자주 묻는 질문 / 핵심 요약 / 업체 소개
· FAQ 섹션: "Q:/A:" 3~5개({추천모델}·{대상업종} 관련).

{공통_종결}
{공통_모바일}
{공통_출력}
"""
        else:
            prompt = f"""당신은 네이버 SEO·검색의도 분석·E-E-A-T 콘텐츠 전문가입니다. 검색 사용자의 의도를 가장 먼저 해결하는 복합기렌탈 정보성 원고를 씁니다.

[입력]
· 메인 키워드: 복합기렌탈
· 지역 키워드: {지명키워드}
· 업체명: {업체명}
· 추천 모델: {추천모델}
· 대상 업종: {대상업종}
· 공백 제외 {목표글자수}자 이상

{공통_지명}
{seo_동의어_지침}

{공통_어조}

[원칙]
· 결론을 먼저 말한다. 광고보다 정보를 우선한다(정보 80% 홍보 20%).
· 구체적 숫자·사례를 넣고, 장점과 단점을 함께 설명한다.
· 업체 소개는 마지막에 짧게, 자화자찬 없이 담백하게.

[구성 — ## 소제목 {섹션_개수}개, 도입부는 ## 없음]
· 첫 줄 # 제목 → 도입(검색의도·결론·이 글에서 얻는 내용을 ## 없이 서술) → ## 소제목 {섹션_개수}개
· 소제목 주제 후보(분량에 맞게 고르고, FAQ와 마무리·업체 소개는 반드시 포함하고 맨 끝):
  한눈에 보기(핵심 요약 5~7개) / {지명키워드}에 복합기렌탈이 왜 필요한가 / 구매 vs 렌탈 비교 / 비용은 얼마나 드나(월 렌탈료·매수당 요금) / {추천모델} 소개와 {대상업종} 활용 / 유지관리와 A/S / 계약기간과 해지 / 설치 절차 / 주의사항 / 복합기 렌탈 FAQ 자주 묻는 질문 / 핵심 요약 / 업체 소개
· 추천 모델은 {추천모델} 하나만 다룬다. 스펙은 수치와 함께 {대상업종}에서 무엇이 편해지는지 붙여 쓴다.
· 소제목 첫 문장은 결론으로 시작한다.
· FAQ는 독자가 실제로 궁금해할 질문 기준 "Q:/A:"(답변 2~3문장) 3~5개.

{공통_종결}

{공통_모바일}

{공통_출력}
"""
        
        # 생성이 성공할 때까지 30초 간격으로 무한 재시도
        재시도_횟수 = 0
        while True:
            try:
                print(f"블로그 글 생성 시도 중... (시도 {재시도_횟수 + 1})")
                response = model.generate_content(prompt)
                content = response.text.replace('*', '')
                
                # HTML 태그와 마크다운 코드 블록 제거
                import re
                # HTML 태그 제거 (<br>, <p>, <div> 등)
                content = re.sub(r'<[^>]+>', '', content)
                # 마크다운 코드 블록 제거 (```, ''')
                content = re.sub(r'```[^`]*```', '', content, flags=re.DOTALL)
                content = re.sub(r"'''[^']*'''", '', content, flags=re.DOTALL)
                content = _원고_메타노트_제거(content)
                
                # 생성된 콘텐츠가 있는지 확인
                if content and len(content.strip()) > 0:
                    # 파일 저장
                    # 현재 스크립트가 있는 폴더에 저장
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    filename = resource_path("최종원고.txt")
                    
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(content)
                    _원고_작성_지명키워드_저장(지명키워드)
                    
                    print(f"생성 완료! 파일명: {filename}")
                    print(f"랜덤화 정보: {섹션_개수}개 섹션, {이미지_개수}개 이미지, {이미지_배치_방식}")
                    print(f"섹션별 글자수: {섹션별_글자수}")
                    print(f"문체: {문체_스타일}, 문단구조: {문단_구조_전략}, 특별요소: {특별_요소_추가}")
                    
                    # 블로그 콘텐츠 생성 완료 로그
                    중요_작업_로그_저장(f"블로그 콘텐츠 생성 완료: {filename}, {섹션_개수}개 섹션, {이미지_개수}개 이미지")
                    break  # 성공 시 루프 종료
                else:
                    print("생성된 콘텐츠가 없습니다. 30초 후 재시도합니다...")
                    재시도_횟수 += 1
                    time.sleep(30)
            except Exception as api_error:
                print(f"블로그 글 생성 중 오류가 발생했습니다: {str(api_error)}")
                print("30초 후 재시도합니다...")
                재시도_횟수 += 1
                time.sleep(30)
        
        # === 지명키워드 중복 체크 시작 ===
        print(f"\n=== 지명키워드 중복 체크 시작 ===")
        print(f"현재 지명키워드: '{지명키워드}'")
        
        try:
            # 구글 스프레드시트에서 작업완료확인 데이터 가져오기
            작업완료_df = 구글스프레드시트_작업완료확인_가져오기()
            
            if not 작업완료_df.empty and '지명키워드' in 작업완료_df.columns:
                # 가장 최근 작업한 지명키워드 가져오기 (마지막 행)
                if len(작업완료_df) > 0:
                    최근_지명키워드 = str(작업완료_df.iloc[-1]['지명키워드']).strip()
                    현재_지명키워드_정리 = str(지명키워드).strip()
                    
                    print(f"최근 작업한 지명키워드: '{최근_지명키워드}'")
                    print(f"현재 지명키워드: '{현재_지명키워드_정리}'")
                    
                    # 가장 최근 지명키워드와 비교
                    if 현재_지명키워드_정리 == 최근_지명키워드:
                        print(f"⚠️ 중복 발견! 가장 최근 작업한 지명키워드와 동일합니다.")
                        print("🔄 1단계부터 재시작합니다...")
                        중요_작업_로그_저장(f"지명키워드 중복 발견으로 인한 재시작: {지명키워드} (최근: {최근_지명키워드})")
                        
                        print("\n=== 프로그램 재시작 ===")
                        프로그램_같은_터미널_재시작(f"지명키워드 중복: {지명키워드}")
                    else:
                        print(f"✅ 중복 없음! 최근 작업한 지명키워드와 다릅니다.")
                        print("포스팅을 계속 진행합니다.")
                        중요_작업_로그_저장(f"지명키워드 중복 없음 확인: {지명키워드} (최근: {최근_지명키워드})")
                else:
                    print("작업완료확인 데이터가 비어있습니다. 중복 없음으로 처리합니다.")
            else:
                print("작업완료확인 데이터가 없거나 지명키워드 컬럼이 없습니다. 중복 없음으로 처리합니다.")
                
        except Exception as e:
            print(f"지명키워드 중복 체크 중 오류: {e}")
            print("오류로 인해 중복 없음으로 처리하고 포스팅을 계속 진행합니다.")
        
        return content, filename
        
    except Exception as e:
        print(f"콘텐츠 생성 중 오류가 발생했습니다: {str(e)}")
        return None, None

def 메인_프로그램():
    """메인 프로그램"""
    print("=== 블로그 콘텐츠 생성기 ===")
    print("돌쇠가 만든 Gemini AI 블로그 글 생성기입니다!")
    print()

    # 현재 작업 지명키워드와 일치하는 블로그제목 행에서 제목 추출
    try:
        df = pd.read_excel(resource_path('블로그제목.xlsx'))
        if '생성된제목' not in df.columns or '지명키워드' not in df.columns:
            print("엑셀 파일에 '생성된제목' 또는 '지명키워드' 컬럼이 없습니다.")
            return None, None
        현재_kw = _현재_작업_지명키워드()
        row = _블로그제목_현재키워드_행_선택(df, 현재_kw)
        if row is None:
            print(f"블로그제목.xlsx에 현재 지명키워드 '{현재_kw}'와 일치하는 행이 없습니다.")
            return None, None
        지명키워드 = str(row['지명키워드'])
        생성된제목 = str(row['생성된제목'])
        # 제목과 동일한 유형(유형_목록)으로 원고를 일괄되게 생성
        유형 = str(row['유형']).strip() if '유형' in df.columns and pd.notna(row.get('유형')) else ''
        if 유형 not in 유형_목록:
            유형 = random.choice(유형_목록)
        추천모델 = str(row['추천모델']).strip() if '추천모델' in df.columns and pd.notna(row.get('추천모델')) else ''
        if not 추천모델 or 추천모델.lower() == 'nan':
            추천모델 = random.choice(추천모델_목록)
        대상업종 = ''
        if '대상업종' in df.columns and pd.notna(row.get('대상업종')):
            대상업종 = str(row['대상업종']).strip()
        if not 대상업종 or 대상업종.lower() == 'nan':
            base = random.choice(대상업종_목록)
            if 유형 == "설치후기형":
                대상업종 = _설치후기_대상업종_표기(base)
            else:
                대상업종 = base
        faq_세부유형 = str(row['세부유형']).strip() if '세부유형' in df.columns and pd.notna(row.get('세부유형')) else ''
        faq_세부주제 = str(row['세부주제']).strip() if '세부주제' in df.columns and pd.notna(row.get('세부주제')) else ''
        if faq_세부유형.lower() == 'nan':
            faq_세부유형 = ''
        if faq_세부주제.lower() == 'nan':
            faq_세부주제 = ''
        print(f"랜덤 추출된 지명키워드: {지명키워드}")
        print(f"랜덤 추출된 블로그 제목: {생성된제목}")
        print(f"유형: {유형} / 추천모델: {추천모델} / 대상업종: {대상업종}")
        if 유형 == FAQ_글유형 and faq_세부유형:
            print(f"세부유형: {faq_세부유형} / 세부주제: {faq_세부주제}")
    except Exception as e:
        print(f"엑셀 파일 읽기 오류: {e}")
        return None, None

    print(f"\n[{유형}] 블로그 글을 생성합니다...")

    content, filename = 블로그_글_생성(
        지명키워드, 생성된제목, 유형, 추천모델, 대상업종, faq_세부유형, faq_세부주제
    )

    if content and filename:
        print(f"\n=== 생성 완료 ===")
        print(f"생성된 파일: {filename}")
        print(f"유형: {유형}")

        # 연관어 생성 및 저장
        print(f"\n=== 연관어 생성 시작 ===")
        연관어_리스트 = 연관어_생성(지명키워드)
        if 연관어_리스트:
            연관어_txt_저장(연관어_리스트, 지명키워드)
            print("연관어 생성 및 저장이 완료되었습니다!")
        else:
            print("연관어 생성에 실패했습니다.")
    else:
        print(f"\n=== 생성 실패 ===")
        print("블로그 글 생성에 실패했습니다.")
    return content, filename

if __name__ == "__main__":
    if _원고_재사용_모드:
        print("기존 원고 재사용 모드 - 블로그 원고/연관어 생성을 건너뜁니다.")
        중요_작업_로그_저장("기존 원고 재사용 모드 - 블로그 원고/연관어 생성 건너뜀")
        content, filename = None, resource_path("최종원고.txt")
    else:
        _최종원고_생성_무한_재시도(메인_프로그램)
        content, filename = None, resource_path("최종원고.txt")

import google.generativeai as genai
from google import genai
from google.genai import types
from PIL import Image
from io import BytesIO
import base64
import pyautogui
import pyperclip
import time
import random
import threading
import os
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains




def 구글스프레드시트_포스팅수_업데이트(아이디):
    """구글 스프레드시트에서 특정 아이디의 포스팅수를 +1 업데이트하는 함수"""
    import socket
    import time
    
    print(f"포스팅수 업데이트 시작: 아이디='{아이디}'")
    
    # 1. 파일 존재 여부 확인
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(키_파일_경로):
        print(f"오류: {키_파일_경로} 파일을 찾을 수 없습니다.")
        return False
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 2. 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 3. 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                # 5. 진행상황 출력
                if 시도_횟수 > 0:
                    print(f"포스팅수 업데이트 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 인증 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
                gc = gspread_authorize_with_timeout(creds)
                
                # 계정정보 스프레드시트 열기
                spreadsheet_id = '1JioOQCAlWxCpQnsr43UcQt9gWvCGDeFYlwlmT-m8B6s'
                spreadsheet = gspread_operation_with_timeout(
                    lambda: gc.open_by_key(spreadsheet_id),
                    timeout=20,
                    operation_name="스프레드시트 열기"
                )
                
                # 첫 번째 워크시트 선택
                worksheet = gspread_operation_with_timeout(
                    lambda: spreadsheet.get_worksheet(0),
                    timeout=20,
                    operation_name="워크시트 가져오기"
                )
                
                # 모든 데이터 가져오기
                all_values = gspread_operation_with_timeout(
                    lambda: worksheet.get_all_values(),
                    timeout=30,
                    operation_name="모든 데이터 가져오기"
                )
                print(f"스프레드시트 데이터 행 수: {len(all_values)}")
                
                if len(all_values) < 2:
                    print("계정정보 구글 스프레드시트에 데이터가 없습니다.")
                    return False
                
                # 헤더와 데이터 분리
                headers = all_values[0]
                data = all_values[1:]
                print(f"헤더: {headers}")
                
                # 아이디 컬럼 인덱스 찾기
                if '아이디' not in headers:
                    print("계정정보 구글 스프레드시트에 '아이디' 컬럼이 없습니다.")
                    return False
                
                아이디_컬럼_인덱스 = headers.index('아이디')
                print(f"아이디 컬럼 인덱스: {아이디_컬럼_인덱스}")
                
                # 포스팅수 컬럼 인덱스 찾기
                if '포스팅수' not in headers:
                    print("계정정보 구글 스프레드시트에 '포스팅수' 컬럼이 없습니다.")
                    return False
                
                포스팅수_컬럼_인덱스 = headers.index('포스팅수')
                print(f"포스팅수 컬럼 인덱스: {포스팅수_컬럼_인덱스}")
                
                # 해당 아이디 찾기
                아이디_찾음 = False
                for row_idx, row_data in enumerate(data, start=2):  # 2부터 시작 (헤더 다음 행)
                    print(f"행 {row_idx} 확인: {row_data}")
                    if len(row_data) > 아이디_컬럼_인덱스 and row_data[아이디_컬럼_인덱스] == 아이디:
                        아이디_찾음 = True
                        print(f"아이디 '{아이디}'를 행 {row_idx}에서 찾았습니다.")
                        
                        # 현재 포스팅수 가져오기
                        current_posting_count = 0
                        if len(row_data) > 포스팅수_컬럼_인덱스 and row_data[포스팅수_컬럼_인덱스]:
                            try:
                                current_posting_count = int(row_data[포스팅수_컬럼_인덱스])
                                print(f"현재 포스팅수: {current_posting_count}")
                            except ValueError:
                                current_posting_count = 0
                                print(f"포스팅수 파싱 오류, 0으로 설정")
                        else:
                            print("포스팅수 데이터가 없어 0으로 설정")
                        
                        # 포스팅수 +1
                        new_posting_count = current_posting_count + 1
                        print(f"새 포스팅수: {new_posting_count}")
                        
                        # 최대 3번 재시도
                        max_retries = 3
                        for retry_count in range(max_retries):
                            print(f"포스팅수 업데이트 시도 {retry_count + 1}/{max_retries}")
                            
                            # 스프레드시트 업데이트 (1-based 인덱스 사용)
                            gspread_operation_with_timeout(
                                lambda: worksheet.update_cell(row_idx, 포스팅수_컬럼_인덱스 + 1, new_posting_count),
                                timeout=20,
                                operation_name="포스팅수 업데이트"
                            )
                            print(f"스프레드시트 업데이트 완료: 행={row_idx}, 열={포스팅수_컬럼_인덱스 + 1}, 값={new_posting_count}")
                            
                            # 업데이트 확인을 위해 잠시 대기
                            time.sleep(2)
                            
                            # 업데이트 확인: 해당 셀의 현재 값 다시 가져오기
                            updated_cell_value = gspread_operation_with_timeout(
                                lambda: worksheet.cell(row_idx, 포스팅수_컬럼_인덱스 + 1).value,
                                timeout=20,
                                operation_name="업데이트 후 값 확인"
                            )
                            print(f"업데이트 후 확인: 셀 값 = {updated_cell_value}")
                            
                            try:
                                updated_posting_count = int(updated_cell_value) if updated_cell_value else 0
                                print(f"업데이트 후 포스팅수: {updated_posting_count}")
                                
                                if updated_posting_count == new_posting_count:
                                    print(f"✅ 포스팅수 업데이트 성공! 아이디 '{아이디}'의 포스팅수: {updated_posting_count}")
                                    return True
                                else:
                                    print(f"❌ 포스팅수 업데이트 실패: 예상값={new_posting_count}, 실제값={updated_posting_count}")
                                    if retry_count < max_retries - 1:
                                        print(f"재시도 중... ({retry_count + 1}/{max_retries})")
                                        time.sleep(1)
                                    else:
                                        print(f"최대 재시도 횟수({max_retries}) 초과. 포스팅수 업데이트 실패")
                                        return False
                            except ValueError:
                                print(f"❌ 업데이트된 값 파싱 오류: {updated_cell_value}")
                                if retry_count < max_retries - 1:
                                    print(f"재시도 중... ({retry_count + 1}/{max_retries})")
                                    time.sleep(1)
                                else:
                                    print(f"최대 재시도 횟수({max_retries}) 초과. 포스팅수 업데이트 실패")
                                    return False
                
                if not 아이디_찾음:
                    print(f"아이디 '{아이디}'를 계정정보 구글 스프레드시트에서 찾을 수 없습니다.")
                    print(f"사용 가능한 아이디들: {[row[아이디_컬럼_인덱스] for row in data if len(row) > 아이디_컬럼_인덱스]}")
                    return False
                
                if 시도_횟수 > 0:
                    print(f"포스팅수 업데이트 성공! (시도 {시도_횟수 + 1}회)")
                
                return True
                
            except (socket.timeout, TimeoutError):
                # 4. socket.timeout 예외 발생 시 30초 대기 후 재시도
                print(f"연결 타임아웃 발생 (시도 {시도_횟수 + 1}/10). 30초 대기 후 재시도합니다...")
                if 시도_횟수 < 9:
                    time.sleep(30)
                    
            except Exception as e:
                print(f"포스팅수 업데이트 중 오류 (시도 {시도_횟수 + 1}/10): {e}")
                import traceback
                print(f"상세 오류: {traceback.format_exc()}")
                if 시도_횟수 < 9:
                    time.sleep(5)
        
        print("포스팅수 업데이트 실패: 최대 재시도 횟수(10회)에 도달했습니다.")
        return False
        
    finally:
        # 6. 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def get_random_promo_text_from_spreadsheet(df, 현재_지명, max_retries=3):
    """
    지명 기반으로 하나노란 값을 찾아서 아이디2 스프레드시트에서 홍보문구를 랜덤으로 선택하는 함수
    
    매개변수:
    - df: 계정정보 데이터프레임
    - 현재_지명: 현재 작업하는 지명
    - max_retries: 최대 재시도 횟수 (기본값: 3)
    
    반환값:
    - 선택된 홍보문구 문자열
    """
    for attempt in range(max_retries):
        try:
            print(f"=== 홍보문구 선택 시도 {attempt + 1}/{max_retries} ===")
            
            # 1. 로컬 작업큐 캐시에서 하나노란 값 확인
            print("1단계: 로컬 작업큐 캐시에서 하나노란 값 확인")
            try:
                지명키워드_df = 지명키워드_df_가져오기()
                if not 지명키워드_df.empty and '하나노란' in 지명키워드_df.columns:
                    지명_하나노란_값 = str(지명키워드_df.iloc[0]['하나노란']).strip()
                    if 지명_하나노란_값 == 'nan':
                        지명_하나노란_값 = ""
                    
                    if not 지명_하나노란_값:
                        print("작업큐 캐시의 하나노란 값이 비어있습니다.")
                        if attempt < max_retries - 1:
                            print("재시도합니다...")
                            import time
                            time.sleep(10)
                            continue
                        return ""
                    
                    print(f"작업큐 캐시에서 하나노란 값 가져오기 성공: '{지명_하나노란_값}'")
                else:
                    print("작업큐 캐시가 비어있거나 하나노란 컬럼이 없습니다.")
                    if attempt < max_retries - 1:
                        print("재시도합니다...")
                        import time
                        time.sleep(10)
                        continue
                    return ""
            except Exception as e:
                print(f"작업큐 캐시 읽기 중 오류 발생: {e}")
                if attempt < max_retries - 1:
                    print("재시도합니다...")
                    import time
                    time.sleep(10)
                    continue
                return ""
            
            # 2. 아이디2 스프레드시트에서 동일한 하나노란 값 찾아서 홍보문구 랜덤 선택
            print("2단계: 아이디2 스프레드시트에서 홍보문구 선택")
            
            # 아이디2 스프레드시트에서 계정정보 가져오기
            아이디2_df = 구글_시트_읽기(아이디2_스프레드시트_ID, "시트1")
            
            if 아이디2_df.empty:
                print("아이디2 스프레드시트에서 계정정보를 가져올 수 없습니다.")
                if attempt < max_retries - 1:
                    print("재시도합니다...")
                    import time
                    time.sleep(10)
                    continue
                return ""
            
            # 하나노란 값이 일치하는 행들만 필터링
            matching_rows = 아이디2_df[아이디2_df['하나노란'].astype(str) == 지명_하나노란_값]
            
            if len(matching_rows) == 0:
                print(f"아이디2 스프레드시트에서 하나노란 값 '{지명_하나노란_값}'에 해당하는 계정이 없습니다.")
                if attempt < max_retries - 1:
                    print("재시도합니다...")
                    import time
                    time.sleep(10)
                    continue
                return ""
            
            # 랜덤으로 하나의 행 선택
            selected_row = matching_rows.sample(n=1).iloc[0]
            
            # 선택된 행의 홍보문구 셀 전체 내용 반환
            selected_promo_text = str(selected_row['홍보문구']).strip()
            
            if not selected_promo_text or selected_promo_text == 'nan':
                print(f"선택된 행의 홍보문구가 비어있습니다.")
                if attempt < max_retries - 1:
                    print("재시도합니다...")
                    import time
                    time.sleep(10)
                    continue
                return ""
            
            print(f"하나노란 값 '{지명_하나노란_값}' → 랜덤 선택된 홍보문구: {selected_promo_text}")
            
            print("=== 홍보문구 선택 완료 ===")
            
            return selected_promo_text
            
        except Exception as e:
            print(f"홍보문구 선택 중 오류 발생 (시도 {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                print("재시도합니다...")
                import time
                time.sleep(10)
                continue
            else:
                print("모든 재시도가 실패했습니다.")
                return ""
    
    return ""


def get_random_naver_account(use_google_sheets=True):
    """구글 스프레드시트 또는 Excel에서 계정 정보를 가져와 포스팅수가 적은 것부터 우선 선택"""
    
    if use_google_sheets:
        # 구글 스프레드시트에서 계정 정보 가져오기
        df = 구글스프레드시트_계정정보_가져오기()
        
        if df.empty:
            print("구글 스프레드시트에서 계정 정보를 가져올 수 없어 Excel 파일을 사용합니다.")
            use_google_sheets = False
    
    if not use_google_sheets:
        raise ValueError("구글 스프레드시트에서 계정 정보를 가져올 수 없습니다.")
    
    # '아이디', '비번', '홍보문구', '하나노란' 컬럼에서 결측치가 없는 행만 필터링
    df = df.dropna(subset=['아이디', '비번', '홍보문구', '하나노란'])
    
    # 데이터가 비어있는지 확인
    if len(df) == 0:
        raise ValueError("계정 정보에 유효한 계정이 없습니다.")
    
    # === 구글 스프레드시트에서 현재 사용 중인 아이디들 가져오기 ===
    사용중인_아이디들 = []
    try:
        사용중인_아이디들 = 구글스프레드시트_사용중인_아이디_목록_가져오기()
        print(f"현재 구글 스프레드시트에서 사용 중인 아이디들: {사용중인_아이디들}")
    except Exception as e:
        print(f"구글 스프레드시트에서 사용 중인 아이디 목록 가져오기 실패: {e}")
        # 오류 발생 시 빈 리스트로 처리 (모든 아이디 사용 가능)
        사용중인_아이디들 = []
    
    # === 사용 중이지 않은 아이디들만 필터링 ===
    사용가능한_아이디들 = df[~df['아이디'].isin(사용중인_아이디들)]
    
    if len(사용가능한_아이디들) == 0:
        print("모든 아이디가 구글 스프레드시트에서 사용 중입니다.")
        print("잠시 후 다시 시도하거나 다른 컴퓨터에서 작업을 완료해주세요.")
        raise ValueError("사용 가능한 아이디가 없습니다.")
    
    print(f"사용 가능한 아이디 수: {len(사용가능한_아이디들)}개")
    
    # === 아이디별 하루 최대 포스팅 수 제한 추가 ===
    from datetime import date
    today = date.today()
    
    # 오늘 포스팅한 아이디는 제외
    오늘_포스팅_완료_아이디들 = []
    
    # 구글 스프레드시트에서 오늘 포스팅한 아이디 확인
    try:
        작업완료_df = 구글스프레드시트_작업완료확인_가져오기()
        if not 작업완료_df.empty and '아이디' in 작업완료_df.columns and '작성일시' in 작업완료_df.columns:
            for idx, row in 작업완료_df.iterrows():
                try:
                    작성일시 = pd.to_datetime(row['작성일시'])
                    if 작성일시.date() == today:
                        아이디 = row['아이디']
                        # 오늘 포스팅한 횟수 확인
                        오늘_포스팅_횟수 = len(작업완료_df[
                            (작업완료_df['아이디'] == 아이디) & 
                            (pd.to_datetime(작업완료_df['작성일시']).dt.date == today)
                        ])
                        
                        # 해당 아이디의 하루 최대 포스팅 수 확인
                        아이디_정보 = 사용가능한_아이디들[사용가능한_아이디들['아이디'] == 아이디]
                        if len(아이디_정보) > 0:
                            # 하루최대포스팅수 컬럼이 있으면 사용, 없으면 기본값 3
                            if '하루최대포스팅수' in 아이디_정보.columns:
                                하루_최대_포스팅수 = 아이디_정보.iloc[0]['하루최대포스팅수']
                                if pd.isna(하루_최대_포스팅수):  # NaN이면 기본값 3
                                    하루_최대_포스팅수 = 3
                                else:
                                    # 문자열인 경우 정수로 변환
                                    try:
                                        하루_최대_포스팅수 = int(float(하루_최대_포스팅수))
                                    except (ValueError, TypeError):
                                        하루_최대_포스팅수 = 3  # 변환 실패시 기본값
                            else:
                                하루_최대_포스팅수 = 3  # 기본값
                            
                            # 하루최대포스팅수가 0인 경우 로그인 불가 (더 엄격한 체크)
                            if 하루_최대_포스팅수 <= 0 or str(하루_최대_포스팅수).strip() == "0":
                                print(f"아이디 '{아이디}'는 하루최대포스팅수가 {하루_최대_포스팅수}로 설정되어 로그인이 불가능합니다.")
                                print(f"데이터 타입: {type(하루_최대_포스팅수)}, 값: {repr(하루_최대_포스팅수)}")
                                continue
                            
                            print(f"아이디 '{아이디}'의 하루최대포스팅수: {하루_최대_포스팅수}")
                            print(f"로그인 가능 여부: {'가능' if 하루_최대_포스팅수 > 0 else '불가능'}")
                            
                            if 오늘_포스팅_횟수 >= 하루_최대_포스팅수:
                                오늘_포스팅_완료_아이디들.append(아이디)
                                print(f"아이디 '{아이디}'는 오늘 {하루_최대_포스팅수}개 포스팅을 완료했습니다.")
                except Exception as e:
                    print(f"아이디 '{row.get('아이디', '알수없음')}' 포스팅 수 확인 중 오류: {e}")
                    continue
            else:
                print("구글 스프레드시트에서 작업완료확인 데이터를 가져올 수 없습니다.")
    except Exception as e:
        print(f"오늘 포스팅 확인 중 오류: {e}")
    
    # 오늘 포스팅 완료된 아이디들 제외
    사용가능한_아이디들 = 사용가능한_아이디들[~사용가능한_아이디들['아이디'].isin(오늘_포스팅_완료_아이디들)]
    
    # === 하루최대포스팅수가 0인 아이디들 제외 ===
    if '하루최대포스팅수' in 사용가능한_아이디들.columns:
        # 하루최대포스팅수가 0 이하인 아이디들 필터링
        사용가능한_아이디들 = 사용가능한_아이디들[
            (사용가능한_아이디들['하루최대포스팅수'] > 0) & 
            (사용가능한_아이디들['하루최대포스팅수'].notna())
        ]
        print(f"하루최대포스팅수가 0 이하인 아이디를 제외한 후 {len(사용가능한_아이디들)}개의 아이디가 남았습니다.")
        
        # 제외된 아이디들 확인
        제외된_아이디들 = 사용가능한_아이디들[
            (사용가능한_아이디들['하루최대포스팅수'] <= 0) | 
            (사용가능한_아이디들['하루최대포스팅수'].isna())
        ]
        if len(제외된_아이디들) > 0:
            print("하루최대포스팅수가 0 이하로 제외된 아이디들:")
            for idx, row in 제외된_아이디들.iterrows():
                print(f"  {row['아이디']}: 하루최대포스팅수 = {row['하루최대포스팅수']}")
    
    if len(사용가능한_아이디들) == 0:
        print("하루최대포스팅수 제한으로 인해 사용 가능한 아이디가 없습니다.")
        print("하루최대포스팅수가 1 이상인 아이디만 사용 가능합니다.")
        raise ValueError("사용 가능한 아이디가 없습니다.")
    
    # === 포스팅수가 적은 순으로 정렬하여 우선 선택 ===
    if '포스팅수' in 사용가능한_아이디들.columns:
        사용가능한_아이디들 = 사용가능한_아이디들.sort_values('포스팅수', ascending=True)
        # 포스팅수가 가장 적은 계정들 중에서 랜덤 선택
        min_posting = 사용가능한_아이디들['포스팅수'].min()
        min_posting_df = 사용가능한_아이디들[사용가능한_아이디들['포스팅수'] == min_posting]
        
        # min_posting_df가 비어있지 않은지 확인
        if len(min_posting_df) > 0:
            row = min_posting_df.sample(n=1).iloc[0]
            print(f"포스팅수 {min_posting}인 아이디 중에서 선택: {row['아이디']}")
        else:
            # 비어있으면 전체에서 랜덤 선택
            row = 사용가능한_아이디들.sample(n=1).iloc[0]
            print(f"랜덤 선택된 아이디: {row['아이디']}")
    else:
        # 포스팅수 컬럼이 없으면 랜덤 선택
        row = 사용가능한_아이디들.sample(n=1).iloc[0]
        print(f"포스팅수 정보 없이 랜덤 선택된 아이디: {row['아이디']}")
    
    # 지명 기반으로 홍보문구 랜덤 선택
    현재_지명 = 지명키워드에서_지명_추출()
    random_promo_text = get_random_promo_text_from_spreadsheet(df, 현재_지명)
    
    return str(row['아이디']), str(row['비번']), random_promo_text, str(row['하나노란']), row.name  # row.name은 인덱스 번호



def 구글스프레드시트_사용중인_아이디_목록_가져오기():
    """구글 스프레드시트에서 현재 사용 중인 아이디 목록을 가져오는 함수"""
    import socket
    import time
    
    # 1. 파일 존재 여부 확인
    키_파일_경로 = resource_path('khon21-534690057aec.json')
    if not os.path.exists(키_파일_경로):
        print(f"오류: {키_파일_경로} 파일을 찾을 수 없습니다.")
        return []
    
    # 원래 타임아웃 저장
    원래_타임아웃 = socket.getdefaulttimeout()
    
    try:
        # 2. 타임아웃 30초 설정
        socket.setdefaulttimeout(30)
        
        # 3. 최대 10번 재시도
        for 시도_횟수 in range(10):
            try:
                # 5. 진행상황 출력
                if 시도_횟수 > 0:
                    print(f"사용중인 아이디 목록 가져오기 재시도 중... ({시도_횟수 + 1}/10)")
                
                # 구글 스프레드시트 연결 설정
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(키_파일_경로, scopes=scope)
                client = gspread_authorize_with_timeout(creds)
                
                # 구글 스프레드시트 열기
                spreadsheet_url = "https://docs.google.com/spreadsheets/d/1w5ubHKn418A9ypJEa9nKjdskOcZ1BImP89xO8PRISgs/edit?usp=sharing"
                spreadsheet = client.open_by_url(spreadsheet_url)
                worksheet = spreadsheet.sheet1
                
                # 현재 데이터 확인
                current_data = worksheet.get_all_values()
                
                사용중인_아이디들 = []
                if current_data and len(current_data) > 1:
                    # A2부터 A6까지 확인 (5개 아이디 동시 사용 가능)
                    for row_idx in range(1, min(6, len(current_data))):  # A2, A3, A4, A5, A6 확인
                        if current_data[row_idx] and current_data[row_idx][0] and str(current_data[row_idx][0]).strip():
                            사용중인_아이디 = str(current_data[row_idx][0]).strip()
                            사용중인_아이디들.append(사용중인_아이디)
                
                if 시도_횟수 > 0:
                    print(f"사용중인 아이디 목록 가져오기 성공! (시도 {시도_횟수 + 1}회)")
                
                return 사용중인_아이디들
                
            except (socket.timeout, TimeoutError):
                # 4. socket.timeout 예외 발생 시 30초 대기 후 재시도
                print(f"연결 타임아웃 발생 (시도 {시도_횟수 + 1}/10). 30초 대기 후 재시도합니다...")
                if 시도_횟수 < 9:
                    time.sleep(30)
                    
            except Exception as e:
                print(f"사용중인 아이디 목록 가져오기 중 오류 (시도 {시도_횟수 + 1}/10): {e}")
                if 시도_횟수 < 9:
                    time.sleep(5)
        
        print("사용중인 아이디 목록 가져오기 실패: 최대 재시도 횟수(10회)에 도달했습니다.")
        return []
        
    finally:
        # 6. 원래 타임아웃 복원
        socket.setdefaulttimeout(원래_타임아웃)

def naver_login_and_prepare(driver, id, pw, max_retries=3):
    """네이버 로그인 및 블로그 글쓰기 준비 (구글 스프레드시트 중복 로그인 방지 포함)"""
    
    # === 새탭 열기 방지 JavaScript 설정 ===
    try:
        driver.execute_script("""
            // 새탭 열기 방지
            window.open = function() { return window; };
            
            // target="_blank" 링크 클릭 시 새탭 대신 현재 탭에서 열기
            document.addEventListener('click', function(e) {
                if (e.target.tagName === 'A' && e.target.target === '_blank') {
                    e.preventDefault();
                    e.target.target = '_self';
                    window.location.href = e.target.href;
                }
            });
            
            // JavaScript로 새탭 열기 시도 시 방지
            const originalOpen = window.open;
            window.open = function(url, name, specs) {
                if (name === '_blank' || name === 'blank') {
                    window.location.href = url;
                    return window;
                }
                return originalOpen.apply(this, arguments);
            };
        """)
        print("새탭 열기 방지 JavaScript 설정 완료")
    except Exception as e:
        print(f"새탭 방지 JavaScript 설정 중 오류: {e}")
    
    # === 로그인금지시간대 확인 ===
    print(f"아이디 '{id}'의 로그인금지시간대를 확인하는 중...")
    
    # 아이디2 구글 시트에서 해당 아이디의 로그인금지시간대 확인
    try:
        작업아이디_df = 구글스프레드시트_계정정보_가져오기()
        if not 작업아이디_df.empty and not 로그인금지시간대_확인(id, 작업아이디_df):
            print("현재 시간에 로그인이 금지되어 있습니다.")
            return False
    except Exception as e:
        print(f"로그인금지시간대 확인 중 오류 발생: {e}")
        # 오류 시에는 로그인 허용
    
    print("로그인금지시간대 확인이 완료되었습니다. 로그인을 진행합니다.")
    
    # === 구글 스프레드시트 중복 로그인 방지 시스템 ===
    print(f"아이디 '{id}'의 중복 로그인 방지를 확인하는 중...")
    
    # 1. 아이디가 이미 사용 중인지 확인 (이미 선택된 아이디이므로 빠른 확인)
    if 구글스프레드시트_아이디_사용중_확인(id):
        print(f"아이디 '{id}'가 이미 다른 컴퓨터에서 사용 중입니다.")
        print("다른 아이디를 사용하거나 잠시 후 다시 시도해주세요.")
        return False
    
    # 2. 구글 스프레드시트에 아이디 입력 (사용 중 표시)
    if not 구글스프레드시트_아이디_입력(id):
        print(f"구글 스프레드시트에 아이디 '{id}' 입력에 실패했습니다.")
        return False
    
    print(f"아이디 '{id}'가 성공적으로 등록되었습니다. 로그인을 시작합니다...")
    
    try:
        # === 네이버 로그인 시작 ===
        driver.get("https://nid.naver.com/nidlogin.login")
        time.sleep(20)  # 페이지 로딩 대기
        
        # IP 보안 설정 확인 및 OFF로 설정
        try:
            # IP 보안 스위치 상태 확인
            ip_security_element = driver.find_element(By.CSS_SELECTOR, "#login_keep_wrap > div.ip_check > span > label > span")
            element_class = ip_security_element.get_attribute("class")
            
            if "switch_off" in element_class:
                print("✅ IP 보안이 이미 OFF 상태입니다.")
            elif "switch_on" in element_class:
                print("⚠️ IP 보안이 ON 상태입니다. OFF로 변경합니다...")
                # IP 보안 스위치 클릭하여 OFF로 변경
                ip_security_switch = driver.find_element(By.CSS_SELECTOR, "#login_keep_wrap > div.ip_check > span > label")
                ip_security_switch.click()
                time.sleep(10)
                print("✅ IP 보안을 OFF로 변경했습니다.")
            else:
                print(f"⚠️ IP 보안 상태를 알 수 없습니다. (클래스: {element_class})")
                
        except Exception as e:
            print(f"⚠️ IP 보안 설정 확인/변경 중 오류 (무시하고 진행): {e}")
        
        # 아이디 입력
        pyperclip.copy(id)
        driver.find_element(By.CSS_SELECTOR, "#id").click()
        driver.find_element(By.CSS_SELECTOR, "#id").send_keys(Keys.CONTROL, 'v')
        
        # 비밀번호 입력
        pyperclip.copy(pw)
        driver.find_element(By.CSS_SELECTOR, "#pw").click()
        driver.find_element(By.CSS_SELECTOR, "#pw").send_keys(Keys.CONTROL, 'v')
        
        # 로그인 버튼 클릭
        driver.find_element(By.CSS_SELECTOR, "#log\\.login").click()
        time.sleep(10)  # 로그인 완료 대기 시간 증가
        
        # 로그인 성공 확인
        try:
            # 로그인 후 잠시 대기 (페이지 로딩 대기)
            time.sleep(10)
            
            # URL 변경 대기 (최대 30초 대기)
            try:
                wait = WebDriverWait(driver, 30)
                wait.until(lambda d: "nid.naver.com" not in d.current_url or d.current_url != "https://nid.naver.com/nidlogin.login")
                print("URL 변경 완료")
            except:
                print("URL 변경 대기 시간 초과, 현재 URL로 확인 진행")
            
            # 현재 URL 확인
            current_url = driver.current_url
            print(f"로그인 후 현재 URL: {current_url}")
            
            # 로그인 성공 여부를 여러 방법으로 확인
            로그인_성공 = False
            
            # 방법 1: URL 확인 (로그인 성공 시 리다이렉트)
            if "nid.naver.com" not in current_url:
                print("URL 확인: 로그인 페이지에서 벗어났습니다.")
                로그인_성공 = True
            
            # 방법 2: 네이버 메인 페이지로 이동하여 확인
            if not 로그인_성공:
                driver.get("https://www.naver.com")
                
                # 페이지 로딩 대기 (최대 30초)
                try:
                    wait = WebDriverWait(driver, 30)
                    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                    print("네이버 메인 페이지 로딩 완료")
                except:
                    print("페이지 로딩 대기 시간 초과, 진행")
                
                time.sleep(5)  # 추가 안정화 대기
                
                # 여러 로그인 상태 확인 방법 시도
                try:
                    # 방법 2-1: 프로필 요소 확인 (최대 20초 대기)
                    try:
                        wait = WebDriverWait(driver, 20)
                        profile_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".sc_login")))
                        print("로그인 상태 확인: 프로필 요소 발견")
                        로그인_성공 = True
                    except:
                        # 방법 2-2: 사용자 메뉴 확인 (최대 20초 대기)
                        try:
                            wait = WebDriverWait(driver, 20)
                            user_menu = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gnb_my")))
                            print("로그인 상태 확인: 사용자 메뉴 발견")
                            로그인_성공 = True
                        except:
                            print("로그인 상태 확인: 명확한 로그인 상태를 확인할 수 없습니다.")
                            # 기본적으로 성공으로 간주 (URL이 변경되었으므로)
                            로그인_성공 = True
                except Exception as e:
                    print(f"로그인 상태 확인 중 오류: {e}")
                    # 기본적으로 성공으로 간주
                    로그인_성공 = True
            
            if 로그인_성공:
                print("네이버 로그인이 성공적으로 완료되었습니다.")
                
                # 로그인 성공 로그 저장
                중요_작업_로그_저장(f"네이버 로그인 성공: 아이디={id}")
                
                # === 로그인 성공 시 구글 스프레드시트에 로그인 시간 기록 ===
                try:
                    if 구글스프레드시트_로그인시간_업데이트(id):
                        print(f"아이디 '{id}'의 로그인 시간이 구글 스프레드시트에 기록되었습니다.")
                        작업_로그_저장(f"로그인 시간 구글 스프레드시트 기록 완료: 아이디={id}")
                    else:
                        print(f"경고: 아이디 '{id}'의 로그인 시간을 구글 스프레드시트에 기록할 수 없습니다.")
                        오류_로그_저장(f"로그인 시간 구글 스프레드시트 기록 실패: 아이디={id}")
                    
                except Exception as e:
                    print(f"로그인 시간 기록 중 오류: {e}")
                    오류_로그_저장(f"로그인 시간 기록 중 오류: {e}")
                    
            else:
                print("네이버 로그인에 실패했습니다.")
                # 로그인 실패 시 구글 스프레드시트에서 아이디 삭제
                구글스프레드시트_아이디_삭제(id)
                return False
                
        except Exception as e:
            print(f"로그인 상태 확인 중 오류: {e}")
            print("오류가 발생했지만 기본적으로 로그인 성공으로 간주합니다.")
            # 오류가 발생해도 기본적으로 성공으로 간주 (네이버 페이지 구조 변경 가능성)
            pass
        
        # === 로그인 성공 후 서로이웃 작업 또는 랜덤 브라우징 ===
        print("\n" + "="*50)
        print("서로이웃작업 상태 확인 중...")
        print("="*50)
        
        # 구글 스프레드시트에서 서로이웃작업 값 확인
        서로이웃작업_값 = 구글스프레드시트_서로이웃작업_확인(id)
        
        # 서로이웃 추가 작업 부분 주석처리 (활성화 시 아래 조건을 서로이웃작업_값 == 0 으로 변경)
        if False:  # 서로이웃 추가 작업 주석처리 (원래: 서로이웃작업_값 == 0)
            # 서로이웃 작업 진행
            print("\n서로이웃작업 값이 0이므로 서로이웃 작업을 진행합니다.")
            중요_작업_로그_저장(f"서로이웃작업 값 확인: {서로이웃작업_값} - 서로이웃 작업 진행")
            
            서로이웃_작업_시도_여부 = False  # 서로이웃 작업 시도 여부 플래그
            서로이웃_작업_업데이트_완료 = False  # 서로이웃작업 값 업데이트 완료 여부
            
            try:
                # 현재 로그인된 아이디 확인
                로그인_아이디 = 서로이웃_get_current_login_id(driver)
                if not 로그인_아이디:
                    # 아이디를 확인할 수 없으면 전달받은 id 사용
                    로그인_아이디 = id
                    print(f"로그인 아이디를 자동으로 확인할 수 없어 전달받은 아이디를 사용합니다: {로그인_아이디}")
                else:
                    print(f"확인된 로그인 아이디: {로그인_아이디}")
                
                # 서로이웃 작업 수행
                서로이웃_작업_시도_여부 = True  # 서로이웃 작업 시도 시작
                서로이웃_작업_업데이트_완료 = False  # 서로이웃작업 값 업데이트 완료 여부
                서로이웃_작업_결과 = 서로이웃_작업_수행(driver, 로그인_아이디)
                
                # 브라우저 재시작이 필요한 경우 처리
                if isinstance(서로이웃_작업_결과, str) and 서로이웃_작업_결과.startswith("브라우저_재시작_필요"):
                    # 반환값에서 현재까지 성공 횟수 추출
                    parts = 서로이웃_작업_결과.split(":")
                    현재_성공_횟수 = int(parts[1]) if len(parts) > 1 else 0
                    
                    print(f"⚠️ 연속 실패로 인해 브라우저를 재시작합니다. (현재 성공: {현재_성공_횟수}명)")
                    중요_작업_로그_저장(f"서로이웃 연속 실패 - 브라우저 재시작 (현재 성공: {현재_성공_횟수}명)")
                    
                    # 브라우저 재시작 전 모든 Chrome 프로세스 강제 종료
                    크롬_프로세스_강제_종료()
                    
                    # 기존 브라우저 종료
                    try:
                        driver.quit()
                        print("기존 브라우저를 종료했습니다.")
                    except:
                        pass
                    
                    # 새로운 브라우저 시작
                    print("\n새로운 브라우저를 시작합니다...")
                    chrome_options = uc_포스팅_크롬_옵션_생성()
                    driver = uc_크롬_드라이버_생성(chrome_options)
                    print("✅ 새로운 브라우저가 시작되었습니다.")
                    
                    # 다시 로그인 시도
                    print("다시 로그인을 시도합니다...")
                    try:
                        # 네이버 로그인 시작
                        driver.get("https://nid.naver.com/nidlogin.login")
                        time.sleep(15)  # 페이지 로딩 대기
                        
                        # IP 보안 설정 확인 및 OFF로 설정
                        try:
                            ip_security_element = driver.find_element(By.CSS_SELECTOR, "#login_keep_wrap > div.ip_check > span > label > span")
                            element_class = ip_security_element.get_attribute("class")
                            
                            if "switch_off" in element_class:
                                print("IP 보안이 이미 OFF 상태입니다.")
                            else:
                                print("IP 보안을 OFF로 설정합니다...")
                                ip_security_element.click()
                                time.sleep(2)
                        except Exception as e:
                            print(f"IP 보안 설정 확인 중 오류 (무시하고 계속): {e}")
                        
                        # 아이디 입력
                        driver.find_element(By.ID, "id").send_keys(id)
                        time.sleep(1)
                        
                        # 비밀번호 입력
                        driver.find_element(By.ID, "pw").send_keys(pw)
                        time.sleep(1)
                        
                        # 로그인 버튼 클릭
                        driver.find_element(By.ID, "log.login").click()
                        time.sleep(10)
                        
                        # 재로그인 성공 확인 로직 개선
                        로그인_성공 = False
                        try:
                            # 현재 URL 확인
                            현재_URL = driver.current_url
                            print(f"로그인 후 현재 URL: {현재_URL}")
                            
                            # 방법 1: URL 확인 - 로그인 페이지에서 벗어났는지 확인
                            if "nid.naver.com" not in 현재_URL:
                                print("URL 확인: 로그인 페이지에서 벗어났습니다.")
                                로그인_성공 = True
                            else:
                                # 방법 2: 네이버 메인 페이지로 이동하여 프로필 요소 확인
                                try:
                                    driver.get("https://www.naver.com")
                                    time.sleep(3)
                                    
                                    # 프로필 요소 확인 (.sc_login)
                                    try:
                                        WebDriverWait(driver, 5).until(
                                            EC.presence_of_element_located((By.CSS_SELECTOR, ".sc_login"))
                                        )
                                        print("로그인 상태 확인: 프로필 요소 발견")
                                        로그인_성공 = True
                                    except:
                                        # 사용자 메뉴 확인 (.gnb_my)
                                        try:
                                            WebDriverWait(driver, 5).until(
                                                EC.presence_of_element_located((By.CSS_SELECTOR, ".gnb_my"))
                                            )
                                            print("로그인 상태 확인: 사용자 메뉴 발견")
                                            로그인_성공 = True
                                        except:
                                            # 로그인 버튼이 없으면 성공으로 간주
                                            try:
                                                driver.find_element(By.CSS_SELECTOR, "#gnb_login_button")
                                                print("로그인 상태 확인: 로그인 버튼이 아직 있습니다.")
                                                로그인_성공 = False
                                            except:
                                                print("로그인 상태 확인: 로그인 버튼이 없습니다. 성공으로 간주합니다.")
                                                로그인_성공 = True
                                except Exception as check_e:
                                    print(f"로그인 상태 확인 중 오류: {check_e}")
                                    # 오류 발생 시 기본적으로 성공으로 간주
                                    로그인_성공 = True
                            
                            if 로그인_성공:
                                print("✅ 로그인 성공! 메인 페이지로 이동했습니다.")
                                중요_작업_로그_저장("브라우저 재시작 후 로그인 완료")
                                
                                # 서로이웃 작업 다시 시도
                                print("\n서로이웃 작업을 다시 시도합니다...")
                                서로이웃_작업_결과 = 서로이웃_작업_수행(driver, 로그인_아이디)
                            else:
                                print("❌ 재로그인에 실패했습니다.")
                                오류_로그_저장("브라우저 재시작 후 로그인 실패")
                                
                                # 재로그인 실패 시 서로이웃작업 값 +1 업데이트
                                if 구글스프레드시트_서로이웃작업_업데이트(id):
                                    print("✅ 서로이웃작업 값이 업데이트되었습니다.")
                                    중요_작업_로그_저장("서로이웃작업 값 업데이트 완료 (재로그인 실패)")
                                    서로이웃_작업_업데이트_완료 = True
                                else:
                                    print("⚠️ 서로이웃작업 값 업데이트에 실패했습니다.")
                                    오류_로그_저장("서로이웃작업 값 업데이트 실패 (재로그인 실패)")
                                
                                # 랜덤 브라우징으로 자동 전환
                                print("\n🌐 네이버 랜덤 브라우징을 시작합니다...")
                                중요_작업_로그_저장("재로그인 실패 후 랜덤 브라우징 시작")
                                
                                try:
                                    driver.get("https://www.naver.com")
                                    time.sleep(random.uniform(2, 3))
                                    브라우징_시간 = random.uniform(3, 5)
                                    if 네이버_랜덤_브라우징(driver, 브라우징_시간):
                                        print("✅ 랜덤 브라우징이 완료되었습니다!")
                                        중요_작업_로그_저장("재로그인 실패 후 랜덤 브라우징 완료")
                                    else:
                                        print("⚠️ 랜덤 브라우징에 실패했지만 블로그 포스팅을 계속 진행합니다.")
                                        중요_작업_로그_저장("재로그인 실패 후 랜덤 브라우징 실패하지만 진행")
                                except Exception as browse_e:
                                    print(f"⚠️ 랜덤 브라우징 중 오류가 발생했지만 블로그 포스팅을 계속 진행합니다: {browse_e}")
                                    중요_작업_로그_저장(f"재로그인 실패 후 랜덤 브라우징 오류하지만 진행: {str(browse_e)}")
                                
                                서로이웃_작업_결과 = False
                                
                        except Exception as check_e:
                            print(f"⚠️ 로그인 상태 확인 중 오류 발생: {check_e}")
                            오류_로그_저장(f"브라우저 재시작 후 로그인 상태 확인 오류: {str(check_e)}")
                            # 오류 발생 시 기본적으로 성공으로 간주하고 계속 진행
                            print("오류가 발생했지만 기본적으로 로그인 성공으로 간주하고 계속 진행합니다.")
                            중요_작업_로그_저장("브라우저 재시작 후 로그인 완료 (오류 발생하지만 진행)")
                            
                            # 서로이웃 작업 다시 시도
                            print("\n서로이웃 작업을 다시 시도합니다...")
                            서로이웃_작업_결과 = 서로이웃_작업_수행(driver, 로그인_아이디)
                        
                    except Exception as login_e:
                        print(f"⚠️ 재로그인 중 오류 발생: {login_e}")
                        오류_로그_저장(f"브라우저 재시작 후 로그인 실패: {str(login_e)}")
                        
                        # 재로그인 실패 시 서로이웃작업 값 +1 업데이트
                        if 구글스프레드시트_서로이웃작업_업데이트(id):
                            print("✅ 서로이웃작업 값이 업데이트되었습니다.")
                            중요_작업_로그_저장("서로이웃작업 값 업데이트 완료 (재로그인 오류)")
                            서로이웃_작업_업데이트_완료 = True
                        else:
                            print("⚠️ 서로이웃작업 값 업데이트에 실패했습니다.")
                            오류_로그_저장("서로이웃작업 값 업데이트 실패 (재로그인 오류)")
                        
                        # 랜덤 브라우징으로 자동 전환
                        print("\n🌐 네이버 랜덤 브라우징을 시작합니다...")
                        중요_작업_로그_저장("재로그인 오류 후 랜덤 브라우징 시작")
                        
                        try:
                            driver.get("https://www.naver.com")
                            time.sleep(random.uniform(2, 3))
                            브라우징_시간 = random.uniform(3, 5)
                            if 네이버_랜덤_브라우징(driver, 브라우징_시간):
                                print("✅ 랜덤 브라우징이 완료되었습니다!")
                                중요_작업_로그_저장("재로그인 오류 후 랜덤 브라우징 완료")
                            else:
                                print("⚠️ 랜덤 브라우징에 실패했지만 블로그 포스팅을 계속 진행합니다.")
                                중요_작업_로그_저장("재로그인 오류 후 랜덤 브라우징 실패하지만 진행")
                        except Exception as browse_e:
                            print(f"⚠️ 랜덤 브라우징 중 오류가 발생했지만 블로그 포스팅을 계속 진행합니다: {browse_e}")
                            중요_작업_로그_저장(f"재로그인 오류 후 랜덤 브라우징 오류하지만 진행: {str(browse_e)}")
                        
                        서로이웃_작업_결과 = False
                
                if 서로이웃_작업_결과 == "본인_이웃수_초과":
                    # 본인의 이웃수 초과: 스프레드시트에 기록하고 브라우징으로 넘어가기
                    print("✅ 본인의 이웃수가 5,000명을 초과하여 서로이웃 작업을 마무리했습니다.")
                    중요_작업_로그_저장("서로이웃 작업 완료 (본인 이웃수 초과로 마무리)")
                    # 서로이웃작업 값 +1 업데이트
                    if 구글스프레드시트_서로이웃작업_업데이트(id):
                        print("✅ 서로이웃작업 값이 업데이트되었습니다.")
                        중요_작업_로그_저장("서로이웃작업 값 업데이트 완료 (본인 이웃수 초과)")
                        서로이웃_작업_업데이트_완료 = True  # 업데이트 완료 표시
                    else:
                        print("⚠️ 서로이웃작업 값 업데이트에 실패했습니다.")
                        오류_로그_저장("서로이웃작업 값 업데이트 실패 (본인 이웃수 초과)")
                    
                    # 브라우징으로 넘어가기
                    print("\n🌐 네이버 랜덤 브라우징을 시작합니다...")
                    중요_작업_로그_저장("본인 이웃수 초과 후 랜덤 브라우징 시작")
                    
                    try:
                        # 네이버 메인 페이지로 이동
                        print("네이버 메인 페이지로 이동합니다...")
                        driver.get("https://www.naver.com")
                        time.sleep(random.uniform(2, 3))
                        
                        # 3-5분 랜덤 브라우징
                        브라우징_시간 = random.uniform(3, 5)  # 3-5분
                        if 네이버_랜덤_브라우징(driver, 브라우징_시간):
                            print("✅ 랜덤 브라우징이 완료되었습니다!")
                            중요_작업_로그_저장("본인 이웃수 초과 후 랜덤 브라우징 완료")
                        else:
                            print("⚠️ 랜덤 브라우징에 실패했지만 블로그 포스팅을 계속 진행합니다.")
                            중요_작업_로그_저장("본인 이웃수 초과 후 랜덤 브라우징 실패하지만 진행")
                    except Exception as e:
                        print(f"⚠️ 랜덤 브라우징 중 오류가 발생했지만 블로그 포스팅을 계속 진행합니다: {e}")
                        중요_작업_로그_저장(f"본인 이웃수 초과 후 랜덤 브라우징 오류하지만 진행: {str(e)}")
                elif 서로이웃_작업_결과 == "드라이버_연결_오류":
                    # 드라이버 연결 오류: 브라우저 재시작하고 다시 로그인
                    print("⚠️ 드라이버 연결 오류가 발생했습니다. 브라우저를 재시작합니다.")
                    중요_작업_로그_저장("드라이버 연결 오류 - 브라우저 재시작")
                    
                    # 브라우저 재시작 전 모든 Chrome 프로세스 강제 종료
                    크롬_프로세스_강제_종료()
                    
                    # 기존 브라우저 종료
                    try:
                        driver.quit()
                        print("기존 브라우저를 종료했습니다.")
                    except:
                        pass
                    
                    # 서로이웃작업 값 +1 업데이트
                    if 구글스프레드시트_서로이웃작업_업데이트(id):
                        print("✅ 서로이웃작업 값이 업데이트되었습니다.")
                        중요_작업_로그_저장("서로이웃작업 값 업데이트 완료 (드라이버 연결 오류)")
                        서로이웃_작업_업데이트_완료 = True  # 업데이트 완료 표시
                    else:
                        print("⚠️ 서로이웃작업 값 업데이트에 실패했습니다.")
                        오류_로그_저장("서로이웃작업 값 업데이트 실패 (드라이버 연결 오류)")
                    
                    # 새로운 브라우저 시작
                    print("\n새로운 브라우저를 시작합니다...")
                    chrome_options = uc_포스팅_크롬_옵션_생성()
                    driver = uc_크롬_드라이버_생성(chrome_options)
                    print("✅ 새로운 브라우저가 시작되었습니다.")
                    
                    # 다시 로그인 시도 (서로이웃 작업은 건너뛰고 바로 브라우징으로)
                    print("다시 로그인을 시도합니다...")
                    # 서로이웃 작업은 이미 완료 처리되었으므로, 로그인만 하고 브라우징으로 넘어감
                    try:
                        # 네이버 로그인 시작
                        driver.get("https://nid.naver.com/nidlogin.login")
                        time.sleep(15)  # 페이지 로딩 대기
                        
                        # IP 보안 설정 확인 및 OFF로 설정
                        try:
                            ip_security_element = driver.find_element(By.CSS_SELECTOR, "#login_keep_wrap > div.ip_check > span > label > span")
                            element_class = ip_security_element.get_attribute("class")
                            
                            if "switch_off" in element_class:
                                print("IP 보안이 이미 OFF 상태입니다.")
                            else:
                                print("IP 보안을 OFF로 설정합니다...")
                                ip_security_element.click()
                                time.sleep(2)
                        except Exception as e:
                            print(f"IP 보안 설정 확인 중 오류 (무시하고 계속): {e}")
                        
                        # 아이디 입력
                        driver.find_element(By.ID, "id").send_keys(id)
                        time.sleep(1)
                        
                        # 비밀번호 입력
                        driver.find_element(By.ID, "pw").send_keys(pw)
                        time.sleep(1)
                        
                        # 로그인 버튼 클릭
                        driver.find_element(By.ID, "log.login").click()
                        time.sleep(5)
                        
                        # 로그인 성공 확인
                        if "nid.naver.com" not in driver.current_url:
                            print("✅ 브라우저 재시작 후 로그인에 성공했습니다!")
                            중요_작업_로그_저장("브라우저 재시작 후 로그인 성공")
                            
                            # 로그인 성공 후 브라우징으로 넘어가기 (서로이웃 작업은 이미 완료 처리됨)
                            print("\n🌐 네이버 랜덤 브라우징을 시작합니다...")
                            중요_작업_로그_저장("드라이버 재시작 후 랜덤 브라우징 시작")
                            
                            try:
                                # 네이버 메인 페이지로 이동
                                print("네이버 메인 페이지로 이동합니다...")
                                driver.get("https://www.naver.com")
                                time.sleep(random.uniform(2, 3))
                                
                                # 3-5분 랜덤 브라우징
                                브라우징_시간 = random.uniform(3, 5)  # 3-5분
                                if 네이버_랜덤_브라우징(driver, 브라우징_시간):
                                    print("✅ 랜덤 브라우징이 완료되었습니다!")
                                    중요_작업_로그_저장("드라이버 재시작 후 랜덤 브라우징 완료")
                                else:
                                    print("⚠️ 랜덤 브라우징에 실패했지만 블로그 포스팅을 계속 진행합니다.")
                                    중요_작업_로그_저장("드라이버 재시작 후 랜덤 브라우징 실패하지만 진행")
                            except Exception as e:
                                print(f"⚠️ 랜덤 브라우징 중 오류가 발생했지만 블로그 포스팅을 계속 진행합니다: {e}")
                                중요_작업_로그_저장(f"드라이버 재시작 후 랜덤 브라우징 오류하지만 진행: {str(e)}")
                        else:
                            print("❌ 브라우저 재시작 후 로그인에 실패했습니다.")
                            중요_작업_로그_저장("브라우저 재시작 후 로그인 실패")
                            return False
                    except Exception as e:
                        print(f"❌ 브라우저 재시작 후 로그인 중 오류 발생: {e}")
                        중요_작업_로그_저장(f"브라우저 재시작 후 로그인 오류: {str(e)}")
                        return False
                elif 서로이웃_작업_결과:
                    print("✅ 서로이웃 작업이 정상적으로 완료되었습니다.")
                    중요_작업_로그_저장("서로이웃 작업 정상 완료")
                    
                    # 서로이웃작업 값 +1 업데이트
                    if 구글스프레드시트_서로이웃작업_업데이트(id):
                        print("✅ 서로이웃작업 값이 업데이트되었습니다.")
                        중요_작업_로그_저장("서로이웃작업 값 업데이트 완료")
                        서로이웃_작업_업데이트_완료 = True  # 업데이트 완료 표시
                    else:
                        print("⚠️ 서로이웃작업 값 업데이트에 실패했습니다.")
                        오류_로그_저장("서로이웃작업 값 업데이트 실패")
                    
                    # 서로이웃 작업 완료 후 랜덤브라우징 진행
                    print("\n🌐 네이버 랜덤 브라우징을 시작합니다...")
                    중요_작업_로그_저장("서로이웃 작업 완료 후 랜덤 브라우징 시작")
                    
                    try:
                        # 네이버 메인 페이지로 이동
                        print("네이버 메인 페이지로 이동합니다...")
                        driver.get("https://www.naver.com")
                        time.sleep(random.uniform(2, 3))
                        
                        # 3-5분 랜덤 브라우징
                        브라우징_시간 = random.uniform(3, 5)  # 3-5분
                        if 네이버_랜덤_브라우징(driver, 브라우징_시간):
                            print("✅ 서로이웃 작업 완료 후 랜덤 브라우징이 완료되었습니다!")
                            중요_작업_로그_저장("서로이웃 작업 완료 후 랜덤 브라우징 완료")
                        else:
                            print("⚠️ 랜덤 브라우징에 실패했지만 블로그 포스팅을 계속 진행합니다.")
                            중요_작업_로그_저장("서로이웃 작업 완료 후 랜덤 브라우징 실패하지만 진행")
                    except Exception as e:
                        print(f"⚠️ 랜덤 브라우징 중 오류가 발생했지만 블로그 포스팅을 계속 진행합니다: {e}")
                        중요_작업_로그_저장(f"서로이웃 작업 완료 후 랜덤 브라우징 오류하지만 진행: {str(e)}")
                else:
                    print("⚠️ 서로이웃 작업에 실패했지만 블로그 포스팅을 계속 진행합니다.")
                    중요_작업_로그_저장("서로이웃 작업 실패하지만 진행")
                    
                    # 서로이웃 작업을 건너뛰고 랜덤브라우징 진행
                    print("\n🌐 네이버 랜덤 브라우징을 시작합니다...")
                    중요_작업_로그_저장("로그인 성공 후 블로그 글쓰기 전 네이버 랜덤 브라우징 시작")
                    
                    try:
                        # 네이버 메인 페이지로 이동
                        print("네이버 메인 페이지로 이동합니다...")
                        driver.get("https://www.naver.com")
                        time.sleep(random.uniform(2, 3))
                        
                        # 3-5분 랜덤 브라우징
                        브라우징_시간 = random.uniform(3, 5)  # 3-5분
                        if 네이버_랜덤_브라우징(driver, 브라우징_시간):
                            print("✅ 로그인 성공 후 랜덤 브라우징이 완료되었습니다!")
                            중요_작업_로그_저장("로그인 성공 후 블로그 글쓰기 전 네이버 랜덤 브라우징 완료")
                        else:
                            print("⚠️ 랜덤 브라우징에 실패했지만 블로그 포스팅을 계속 진행합니다.")
                            중요_작업_로그_저장("로그인 성공 후 랜덤 브라우징 실패하지만 진행")
                    except Exception as e:
                        print(f"⚠️ 랜덤 브라우징 중 오류가 발생했지만 블로그 포스팅을 계속 진행합니다: {e}")
                        중요_작업_로그_저장(f"로그인 성공 후 랜덤 브라우징 오류하지만 진행: {str(e)}")
                        
            except Exception as e:
                print(f"⚠️ 서로이웃 작업 중 오류가 발생했지만 블로그 포스팅을 계속 진행합니다: {e}")
                중요_작업_로그_저장(f"서로이웃 작업 오류하지만 진행: {str(e)}")
                
                # 오류 발생 시 랜덤브라우징 진행
                print("\n🌐 네이버 랜덤 브라우징을 시작합니다...")
                중요_작업_로그_저장("로그인 성공 후 블로그 글쓰기 전 네이버 랜덤 브라우징 시작")
                
                try:
                    # 네이버 메인 페이지로 이동
                    print("네이버 메인 페이지로 이동합니다...")
                    driver.get("https://www.naver.com")
                    time.sleep(random.uniform(2, 3))
                    
                    # 3-5분 랜덤 브라우징
                    브라우징_시간 = random.uniform(3, 5)  # 3-5분
                    if 네이버_랜덤_브라우징(driver, 브라우징_시간):
                        print("✅ 로그인 성공 후 랜덤 브라우징이 완료되었습니다!")
                        중요_작업_로그_저장("로그인 성공 후 블로그 글쓰기 전 네이버 랜덤 브라우징 완료")
                    else:
                        print("⚠️ 랜덤 브라우징에 실패했지만 블로그 포스팅을 계속 진행합니다.")
                        중요_작업_로그_저장("로그인 성공 후 랜덤 브라우징 실패하지만 진행")
                except Exception as e2:
                    print(f"⚠️ 랜덤 브라우징 중 오류가 발생했지만 블로그 포스팅을 계속 진행합니다: {e2}")
                    중요_작업_로그_저장(f"로그인 성공 후 랜덤 브라우징 오류하지만 진행: {str(e2)}")
            
            finally:
                # 서로이웃 작업을 시도했으면 성공/실패와 관계없이 서로이웃작업 값 +1 업데이트
                # 단, 본인 이웃수 초과로 이미 업데이트한 경우는 제외
                if 서로이웃_작업_시도_여부 and not 서로이웃_작업_업데이트_완료:
                    print("\n서로이웃 작업을 시도했으므로 서로이웃작업 값을 +1 업데이트합니다.")
                    if 구글스프레드시트_서로이웃작업_업데이트(id):
                        print("✅ 서로이웃작업 값이 업데이트되었습니다.")
                        중요_작업_로그_저장("서로이웃작업 값 업데이트 완료 (시도 후)")
                    else:
                        print("⚠️ 서로이웃작업 값 업데이트에 실패했습니다.")
                        오류_로그_저장("서로이웃작업 값 업데이트 실패")
        else:
            # 서로이웃작업 값이 1 이상이면 랜덤브라우징 진행
            print(f"\n서로이웃작업 값이 {서로이웃작업_값}이므로 랜덤 브라우징을 진행합니다.")
            중요_작업_로그_저장(f"서로이웃작업 값 확인: {서로이웃작업_값} - 랜덤브라우징 진행")
            
            print("\n🌐 로그인 성공 후 블로그 글쓰기 전 네이버 랜덤 브라우징을 시작합니다...")
            중요_작업_로그_저장("로그인 성공 후 블로그 글쓰기 전 네이버 랜덤 브라우징 시작")
            
            try:
                # 네이버 메인 페이지로 이동
                print("네이버 메인 페이지로 이동합니다...")
                driver.get("https://www.naver.com")
                time.sleep(random.uniform(2, 3))
                
                # 3-5분 랜덤 브라우징
                브라우징_시간 = random.uniform(3, 5)  # 3-5분
                if 네이버_랜덤_브라우징(driver, 브라우징_시간):
                    print("✅ 로그인 성공 후 랜덤 브라우징이 완료되었습니다!")
                    중요_작업_로그_저장("로그인 성공 후 블로그 글쓰기 전 네이버 랜덤 브라우징 완료")
                else:
                    print("⚠️ 랜덤 브라우징에 실패했지만 블로그 포스팅을 계속 진행합니다.")
                    중요_작업_로그_저장("로그인 성공 후 랜덤 브라우징 실패하지만 진행")
            except Exception as e:
                print(f"⚠️ 랜덤 브라우징 중 오류가 발생했지만 블로그 포스팅을 계속 진행합니다: {e}")
                중요_작업_로그_저장(f"로그인 성공 후 랜덤 브라우징 오류하지만 진행: {str(e)}")
        
        
        
        
        # === 블로그 글쓰기 화면으로 이동 전 팝업창 정리 ===
        print("블로그 글쓰기 화면으로 이동하기 전 팝업창들을 정리합니다...")
        중요_작업_로그_저장("블로그 글쓰기 화면 이동 전 팝업창 정리 시작")
        
        try:
            # 현재 페이지에서 열려있는 팝업창들 확인 및 닫기
            팝업창_정리(driver)
            time.sleep(5)
        except Exception as e:
            print(f"팝업창 정리 중 오류 발생: {e}")
            중요_작업_로그_저장(f"팝업창 정리 오류: {str(e)}")
        
        # === 블로그 글쓰기 화면으로 이동 ===
        driver.get("https://blog.naver.com/GoBlogWrite.naver")
        time.sleep(30)
        
        # iframe으로 전환
        driver.switch_to.frame("mainFrame")
        
        # 작성중인 글 취소 버튼
        try:
            cancel_button = driver.find_element(By.CSS_SELECTOR, ".se-popup-button-cancel")
            cancel_button.click()
        except:
            pass
        time.sleep(10)
        
        # 도움말 닫기 버튼
        try:
            help_close_button = driver.find_element(By.CSS_SELECTOR, ".se-help-panel-close-button")
            help_close_button.click()
        except:
            pass
        time.sleep(10)
        
        # === 기본 왼쪽 정렬 설정 ===
        try:
            print("기본 왼쪽 정렬을 설정합니다...")
            time.sleep(2)
            
            # 정렬 버튼 클릭
            align_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-align button")
            align_button.click()
            time.sleep(2)
            print("정렬 메뉴 열기 완료")
            
            # 왼쪽 정렬 버튼 클릭
            center_align_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-option-align-left-button")
            center_align_button.click()
            time.sleep(2)
            print("기본 왼쪽 정렬 완료")
            
        except Exception as e:
            print(f"기본 왼쪽 정렬 중 오류 발생: {e}")
            print("정렬 없이 계속 진행합니다...")
        
        print("블로그 글쓰기 화면 준비가 완료되었습니다.")
        return True
        
    except Exception as e:
        print(f"네이버 로그인 중 오류 발생: {e}")
        # 오류 발생 시 구글 스프레드시트에서 아이디 삭제
        구글스프레드시트_아이디_삭제(id)
        return False

# 전역 변수: 현재 포스팅에서 사용한 API 키 추적
used_api_keys_in_current_posting = []

def 프로그램_완전_재시작(이유="", 대기시간=2):
    """프로그램을 완전히 재시작하기 전에 리소스를 정리하고 같은 터미널에서 다시 실행"""
    try:
        print("\n" + "="*60)
        print("🔄 프로그램 완전 재시작 준비")
        if 이유:
            print(f"재시작 이유: {이유}")
        print("="*60)
        
        중요_작업_로그_저장(f"프로그램 완전 재시작 - 이유: {이유}")
        
        # 1. 전역 변수 초기화
        global used_api_keys_in_current_posting
        used_api_keys_in_current_posting = []
        print("✅ 1. 전역 변수 초기화 완료")
        
        # 2. 임시 파일 정리 (생성된 이미지 파일 등)
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            삭제된_파일_수 = 0
            
            # generated_image_*.png 파일 삭제
            for 파일명 in os.listdir(script_dir):
                if 파일명.startswith('generated_image_') and 파일명.endswith('.png'):
                    try:
                        파일_경로 = os.path.join(script_dir, 파일명)
                        os.remove(파일_경로)
                        삭제된_파일_수 += 1
                    except Exception as e:
                        pass
            
            if 삭제된_파일_수 > 0:
                print(f"✅ 2. 임시 이미지 파일 {삭제된_파일_수}개 삭제 완료")
            else:
                print("✅ 2. 정리할 임시 파일 없음")
        except Exception as e:
            print(f"⚠️ 2. 임시 파일 정리 중 오류 (무시): {e}")
        
        # 3. 메모리 정리 (가비지 컬렉션)
        try:
            import gc
            수집된_객체수 = gc.collect()
            print(f"✅ 3. 가비지 컬렉션 완료 (수집된 객체: {수집된_객체수}개)")
        except Exception as e:
            print(f"⚠️ 3. 가비지 컬렉션 오류 (무시): {e}")
        
        # 4. 크롬 드라이버 정리 (혹시 남아있을 수 있는 프로세스)
        try:
            import subprocess
            subprocess.run('taskkill /f /im chromedriver.exe /t', shell=True, capture_output=True)
            print("✅ 4. 크롬 드라이버 프로세스 정리 완료")
        except:
            print("✅ 4. 크롬 드라이버 프로세스 정리 완료 (없음)")
        
        # 5. 같은 터미널에서 재시작
        print(f"\n같은 터미널에서 프로그램을 다시 시작합니다...")
        if 대기시간 > 0:
            time.sleep(대기시간)
        print("="*60)
        print("현재 터미널에서 포스팅.py를 처음부터 다시 실행합니다.")
        print("="*60)
        프로그램_같은_터미널_재시작(이유 or "완전 재시작")
        
    except Exception as e:
        print(f"❌ 프로그램 재시작 실패: {e}")
        중요_작업_로그_저장(f"프로그램 재시작 실패: {e}")
        import traceback
        traceback.print_exc()
        # 재시작 실패 시에도 종료
        sys.exit(1)

# Gemini API 관리 함수들
def reset_api_key_usage():
    """포스팅 시작 시 사용한 API 키 목록 초기화"""
    global used_api_keys_in_current_posting
    used_api_keys_in_current_posting = []
    print("API 키 사용 기록이 초기화되었습니다.")

def get_api_key_from_excel():
    """엑셀 파일에서 사용량이 가장 적은 API 키를 가져오는 함수"""
    try:
        # _internal 폴더 경로 설정
        if getattr(sys, 'frozen', False):
            # PyInstaller로 빌드된 실행 파일인 경우
            excel_path = os.path.join(sys._MEIPASS, '_internal', '이미지생성.xlsx')
        else:
            # 개발 환경에서 실행하는 경우
            script_dir = os.path.dirname(os.path.abspath(__file__))
            excel_path = os.path.join(script_dir, '_internal', '이미지생성.xlsx')
        
        if not os.path.exists(excel_path):
            print(f"API 키 파일을 찾을 수 없습니다: {excel_path}")
            return None, None
            
        df = pd.read_excel(excel_path)
        # 사용량이 가장 적은 행 찾기 (사용 컬럼 기준)
        min_usage_idx = df['사용'].idxmin()
        api_key = df.loc[min_usage_idx, 'api']
        return api_key, min_usage_idx
    except Exception as e:
        print(f"API 키 가져오기 실패: {e}")
        return None, None

def update_api_usage(row_idx, success=True):
    """API 사용량 업데이트 함수"""
    try:
        # _internal 폴더 경로 설정
        if getattr(sys, 'frozen', False):
            # PyInstaller로 빌드된 실행 파일인 경우
            excel_path = os.path.join(sys._MEIPASS, '_internal', '이미지생성.xlsx')
        else:
            # 개발 환경에서 실행하는 경우
            script_dir = os.path.dirname(os.path.abspath(__file__))
            excel_path = os.path.join(script_dir, '_internal', '이미지생성.xlsx')
        
        df = pd.read_excel(excel_path)
        if success:
            df.loc[row_idx, '사용'] += 1
        else:
            df.loc[row_idx, '실패'] += 1
        df.to_excel(excel_path, index=False)
    except Exception as e:
        print(f"API 사용량 업데이트 실패: {e}")

def get_gemini_client():
    """API 키를 가져와서 Gemini 클라이언트를 생성하는 함수"""
    api_key, row_idx = get_api_key_from_excel()
    if api_key:
        return genai.Client(api_key=api_key), row_idx
    return None, None


def try_generate_with_api(prompt, client, row_idx):
    """특정 API 키로 Imagen 4 Fast로 이미지 생성을 시도하는 함수"""
    try:
        from google.genai import types  # 위에서 이미 import 했다면 이 줄은 제거해도 됨
        from io import BytesIO
        from PIL import Image
        import os
        import time

        # 프롬프트 정리 (불필요한 문자 제거)
        prompt = prompt.strip().strip('"')

        # 텍스트 없는 이미지 생성 지시 추가
        prompt += (
            ", no text, no letters, no words, no characters, no writing, "
            "no watermark, clean image, only picture, without any text or symbols"
        )

        # ✅ Imagen 4 Fast 호출 (generate_content ❌ → generate_images ✅)
        response = client.models.generate_images(
            model="imagen-4.0-fast-generate-001",   # ← 정확한 모델 ID
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,                # 한 장만 생성
                aspect_ratio="16:9",               # 가로세로 비율 고정
            ),
        )

        # 응답 체크
        if not response or not getattr(response, "generated_images", None):
            print("이미지 생성 실패: 응답이 없습니다.")
            return False, None

        generated_image = response.generated_images[0]

        # ✅ 이미지 바이트 꺼내기 (SDK 버전마다 필드명이 조금 다를 수 있어서 방어적으로 처리)
        img_bytes = None
        if hasattr(generated_image, "image_bytes") and generated_image.image_bytes:
            img_bytes = generated_image.image_bytes
        elif hasattr(generated_image, "image") and getattr(generated_image.image, "image_bytes", None):
            img_bytes = generated_image.image.image_bytes

        if not img_bytes:
            print("이미지 생성 실패: 이미지 데이터가 없습니다.")
            return False, None

        # 이미지 디코드 & 저장
        image = Image.open(BytesIO(img_bytes))
        script_dir = os.path.dirname(os.path.abspath(__file__))
        image_path = os.path.join(script_dir, f"generated_image_{int(time.time())}.png")
        image.save(image_path)

        return True, image_path

    except Exception as e:
        print(f"이미지 생성 중 오류 발생: {str(e)}")
        return False, None


def get_all_api_keys():
    """모든 API 키와 인덱스를 가져오는 함수"""
    try:
        # _internal 폴더 경로 설정
        if getattr(sys, 'frozen', False):
            # PyInstaller로 빌드된 실행 파일인 경우
            excel_path = os.path.join(sys._MEIPASS, '_internal', '이미지생성.xlsx')
        else:
            # 개발 환경에서 실행하는 경우
            script_dir = os.path.dirname(os.path.abspath(__file__))
            excel_path = os.path.join(script_dir, '_internal', '이미지생성.xlsx')
        
        if not os.path.exists(excel_path):
            print(f"API 키 파일을 찾을 수 없습니다: {excel_path}")
            return []
            
        df = pd.read_excel(excel_path)
        api_keys = []
        for idx, row in df.iterrows():
            api_keys.append((row['api'], idx))
        return api_keys
    except Exception as e:
        print(f"API 키 목록 가져오기 실패: {e}")
        return []

def generate_image(prompt, retry_count=0, max_retries=0):
    """프롬프트를 받아 이미지를 생성하고 저장하는 함수 (API 키 교체 재시도 포함)"""
    global used_api_keys_in_current_posting
    
    # 프롬프트 정리
    prompt = prompt.strip().strip('"')
    
    # 모든 API 키 가져오기
    api_keys = get_all_api_keys()
    if not api_keys:
        print("사용 가능한 API 키가 없습니다.")
        return None
    
    # 사용량 순으로 정렬 (사용량이 적은 것부터)
    if getattr(sys, 'frozen', False):
        # PyInstaller로 빌드된 실행 파일인 경우
        excel_path = os.path.join(sys._MEIPASS, '_internal', '이미지생성.xlsx')
    else:
        # 개발 환경에서 실행하는 경우
        script_dir = os.path.dirname(os.path.abspath(__file__))
        excel_path = os.path.join(script_dir, '_internal', '이미지생성.xlsx')
    
    try:
        df = pd.read_excel(excel_path)
        sorted_indices = df['사용'].argsort()
        sorted_api_keys = [(api_keys[i][0], api_keys[i][1]) for i in sorted_indices]
    except Exception as e:
        print(f"API 키 정렬 실패: {e}")
        sorted_api_keys = api_keys
    
    # 실행 폴더 정보 출력
    try:
        print(os.getcwd())
        print(os.path.basename(os.getcwd()))
    except Exception as _e:
        pass

    print(f"이미지 생성 시작: '{prompt[:50]}...'")
    print(f"현재 포스팅에서 사용한 API 키: {used_api_keys_in_current_posting}")
    
    # 사용하지 않은 API 키만 필터링
    available_api_keys = []
    for api_key, row_idx in sorted_api_keys:
        if row_idx not in used_api_keys_in_current_posting:
            available_api_keys.append((api_key, row_idx))
    
    # 사용하지 않은 API 키가 없으면 모든 API 키를 다시 사용 가능하게 만들기
    if not available_api_keys:
        print("모든 API 키를 사용했습니다. 처음부터 다시 시도합니다.")
        used_api_keys_in_current_posting = []
        available_api_keys = sorted_api_keys
    
    print(f"사용 가능한 API 키: {len(available_api_keys)}개")
    
    # 각 API 키로 시도 (사용량이 적은 것부터)
    for i, (api_key, row_idx) in enumerate(available_api_keys):
        current_usage = df.loc[row_idx, '사용']
        print(f"API 키 {i+1}/{len(available_api_keys)} 시도 중... (현재 사용량: {current_usage})")
        
        try:
            client = genai.Client(api_key=api_key)
            success, image_path = try_generate_with_api(prompt, client, row_idx)
            
            if success:
                print(f"✅ 이미지 생성 성공! 저장 경로: {image_path}")
                update_api_usage(row_idx, success=True)
                # 사용한 API 키 기록에 추가
                used_api_keys_in_current_posting.append(row_idx)
                return image_path
            else:
                print(f"❌ API 키 {i+1} 실패 (사용량: {current_usage}), 다음 사용량이 적은 API 키로 재시도...")
                update_api_usage(row_idx, success=False)
                # 실패한 API 키도 사용 기록에 추가 (같은 포스팅에서 재시도 방지)
                used_api_keys_in_current_posting.append(row_idx)
                
        except Exception as e:
            print(f"❌ API 키 {i+1} 오류 (사용량: {current_usage}): {str(e)}")
            update_api_usage(row_idx, success=False)
            # 오류가 발생한 API 키도 사용 기록에 추가
            used_api_keys_in_current_posting.append(row_idx)
            continue
    
    # 모든 API 키 실패 시 즉시 종료 (재시도 없음)
    print("❌ 모든 API 키로 시도했지만 이미지 생성에 실패했습니다. 재시도 없이 종료합니다.")
    중요_작업_로그_저장("이미지 생성 최종 실패 - 재시도 없음 정책 적용")
    return None

def 이미지를_GIF로_변환(입력_이미지_경로, 출력_GIF_경로=None, 품질=85, 최적화=True):
    """이미지 파일을 GIF 형식으로 변환하는 함수
    
    Args:
        입력_이미지_경로 (str): 변환할 원본 이미지 파일 경로 (jpg, png 등)
        출력_GIF_경로 (str, optional): 저장할 GIF 파일 경로. None이면 자동 생성
        품질 (int): GIF 품질 (1-100, 기본값 85)
        최적화 (bool): 파일 크기 최적화 여부 (기본값 True)
    
    Returns:
        str: 생성된 GIF 파일 경로, 실패 시 None
    """
    try:
        from PIL import Image, ImageOps
        import os
        
        # 입력 파일 존재 확인
        if not os.path.exists(입력_이미지_경로):
            print(f"❌ 오류: 입력 파일을 찾을 수 없습니다: {입력_이미지_경로}")
            return None
        
        # 출력 경로 설정
        if 출력_GIF_경로 is None:
            파일명, _ = os.path.splitext(입력_이미지_경로)
            출력_GIF_경로 = f"{파일명}.gif"
        
        print(f"🔄 이미지를 GIF로 변환 중: {os.path.basename(입력_이미지_경로)}")
        
        # 이미지 열기
        이미지 = Image.open(입력_이미지_경로)
        try:
            이미지 = ImageOps.exif_transpose(이미지)
        except Exception:
            pass

        # RGBA 모드를 RGB로 변환 (GIF는 RGB 또는 P 모드 지원)
        if 이미지.mode in ('RGBA', 'LA', 'P'):
            # 투명 배경을 흰색으로 변환
            배경 = Image.new('RGB', 이미지.size, (255, 255, 255))
            if 이미지.mode == 'P':
                이미지 = 이미지.convert('RGBA')
            배경.paste(이미지, mask=이미지.split()[-1] if 이미지.mode == 'RGBA' else None)
            이미지 = 배경
        elif 이미지.mode != 'RGB':
            이미지 = 이미지.convert('RGB')
        
        # GIF로 저장
        이미지.save(
            출력_GIF_경로,
            'GIF',
            optimize=최적화,
            quality=품질
        )
        
        print(f"✅ GIF 변환 완료: {os.path.basename(출력_GIF_경로)}")
        return 출력_GIF_경로
        
    except Exception as e:
        print(f"❌ GIF 변환 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None

def process_markdown_file(file_path):
    """마크다운 파일을 읽고 처리하는 함수"""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    title = lines[0].strip('# \n')
    content = []
    current_section = []
    
    for line in lines[1:]:
        if line.startswith('##'):
            if current_section:
                content.append(('text', current_section))
                current_section = []
            # 'quote'에는 반드시 ##로 시작하는 행의 텍스트만(앞뒤 공백 및 빈 줄 제거)
            quote_text = line.strip('# \n').strip()
            content.append(('quote', quote_text))
        elif line.startswith('[이미지]'):
            if current_section:
                content.append(('text', current_section))
                current_section = []
            # 이미지 프롬프트에서 실제 프롬프트만 추출
            prompt = line.replace('[이미지]', '').strip()
            content.append(('image', prompt))
        else:
            # "Image generation prompt:" 같은 설명 텍스트는 자동으로 생략
            if 'Image generation prompt:' in line:
                print(f"설명 텍스트 생략: {line.strip()}")
                continue
            
            # 이미지 프롬프트는 반드시 별도 줄에 있어야 하므로, 섹션 내용과 같은 줄에 있는 경우는 무시
            # 이미지 프롬프트가 섹션글과 같은 행에 있는 경우 경고 메시지 출력
            if '[이미지]' in line:
                print(f"경고: 이미지 프롬프트가 섹션 내용과 같은 줄에 있습니다. 별도 줄로 분리해야 합니다: {line.strip()}")
                continue
            
            # 빈 줄 처리 (소문단 사이의 빈 줄)
            if line.strip() == '':
                # 빈 줄은 추가 Enter로 처리 (빈 줄 생성)
                current_section.append(('text', '\n'))
                continue
            
            # 한 글자씩 처리
            i = 0
            is_bold = False
            current_text = ''
            while i < len(line):
                if i < len(line) - 1 and line[i:i+2] == '**':
                    # **를 만나면 현재까지의 텍스트를 추가하고 상태 변경
                    if current_text:
                        current_section.append(('text' if not is_bold else 'bold', current_text))
                        current_text = ''
                    is_bold = not is_bold
                    i += 2
                else:
                    current_text += line[i]
                    i += 1
            
            # 마지막 텍스트 추가
            if current_text:
                current_section.append(('text' if not is_bold else 'bold', current_text.rstrip()))
            
            # 줄바꿈 추가 (마지막 텍스트가 있을 때만)
            if current_text.strip():
                current_section.append(('text', '\n'))
    
    if current_section:
        content.append(('text', current_section))
    
    return title, content

def write_to_naver_blog(driver, title, content, promo_text=None, hananoran=None, account_index=None, 아이디=None):
    """네이버 블로그에 글을 작성하는 함수 (홍보문구, 하나노란 이미지 추가)"""
    # driver는 이미 로그인 및 글쓰기 진입, 팝업/도움말 닫기까지 완료된 상태로 전달됨
    # 이하 기존 본문 입력, 저장 등 로직 유지
    
    # 블로그 포스팅 시작 로그
    중요_작업_로그_저장(f"블로그 포스팅 시작: 제목={title}, 하나노란={hananoran}")
    현재_추천모델 = _추천모델_가져오기(title)
    if 현재_추천모델:
        print(f"이미지 선택용 추천모델: {현재_추천모델}")
    
    # === 포스팅 시작 시 API 키 사용 기록 초기화 ===
    reset_api_key_usage()
    
    # 창이 닫혔는지 확인
    try:
        driver.current_url
    except Exception as e:
        print(f"오류: 크롬 창이 이미 닫혔습니다. {e}")
        return False

    # 인용구 스타일 무작위 1개 선택(글 전체에서 동일하게 사용)
    quotation_styles = [
        (".se-toolbar-option-insert-quotation-default-button", "[인용구 1] "),
        (".se-toolbar-option-insert-quotation-quotation_line-button", "[인용구 2] "),
        (".se-toolbar-option-insert-quotation-quotation_bubble-button", "[인용구 3] "),
        (".se-toolbar-option-insert-quotation-quotation_underline-button", "[인용구 4] "),
        (".se-toolbar-option-insert-quotation-quotation_postit-button", "[인용구 5] "),
        (".se-toolbar-option-insert-quotation-quotation_corner-button", "[인용구 6] "),
    ]
    selected_style_selector, selected_prefix = random.choice(quotation_styles)

    # 제목 입력
    try:
        title_element = driver.find_element(By.CSS_SELECTOR, ".se-section-documentTitle")
        title_element.click()
        actions = ActionChains(driver)
        actions.send_keys(title)
        actions.send_keys(Keys.ENTER)
        actions.perform()
        time.sleep(10)
    except Exception as e:
        print(f"제목 입력 중 오류 발생: {e}")
        return False
    
    # === 제목 입력 후, 본문 입력 직전에 랜덤 이미지 삽입 ===
    try:
        import pyautogui
        상단_이미지_폴더 = resource_path("img")
        
        if os.path.exists(상단_이미지_폴더):
            # 사용하지 않은 이미지만 선택 (중복 방지)
            선택된_이미지 = 사용하지_않은_이미지_선택(상단_이미지_폴더, "img")
            
            if 선택된_이미지:
                원본_이미지_경로 = os.path.join(상단_이미지_폴더, 선택된_이미지)
                
                print(f"상단 이미지 선택: {선택된_이미지}")
                작업_로그_저장(f"상단 이미지 선택: {선택된_이미지}")
                
                # 이미지 중복 방지 처리
                처리된_이미지_경로 = 이미지_업로드_전_처리(원본_이미지_경로)
                
                # 이미지 삽입
                image_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-image")
                image_button.click()
                time.sleep(5)
                pyautogui.press('esc')
                time.sleep(3)
                image_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-image")
                image_button.click()
                time.sleep(10)  # 파일 선택 대화상자 열림 대기
                
                # 파일 선택 대화상자 강제 활성화
                import pygetwindow as gw
                try:
                    # "열기" 창 찾기
                    windows = gw.getWindowsWithTitle('열기')
                    if windows:
                        windows[0].activate()
                        time.sleep(0.5)
                except:
                    pass
                
                # 파일 선택 대화상자의 파일명 입력란 활성화
                pyautogui.hotkey('alt', 'n')  # 파일명 입력란으로 포커스 (Alt+N)
                time.sleep(1)
                
                pyperclip.copy(os.path.abspath(처리된_이미지_경로))
                pyautogui.hotkey('ctrl', 'v')
                time.sleep(10)
                pyautogui.press('enter')
                time.sleep(30)
                
                print(f"상단 이미지 삽입 완료: {선택된_이미지}")
                작업_로그_저장(f"상단 이미지 삽입 완료: {선택된_이미지}")
                
                # 처리된 이미지 파일 삭제 (_modified 파일)
                if 처리된_이미지_경로 != 원본_이미지_경로 and os.path.exists(처리된_이미지_경로):
                    try:
                        os.remove(처리된_이미지_경로)
                    except:
                        pass
            else:
                print("상단 이미지 폴더에 사용 가능한 이미지가 없습니다.")
        else:
            print(f"상단 이미지 폴더가 존재하지 않습니다: {상단_이미지_폴더}")
    except Exception as e:
        print(f"상단 이미지 삽입 중 오류: {e}")
        오류_로그_저장(f"상단 이미지 삽입 중 오류: {e}")
    
    # 본문 입력
    # 마지막 이미지 인덱스 찾기 (GIF 변환용)
    마지막_이미지_인덱스 = None
    for idx, (content_type, _) in enumerate(content):
        if content_type == 'image':
            마지막_이미지_인덱스 = idx
    
    본문_이미지_순번 = 0
    for idx, (content_type, content_text) in enumerate(content):
        # 각 단계마다 창이 닫혔는지 확인
        try:
            driver.current_url
        except Exception as e:
            print(f"본문 입력 중 창이 닫힘: {e}")
            return False
            
        if content_type == 'text':
            for part in content_text:
                try:
                    actions = ActionChains(driver)
                    if isinstance(part, tuple):
                        part_type, part_text = part
                        if part_type == 'text':
                            for char in part_text:
                                actions = ActionChains(driver)
                                actions.send_keys(char)
                                actions.perform()
                                time.sleep(random.uniform(0.3, 0.5))  # 0.05~0.1초 랜덤 딜레이
                        elif part_type == 'bold':
                            bold_button = driver.find_element(By.CSS_SELECTOR, ".se-bold-toolbar-button")
                            bold_button.click()
                            time.sleep(0.2)
                            actions = ActionChains(driver)
                            actions.send_keys(part_text)
                            actions.perform()
                            time.sleep(0.2)
                            bold_button.click()
                            time.sleep(0.2)
                        elif part_type == 'text' and part_text == '\n':
                            actions.send_keys(Keys.ENTER)
                            actions.perform()
                    time.sleep(0.2)
                except Exception as e:
                    print(f"본문 텍스트 입력 중 오류: {e}")
                    return False
        
        elif content_type == 'quote':
            # 인용구 삽입: 반드시 str만 입력, 빈 문자열은 제외
            if isinstance(content_text, str) and content_text.strip():
                try:
                    quotation_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-insert-quotation .se-document-toolbar-select-option-button")
                    quotation_button.click()
                    time.sleep(5)
                    quotation_option = driver.find_element(By.CSS_SELECTOR, selected_style_selector)
                    quotation_option.click()
                    time.sleep(5)
                    actions = ActionChains(driver)
                    actions.send_keys(content_text)
                    actions.pause(2)
                    actions.send_keys(Keys.ARROW_DOWN)
                    actions.pause(2)
                    actions.send_keys(Keys.ARROW_DOWN)
                    actions.pause(2)
                    actions.send_keys(Keys.ENTER)
                    actions.perform()
                    time.sleep(2)
                except Exception as e:
                    print(f"인용구 삽입 중 오류: {e}")
                    return False

        elif content_type == 'image':
            # 마지막 이미지인지 확인
            is_last_image = (idx == 마지막_이미지_인덱스)
            본문_이미지_순번 += 1
            folder_2번_사용 = False
            folder_2번_세트 = None
            image_path = None

            # 2번째 이미지(본문 첫 이미지): 노란우산렌탈 계열은 무조건 2번이미지 3장 세트
            if 본문_이미지_순번 == 1:
                사용_하나노란_2 = _작업_하나노란_값(hananoran)
                if _2번이미지_3장_대상_하나노란(사용_하나노란_2):
                    folder_2번_세트 = _2번이미지_세트_선택()
                    if folder_2번_세트:
                        folder_2번_사용 = True
                        print('2번째 이미지: 2번이미지 3장 세트 사용 (노란우산렌탈)')
                        작업_로그_저장(
                            f"2번째 이미지 2번이미지 3장 세트: {', '.join(os.path.basename(p) for p in folder_2번_세트)}"
                        )
                    else:
                        print('2번째 이미지: 2번이미지 세트 선택 실패 -> AI 생성으로 진행')

            if folder_2번_사용 and folder_2번_세트:
                try:
                    folder_2번_세트 = _2번이미지_세트_순서_정렬(folder_2번_세트)
                    처리된_세트_경로 = []
                    for 원본_경로 in folder_2번_세트:
                        처리된_세트_경로.append(이미지_업로드_전_처리(원본_경로))
                    첨부_경로_목록 = _2번이미지_세트_첨부_순서(처리된_세트_경로)
                    첨부_문자열 = _파일선택_입력_문자열(첨부_경로_목록)
                    print(
                        '2번이미지 첨부 순서(1->2->3): '
                        + ' -> '.join(os.path.basename(p) for p in 첨부_경로_목록)
                    )
                    작업_로그_저장(f'2번이미지 첨부 문자열: {첨부_문자열}')
                    _블로그_이미지_파일선택_삽입(driver, 첨부_경로_목록, 첨부_문자열=첨부_문자열)
                    print(f"2번이미지 3장 삽입 완료: {첨부_문자열}")
                    for 원본_경로, 처리_경로 in zip(folder_2번_세트, 처리된_세트_경로):
                        if 처리_경로 != 원본_경로 and os.path.exists(처리_경로):
                            try:
                                os.remove(처리_경로)
                            except Exception:
                                pass
                except Exception as e:
                    print(f'2번이미지 3장 삽입 오류: {e}')
                    오류_로그_저장(f'2번이미지 3장 삽입 오류: {e}')
                continue

            if not image_path:
                image_path = generate_image(content_text)
            
            # 마지막 이미지이고 생성에 성공했으면 GIF로 변환
            if is_last_image and image_path:
                print(f"🎬 마지막 이미지를 GIF로 변환합니다...")
                gif_path = 이미지를_GIF로_변환(image_path)
                if gif_path and os.path.exists(gif_path):
                    # 원본 대신 GIF 사용
                    print(f"✅ GIF 변환 성공. GIF 파일을 사용합니다: {os.path.basename(gif_path)}")
                    image_path = gif_path
                else:
                    print(f"⚠️ GIF 변환 실패. 원본 이미지를 사용합니다.")
            
            if image_path:
                time.sleep(10)  # 이미지 준비 후 대기
                try:
                    image_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-image")
                    image_button.click()
                    time.sleep(10)  # 파일 선택 대화상자 열림 대기
                    
                    # 파일 선택 대화상자 강제 활성화
                    import pygetwindow as gw
                    try:
                        # "열기" 창 찾기
                        windows = gw.getWindowsWithTitle('열기')
                        if windows:
                            windows[0].activate()
                            time.sleep(0.5)
                    except:
                        pass
                    
                    # 파일 선택 대화상자의 파일명 입력란 활성화
                    pyautogui.hotkey('alt', 'n')  # 파일명 입력란으로 포커스 (Alt+N)
                    time.sleep(1)

                    pyperclip.copy(os.path.abspath(image_path))
                    pyautogui.hotkey('ctrl', 'v')
                    time.sleep(10)
                    pyautogui.press('enter')
                    time.sleep(30)
                    
                    if not folder_2번_사용:
                        # 생성된 이미지 파일을 삭제하지 않고 img2/img3 폴더로 번갈아 이동
                        try:
                            import shutil
                            script_dir = os.path.dirname(os.path.abspath(__file__))
                            
                            # 다음 사용할 폴더 선택 (img2와 img3 번갈아 사용)
                            selected_folder = 다음_이미지_폴더_선택()
                            img_dir = os.path.join(script_dir, selected_folder)
                            os.makedirs(img_dir, exist_ok=True)
                            
                            base_name = os.path.basename(image_path)
                            target_path = os.path.join(img_dir, base_name)
                            # 동일 파일명이 있을 경우 타임스탬프를 덧붙여 충돌 회피
                            if os.path.exists(target_path):
                                name, ext = os.path.splitext(base_name)
                                target_path = os.path.join(img_dir, f"{name}_{int(time.time())}{ext}")
                            shutil.move(image_path, target_path)
                            print(f"생성 이미지 보관: {selected_folder}/{os.path.basename(target_path)}")
                        except Exception as move_e:
                            print(f"생성 이미지 이동 실패(삭제하지 않음): {move_e}")
                except Exception as e:
                    print(f"이미지 삽입 중 오류 발생: {str(e)}")
            else:
                print(f"이미지 생성 실패: {content_text}")
                # 폴백: img2/img3 폴더에서 번갈아가며 랜덤 이미지 선택 → 중복회피 처리 후 삽입
                try:
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    
                    selected_folder = 다음_이미지_폴더_선택()
                    img_dir, record_folder = _img_폴더_해석(selected_folder, 현재_추천모델)
                    
                    if not os.path.exists(img_dir):
                        other_folder = "img3" if selected_folder == "img2" else "img2"
                        print(f"{selected_folder} 폴더가 없어 {other_folder} 폴더를 사용합니다.")
                        img_dir, record_folder = _img_폴더_해석(other_folder, 현재_추천모델)
                        selected_folder = other_folder
                    
                    if os.path.exists(img_dir):
                        대체_파일 = 사용하지_않은_이미지_선택(img_dir, record_folder)
                        if 대체_파일:
                            대체_경로 = os.path.join(img_dir, 대체_파일)
                            처리된_대체_경로 = 이미지_업로드_전_처리(대체_경로)
                            
                            # 마지막 이미지면 GIF로 변환
                            if is_last_image:
                                print(f"🎬 폴백 이미지(마지막, 중복회피 처리됨)를 GIF로 변환합니다...")
                                gif_path = 이미지를_GIF로_변환(처리된_대체_경로)
                                if gif_path and os.path.exists(gif_path):
                                    print(f"✅ GIF 변환 성공. GIF 파일을 사용합니다: {os.path.basename(gif_path)}")
                                    # 기존 처리된 파일 삭제 (GIF가 아닌 경우)
                                    if 처리된_대체_경로 != 대체_경로 and os.path.exists(처리된_대체_경로):
                                        try:
                                            os.remove(처리된_대체_경로)
                                            print(f"중복회피 처리된 임시 파일 삭제: {os.path.basename(처리된_대체_경로)}")
                                        except:
                                            pass
                                    처리된_대체_경로 = gif_path
                                else:
                                    print(f"⚠️ GIF 변환 실패. 중복회피 처리된 원본 이미지를 사용합니다.")

                            image_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-image")
                            image_button.click()
                            time.sleep(10)  # 파일 선택 대화상자 열림 대기

                            # 파일 선택 대화상자 강제 활성화
                            import pygetwindow as gw
                            try:
                                windows = gw.getWindowsWithTitle('열기')
                                if windows:
                                    windows[0].activate()
                                    time.sleep(0.5)
                            except:
                                pass

                            # 파일 선택 대화상자의 파일명 입력란 활성화
                            pyautogui.hotkey('alt', 'n')  # 파일명 입력란으로 포커스 (Alt+N)
                            time.sleep(1)

                            pyperclip.copy(os.path.abspath(처리된_대체_경로))
                            pyautogui.hotkey('ctrl', 'v')
                            time.sleep(10)
                            pyautogui.press('enter')
                            time.sleep(30)

                            # 처리된 임시 파일은 원본과 다르면 삭제
                            if 처리된_대체_경로 != 대체_경로 and os.path.exists(처리된_대체_경로):
                                try:
                                    os.remove(처리된_대체_경로)
                                except:
                                    pass

                            print(f"이미지 생성 실패 폴백: {record_folder}/{대체_파일} 삽입 완료")
                        else:
                            print(f"폴백 실패: {record_folder} 폴더에 사용 가능한 이미지가 없습니다.")
                    else:
                        print(f"폴백 실패: img2, img3 폴더가 모두 존재하지 않습니다.")
                except Exception as fb_e:
                    print(f"폴백 이미지 삽입 중 오류: {fb_e}")
                # 다음 섹션으로 계속 진행
                continue

    # === 본문 입력 완료 후, 하나노란2 폴더에서 이미지 삽입 ===
    사용할_하나노란_2 = _작업_하나노란_값(hananoran)
    if 사용할_하나노란_2:
        last_image_path = _하나노란2_이미지_선택(사용할_하나노란_2)
        if last_image_path:
            print(f"하나노란2/{사용할_하나노란_2} -> 삽입: {last_image_path}")
    else:
        last_image_path = None
        print("하나노란 값이 없어서 하나노란2 이미지를 삽입하지 않습니다.")
    
    if last_image_path and os.path.exists(last_image_path):
        try:
            # 이미지 중복 방지 처리
            처리된_이미지_경로 = 이미지_업로드_전_처리(last_image_path)
            time.sleep(10)  # 이미지 처리 완료 후 대기
            
            image_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-image")
            image_button.click()
            time.sleep(5)
            pyautogui.press('esc')
            time.sleep(3)
            image_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-image")
            image_button.click()
            time.sleep(10)  # 파일 선택 대화상자 열림 대기
            
            # 파일 선택 대화상자 강제 활성화
            import pygetwindow as gw
            try:
                # "열기" 창 찾기
                windows = gw.getWindowsWithTitle('열기')
                if windows:
                    windows[0].activate()
                    time.sleep(0.5)
            except:
                pass
            
            # 파일 선택 대화상자의 파일명 입력란 활성화
            pyautogui.hotkey('alt', 'n')  # 파일명 입력란으로 포커스 (Alt+N)
            time.sleep(1)
            
            pyperclip.copy(os.path.abspath(처리된_이미지_경로))
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(10)
            pyautogui.press('enter')
            time.sleep(30)
            
            # 처리된 이미지 파일 삭제 (_modified 파일)
            if 처리된_이미지_경로 != last_image_path and os.path.exists(처리된_이미지_경로):
                try:
                    os.remove(처리된_이미지_경로)
                except:
                    pass
        except Exception as e:
            print(f"본문 마지막 이미지 삽입 오류: {str(e)}")

    # === 본문 마지막 이미지 삽입 후 연관어.txt 파일 내용 추가 ===

    # 홍보문구 입력 (연관어 삽입 전)
    if promo_text:
        pyautogui.press('enter')
        time.sleep(0.3)
        try:
            align_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-align button")
            align_button.click()
            time.sleep(1)
            center_align_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-option-align-center-button")
            center_align_button.click()
            time.sleep(1)
            print("홍보문구 가운데 정렬 완료")
        except Exception as e:
            print(f"홍보문구 가운데 정렬 중 오류: {e}")
        pyperclip.copy(promo_text)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(1)
        pyautogui.press('enter')
        time.sleep(0.3)
        pyautogui.press('enter')
        time.sleep(5)

    # 연관어 삽입 전 랜덤 휴식 (245초~648초)
    휴식_시간 = random.randint(245, 648)
    print(f"연관어 삽입 전 {휴식_시간}초 휴식을 시작합니다...")
    time.sleep(휴식_시간)
    print(f"{휴식_시간}초 휴식이 완료되었습니다. 연관어 삽입을 시작합니다.")
    
    try:
        with open(resource_path('연관어.txt'), 'r', encoding='utf-8') as f:
            related_words = f.read().strip()
        if related_words:
            related_lines = related_words.split('\n')
            formatted_related_words = []
            for line in related_lines:
                line = line.strip()
                if line and line.startswith('#'):
                    formatted_related_words.append(line)
            if formatted_related_words:
                for word in formatted_related_words:
                    actions = ActionChains(driver)
                    actions.send_keys(word)
                    actions.send_keys(Keys.ENTER)
                    actions.perform()
                    time.sleep(5)
                print("연관어가 성공적으로 추가되었습니다!")
            else:
                print("연관어.txt 파일에 유효한 내용이 없습니다.")
    except Exception as e:
        print(f"연관어 추가 중 오류 발생: {str(e)}")

    # === 연관어 추가 후 홍보.png 이미지 삽입 ===
    try:
        홍보_이미지_경로 = resource_path('홍보.png')
        if os.path.exists(홍보_이미지_경로):
            print("홍보.png 이미지 삽입을 시작합니다...")
            작업_로그_저장("홍보.png 이미지 삽입 시작")
            
            # 이미지 중복 회피 전처리 적용
            처리된_홍보_이미지_경로 = 이미지_업로드_전_처리(홍보_이미지_경로)
            
            # 이미지 삽입
            image_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-image")
            image_button.click()
            time.sleep(5)
            pyautogui.press('esc')
            time.sleep(3)
            image_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-image")
            image_button.click()
            time.sleep(10)  # 파일 선택 대화상자 열림 대기
            
            # 파일 선택 대화상자 강제 활성화
            import pygetwindow as gw
            try:
                windows = gw.getWindowsWithTitle('열기')
                if windows:
                    windows[0].activate()
                    time.sleep(0.5)
            except:
                pass
            
            # 파일 선택 대화상자의 파일명 입력란 활성화
            pyautogui.hotkey('alt', 'n')  # 파일명 입력란으로 포커스 (Alt+N)
            time.sleep(1)
            
            # 파일 경로 복사 및 붙여넣기
            pyperclip.copy(os.path.abspath(처리된_홍보_이미지_경로))
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(10)
            pyautogui.press('enter')
            time.sleep(30)  # 이미지 업로드 대기
            
            print(f"홍보.png 이미지 삽입 완료: {os.path.basename(처리된_홍보_이미지_경로)}")
            작업_로그_저장(f"홍보.png 이미지 삽입 완료: {os.path.basename(처리된_홍보_이미지_경로)}")
            
            # 처리된 이미지가 원본과 다르면 임시 파일 삭제
            if 처리된_홍보_이미지_경로 != 홍보_이미지_경로 and os.path.exists(처리된_홍보_이미지_경로):
                try:
                    os.remove(처리된_홍보_이미지_경로)
                    print(f"임시 처리 파일 삭제: {os.path.basename(처리된_홍보_이미지_경로)}")
                except Exception as e:
                    print(f"임시 파일 삭제 중 오류: {e}")
        else:
            print("홍보.png 파일을 찾을 수 없습니다. 생략하고 계속 진행합니다.")
    except Exception as e:
        print(f"홍보.png 이미지 삽입 중 오류 발생: {str(e)}")
        오류_로그_저장(f"홍보.png 이미지 삽입 중 오류: {e}")

    # === 본문 입력 후 발행 전 추가 작업 ===
    # 1. 제목 입력란(placeholder가 '제목'인 곳)으로 커서 이동
    try:
        title_element = driver.find_element(By.CSS_SELECTOR, ".se-section-documentTitle")
        title_element.click()
        time.sleep(0.5)
        pyautogui.press('home')  # 제목 맨 앞 위치로 이동
        time.sleep(1)
        pyautogui.press('down')  # 방향키 아래로 한 번
        time.sleep(1)
        pyautogui.press('home') #홈키 누르고
        time.sleep(1)
        pyautogui.press('enter')  # 엔터 한 번
        time.sleep(1)
        pyautogui.press('up')    # 방향키 위로 한 번
    except Exception as e:
        print("제목 입력란 클릭 실패:", e)

    # === 하나노란 값에 따라 1번이미지 폴더에서 이미지 삽입 ===
    지명_하나노란_값_1 = None
    try:
        지명키워드_df = 지명키워드_df_가져오기()
        if not 지명키워드_df.empty and '하나노란' in 지명키워드_df.columns:
            지명_하나노란_값_1 = str(지명키워드_df.iloc[0]['하나노란']).strip()
            if 지명_하나노란_값_1 == 'nan':
                지명_하나노란_값_1 = ""
            print(f"작업큐 캐시에서 가져온 하나노란 값 (1번이미지): {지명_하나노란_값_1}")
        else:
            print("작업큐 캐시가 비어있거나 하나노란 컬럼이 없습니다.")
    except Exception as e:
        print(f"작업큐 캐시 읽기 중 오류 (1번이미지): {e}")

    사용할_하나노란_1 = 지명_하나노란_값_1 if 지명_하나노란_값_1 and 지명_하나노란_값_1 != 'nan' else None

    if 사용할_하나노란_1:
        image_path = _하나노란1_이미지_선택(사용할_하나노란_1)
        if image_path:
            print(f"1번이미지/{사용할_하나노란_1} -> 삽입: {image_path}")
    else:
        image_path = None
        print("하나노란 값이 없어서 1번이미지 삽입을 건너뜁니다.")
    if image_path and os.path.exists(image_path):
        try:
            # 이미지 중복 방지 처리
            처리된_이미지_경로 = 이미지_업로드_전_처리(image_path)
            time.sleep(10)  # 이미지 처리 완료 후 대기

            image_button = driver.find_element(By.CSS_SELECTOR, ".se-toolbar-item-image")
            image_button.click()
            time.sleep(10)  # 파일 선택 대화상자 열림 대기

            # 파일 선택 대화상자 강제 활성화
            import pygetwindow as gw
            try:
                windows = gw.getWindowsWithTitle('열기')
                if windows:
                    windows[0].activate()
                    time.sleep(0.5)
            except:
                pass

            # 파일 선택 대화상자의 파일명 입력란 활성화
            pyautogui.hotkey('alt', 'n')  # 파일명 입력란으로 포커스 (Alt+N)
            time.sleep(1)

            pyperclip.copy(os.path.abspath(처리된_이미지_경로))
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(10)
            pyautogui.press('enter')
            time.sleep(30)

            print(f"1번이미지 삽입 완료: {os.path.basename(image_path)}")
            작업_로그_저장(f"1번이미지 삽입 완료: {os.path.basename(image_path)} ({사용할_하나노란_1})")

            # 처리된 이미지 파일 삭제 (_modified 파일)
            if 처리된_이미지_경로 != image_path and os.path.exists(처리된_이미지_경로):
                try:
                    os.remove(처리된_이미지_경로)
                except:
                    pass
        except Exception as e:
            print(f"1번이미지 삽입 오류: {str(e)}")
            오류_로그_저장(f"1번이미지 삽입 오류: {e}")
    elif 사용할_하나노란_1:
        print(f"1번이미지/{사용할_하나노란_1} 에서 사용할 이미지를 찾지 못했습니다.")


    time.sleep(10)

    # 2. 엔터 2번, 2초 대기
    pyautogui.press('enter')
    pyautogui.press('enter')

    # === 모든 글 작성 및 이미지 삽입이 끝난 후에 발행 버튼 클릭 ===
    publish_button = driver.find_element(By.CSS_SELECTOR, ".publish_btn__m9KHH")
    publish_button.click()
    time.sleep(30)
    
    # 카테고리 버튼 클릭 (카테고리 컬럼에 값이 있는 아이디만)
    if 아이디:
        try:
            # 계정정보 스프레드시트에서 카테고리 값 확인
            계정정보_df = 구글스프레드시트_계정정보_가져오기()
            if not 계정정보_df.empty and '카테고리' in 계정정보_df.columns:
                아이디_정보 = 계정정보_df[계정정보_df['아이디'] == 아이디]
                if len(아이디_정보) > 0:
                    카테고리_값 = str(아이디_정보.iloc[0]['카테고리']).strip()
                    if 카테고리_값 and 카테고리_값.lower() not in ['', 'nan', 'none', '없음']:
                        try:
                            # 카테고리 버튼 클릭
                            category_button = driver.find_element(By.CSS_SELECTOR, "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.option_category___kpJc > div > div > button > span")
                            category_button.click()
                            print(f"카테고리 버튼 클릭 완료 (아이디: {아이디}, 카테고리: {카테고리_값})")
                            time.sleep(3)
                            
                            # 스프레드시트에서 가져온 카테고리 값으로 요소 찾기 및 클릭
                            카테고리_클릭_성공 = False
                            
                            # 방법 1: XPath로 텍스트 직접 찾기
                            try:
                                카테고리_요소 = driver.find_element(By.XPATH, f"//span[contains(@class, 'text__sraQE') and text()='{카테고리_값}']")
                                # 요소가 보이도록 스크롤
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", 카테고리_요소)
                                time.sleep(1)
                                카테고리_요소.click()
                                print(f"'{카테고리_값}' 카테고리 클릭 완료 (XPath 텍스트 방식)")
                                카테고리_클릭_성공 = True
                            except:
                                pass
                            
                            # 방법 2: data-testid 속성으로 찾기 (categoryItemText_로 시작하는 모든 요소 확인)
                            if not 카테고리_클릭_성공:
                                try:
                                    # data-testid가 categoryItemText_로 시작하는 모든 요소 찾기
                                    카테고리_요소들 = driver.find_elements(By.CSS_SELECTOR, "[data-testid^='categoryItemText_']")
                                    for 요소 in 카테고리_요소들:
                                        if 요소.text.strip() == 카테고리_값:
                                            # 요소가 보이도록 스크롤
                                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", 요소)
                                            time.sleep(1)
                                            요소.click()
                                            print(f"'{카테고리_값}' 카테고리 클릭 완료 (data-testid 방식)")
                                            카테고리_클릭_성공 = True
                                            break
                                except Exception as e:
                                    print(f"data-testid 방식으로 찾기 실패: {e}")
                            
                            # 방법 3: 모든 span 요소에서 텍스트로 찾기
                            if not 카테고리_클릭_성공:
                                try:
                                    모든_span = driver.find_elements(By.TAG_NAME, "span")
                                    for span in 모든_span:
                                        if span.text.strip() == 카테고리_값:
                                            # 요소가 보이도록 스크롤
                                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", span)
                                            time.sleep(1)
                                            span.click()
                                            print(f"'{카테고리_값}' 카테고리 클릭 완료 (모든 span 검색 방식)")
                                            카테고리_클릭_성공 = True
                                            break
                                except Exception as e:
                                    print(f"모든 span 검색 방식 실패: {e}")
                            
                            if not 카테고리_클릭_성공:
                                print(f"'{카테고리_값}' 카테고리를 찾을 수 없습니다.")
                            else:
                                time.sleep(2)
                                
                        except Exception as e:
                            print(f"카테고리 버튼 클릭 중 오류 발생: {e}")
                    else:
                        print(f"아이디 '{아이디}'의 카테고리 값이 비어있어 카테고리 버튼을 클릭하지 않습니다.")
                else:
                    print(f"아이디 '{아이디}'를 계정정보 스프레드시트에서 찾을 수 없습니다.")
            else:
                print("계정정보 스프레드시트에 '카테고리' 컬럼이 없거나 데이터가 없습니다.")
        except Exception as e:
            print(f"카테고리 확인 중 오류 발생: {e}")
    else:
        print("아이디가 전달되지 않아 카테고리 버튼을 클릭하지 않습니다.")
    
    # 주제 버튼 클릭
    theme_button = driver.find_element(By.CSS_SELECTOR, "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.option_theme__aYDuG > div > div > a")
    theme_button.click()
    time.sleep(5)
    
    # 지명키워드.xlsx에서 주제 읽기
    try:
        주제_df = 지명키워드_df_가져오기()
        if '주제' in 주제_df.columns and len(주제_df) > 0:
            subject = str(주제_df.iloc[0]['주제']).strip()
            print(f"지명키워드.xlsx에서 주제를 가져옴: '{subject}'")
            
            # 주제별 CSS 선택자 매핑
            theme_selectors = {
                "문학·책": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(1) > ul > li:nth-child(1) > span > label",
                "영화": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(1) > ul > li:nth-child(2) > span > label",
                "미술·디자인": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(1) > ul > li:nth-child(3) > span > label",
                "공연·전시": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(1) > ul > li:nth-child(4) > span > label",
                "음악": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(1) > ul > li:nth-child(5) > span > label",
                "드라마": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(1) > ul > li:nth-child(6) > span > label",
                "스타·연예인": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(1) > ul > li:nth-child(7) > span > label",
                "만화·애니": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(1) > ul > li:nth-child(8) > span > label",
                "방송": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(1) > ul > li:nth-child(9) > span > label",
                "일상·생각": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(2) > ul > li:nth-child(1) > span > label",
                "육아·결혼": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(2) > ul > li:nth-child(2) > span > label",
                "반려동물": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(2) > ul > li:nth-child(3) > span > label",
                "좋은글·이미지": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(2) > ul > li:nth-child(4) > span > label",
                "패션·미용": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(2) > ul > li:nth-child(5) > span > label",
                "인테리어·DIY": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(2) > ul > li:nth-child(6) > span > label",
                "요리·레시피": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(2) > ul > li:nth-child(7) > span > label",
                "상품리뷰": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(2) > ul > li:nth-child(8) > span > label",
                "원예·재배": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(2) > ul > li:nth-child(9) > span > label",
                "게임": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(3) > ul > li:nth-child(1) > span > label",
                "스포츠": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(3) > ul > li:nth-child(2) > span > label",
                "사진": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(3) > ul > li:nth-child(3) > span > label",
                "자동차": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(3) > ul > li:nth-child(4) > span > label",
                "취미": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(3) > ul > li:nth-child(5) > span > label",
                "국내여행": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(3) > ul > li:nth-child(6) > span > label",
                "세계여행": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(3) > ul > li:nth-child(7) > span > label",
                "맛집": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(3) > ul > li:nth-child(8) > span > label",
                "IT·컴퓨터": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(4) > ul > li:nth-child(1) > span > label",
                "사회·정치": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(4) > ul > li:nth-child(2) > span > label",
                "건강·의학": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(4) > ul > li:nth-child(3) > span > label",
                "비즈니스·경제": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(4) > ul > li:nth-child(4) > span > label",
                "어학·외국어": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(4) > ul > li:nth-child(5) > span > label",
                "교육·학문": "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.theme_list_wrap__IpKh9 > div:nth-child(4) > ul > li:nth-child(6) > span > label"
            }
            
            # 주제에 해당하는 버튼 클릭
            if subject in theme_selectors:
                try:
                    subject_button = driver.find_element(By.CSS_SELECTOR, theme_selectors[subject])
                    subject_button.click()
                    print(f"'{subject}' 주제 버튼 클릭 완료")
                    time.sleep(3)
                    
                    # 주제 선택 후 확인 버튼 클릭
                    theme_confirm_button = driver.find_element(By.CSS_SELECTOR, "#root > div > div.header__Ceaap > div > div.publish_btn_area__KjA2i > div:nth-child(2) > div > div > div > div.layer_btn_area__UzyKH > div > button.ok_btn__mVM4b")
                    theme_confirm_button.click()
                    print("주제 확인 버튼 클릭 완료")
                    time.sleep(3)
                except Exception as e:
                    print(f"주제 버튼 클릭 중 오류 발생: {e}")
            else:
                print(f"'{subject}' 주제에 해당하는 선택자를 찾을 수 없습니다.")
        else:
            print("지명키워드.xlsx에 '주제' 컬럼이 없거나 데이터가 없습니다.")
    except Exception as e:
        print(f"주제 읽기 중 오류 발생: {e}")
    
    confirm_button = driver.find_element(By.CSS_SELECTOR, ".confirm_btn__WEaBq")
    confirm_button.click()
    time.sleep(60)

    print("블로그 포스팅이 완료되었습니다!")
    
    # 포스팅 완료 로그 저장
    중요_작업_로그_저장(f"블로그 포스팅 완료: 제목={title}, 아이디={id}")
    
    # === 포스팅 완료 후 API 키 사용 기록 초기화 ===
    reset_api_key_usage()

    # === 포스팅 완료 후 현재 글의 URL(링크) 가져오기 ===
    post_url = driver.current_url

    # === 구글 스프레드시트에 작업완료확인 기록 ===
    import re
    

    # 2. 구글 스프레드시트에 작업완료확인 데이터 추가
    # 지명키워드.xlsx에서 지명, 키워드, 지명키워드 값을 바로 가져오기
    try:
        # 지명키워드.xlsx에서 지명, 키워드, 지명키워드 값 가져오기
        지명키워드_df = 지명키워드_df_가져오기()
        if '지명' in 지명키워드_df.columns and '키워드' in 지명키워드_df.columns and '지명키워드' in 지명키워드_df.columns:
            # 지명키워드.xlsx에서 첫 번째 행의 값을 바로 가져오기
            if len(지명키워드_df) > 0:
                # 지명키워드.xlsx에서 첫 번째 행의 값을 바로 사용
                location = str(지명키워드_df.iloc[0]['지명'])
                keyword = str(지명키워드_df.iloc[0]['키워드'])
                location_keyword = str(지명키워드_df.iloc[0]['지명키워드'])
                print(f"지명키워드.xlsx에서 값을 가져옴: 지명='{location}', 키워드='{keyword}', 지명키워드='{location_keyword}'")
            else:
                # 데이터가 없으면 기본값 사용
                location = '지명'
                keyword = '키워드'
                location_keyword = '지명키워드'
                print(f"지명키워드.xlsx에 데이터가 없어 기본값 사용: 지명='{location}', 키워드='{keyword}', 지명키워드='{location_keyword}'")
        else:
            print("지명키워드.xlsx에 '지명', '키워드', '지명키워드' 컬럼이 없어 기본값 사용")
            location = '지명'
            keyword = '키워드'
            location_keyword = '지명키워드'
    except Exception as e:
        print(f"지명키워드.xlsx 읽기 중 오류: {e}, 기본값 사용")
        location = '지명'
        keyword = '키워드'
        location_keyword = '지명키워드'
    
    # 지명키워드.xlsx에서 이미 지명키워드 값을 가져왔으므로 블로그제목.xlsx 읽기 생략
    현재_시간 = datetime.datetime.now()
    현재_시간_문자열 = 현재_시간.strftime('%Y-%m-%d %H:%M:%S')
    
    # 구글 스프레드시트에 데이터 추가
    print(f"작업완료확인 데이터 준비: 지명='{location}', 키워드='{keyword}', 지명키워드='{location_keyword}'")
    if title and not _원고_작성_지명키워드_일치(location_keyword):
        _title_norm = str(title).replace(' ', '')
        _kw_norm = str(location_keyword).replace(' ', '')
        if _kw_norm not in _title_norm:
            print(f"경고: 포스팅 제목과 지명키워드 불일치 (지명키워드='{location_keyword}', 제목='{title}')")
            오류_로그_저장(f"지명키워드-제목 불일치: kw={location_keyword}, title={title}")
    
    if 구글스프레드시트_작업완료확인_추가(location, keyword, location_keyword, title, id, hananoran, post_url, 현재_시간_문자열):
        print("작업완료확인 데이터가 구글 스프레드시트에 성공적으로 저장되었습니다.")
        try:
            현재_ip = get_computer_ip() or ''
            _글유형 = _블로그_글유형_가져오기()
            _세부유형 = _블로그_세부유형_가져오기()
            _지명키워드_이력_시트_일괄_저장(
                location_keyword, id, 글유형=_글유형, 세부유형=_세부유형,
                아이피=현재_ip, 링크=post_url
            )
        except Exception as _hist_e:
            print(f"지명키워드 이력 일괄 기록 실패 (무시): {_hist_e}")
        _로컬_스케줄_항목_완료표시(id)
        작업_로그_저장(f"작업완료확인 구글 스프레드시트 저장 성공: 아이디={id}, 제목={title}, 지명={location}, 키워드={keyword}")
        
        # === 포스팅 작업요청 스프레드시트에서 사용한 행 삭제 ===
        try:
            # 지명키워드.xlsx에서 포스팅작업요청_행인덱스 컬럼 확인
            if '포스팅작업요청_행인덱스' in 지명키워드_df.columns:
                행_번호 = 지명키워드_df.iloc[0]['포스팅작업요청_행인덱스']
                if pd.notna(행_번호) and 행_번호:
                    행_번호 = int(행_번호)
                    print(f"\n🔍 포스팅 작업요청 스프레드시트에서 {행_번호}번째 행 삭제 중...")
                    if 포스팅작업요청_스프레드시트_행_삭제(행_번호):
                        print(f"✅ 포스팅 작업요청 스프레드시트에서 {행_번호}번째 행을 성공적으로 삭제했습니다.")
                        중요_작업_로그_저장(f"포스팅 작업요청 스프레드시트 행 삭제 성공: 행번호={행_번호}")
                    else:
                        print(f"❌ 포스팅 작업요청 스프레드시트에서 {행_번호}번째 행 삭제 실패")
                        오류_로그_저장(f"포스팅 작업요청 스프레드시트 행 삭제 실패: 행번호={행_번호}")
                else:
                    print("포스팅 작업요청 행 인덱스가 없어 행 삭제를 건너뜁니다.")
            else:
                print("포스팅 작업요청 행 인덱스 컬럼이 없어 행 삭제를 건너뜁니다.")
        except Exception as e:
            print(f"포스팅 작업요청 스프레드시트 행 삭제 중 오류: {e}")
            오류_로그_저장(f"포스팅 작업요청 스프레드시트 행 삭제 오류: {e}")

        # === 지명키워드 로컬 작업큐 항목 삭제 (포스팅 완료 후) ===
        try:
            _로컬_작업큐_항목_삭제(_지명키워드_작업_행번호)
        except Exception as e:
            print(f"로컬 작업큐 항목 삭제 중 오류: {e}")
            오류_로그_저장(f"포스팅 완료 후 로컬 작업큐 항목 삭제 오류: {e}")
    else:
        print("경고: 작업완료확인 데이터를 구글 스프레드시트에 저장할 수 없습니다.")
        오류_로그_저장(f"작업완료확인 구글 스프레드시트 저장 실패: 아이디={id}, 제목={title}, 지명={location}, 키워드={keyword}")

    # === 포스팅 완료 후 포스팅수 업데이트 ===
    try:
        # 구글 스프레드시트에서 포스팅수 업데이트
        if 구글스프레드시트_포스팅수_업데이트(id):
            print(f"아이디 '{id}'의 포스팅수가 구글 스프레드시트에서 성공적으로 업데이트되었습니다.")
            작업_로그_저장(f"포스팅수 구글 스프레드시트 업데이트 성공: 아이디={id}")
        else:
            print(f"아이디 '{id}'의 포스팅수 업데이트에 실패했습니다.")
            오류_로그_저장(f"포스팅수 구글 스프레드시트 업데이트 실패: 아이디={id}")
    except Exception as e:
        print(f"포스팅수 업데이트 중 오류: {str(e)}")
        오류_로그_저장(f"포스팅수 업데이트 중 오류: {str(e)}")

    # === 블로그 글 작성 완료 후 구글 스프레드시트에서 아이디 삭제 ===
    try:
        print(f"작업 완료 후 아이디 '{id}'를 구글 스프레드시트에서 삭제합니다...")
        
        if 구글스프레드시트_아이디_삭제(id):
            print("구글 스프레드시트에서 아이디가 성공적으로 삭제되었습니다.")
            작업_로그_저장(f"구글 스프레드시트 아이디 삭제 성공: 아이디={id}")
        else:
            print("구글 스프레드시트에서 아이디 삭제에 실패했습니다.")
            오류_로그_저장(f"구글 스프레드시트 아이디 삭제 실패: 아이디={id}")
    except Exception as e:
        print(f"구글 스프레드시트 아이디 삭제 중 오류: {e}")
        오류_로그_저장(f"구글 스프레드시트 아이디 삭제 중 오류: {e}")

    # === 작업 완료 후 크롬창 닫기 전 네이버 랜덤 브라우징 ===
    print("\n🌐 작업 완료 후 크롬창 닫기 전 네이버 랜덤 브라우징을 시작합니다...")
    중요_작업_로그_저장("작업 완료 후 크롬창 닫기 전 네이버 랜덤 브라우징 시작")
    
    try:
        # 네이버 메인 페이지로 이동
        print("네이버 메인 페이지로 이동합니다...")
        driver.get("https://www.naver.com")
        time.sleep(random.uniform(2, 3))
        
        # 3-5분 랜덤 브라우징
        브라우징_시간 = random.uniform(3, 5)  # 3-5분
        if 네이버_랜덤_브라우징(driver, 브라우징_시간):
            print("✅ 작업 완료 후 랜덤 브라우징이 완료되었습니다!")
            중요_작업_로그_저장("작업 완료 후 크롬창 닫기 전 네이버 랜덤 브라우징 완료")
        else:
            print("⚠️ 랜덤 브라우징에 실패했지만 계속 진행합니다.")
            중요_작업_로그_저장("작업 완료 후 랜덤 브라우징 실패하지만 진행")
    except Exception as e:
        print(f"⚠️ 랜덤 브라우징 중 오류가 발생했지만 계속 진행합니다: {e}")
        중요_작업_로그_저장(f"작업 완료 후 랜덤 브라우징 오류하지만 진행: {str(e)}")

    # === 작업 완료 후 네이버로 이동 ===
    try:
        print("\n🌐 작업 완료 후 네이버로 이동합니다...")
        driver.get("https://www.naver.com")
        print("✅ 네이버로 이동이 완료되었습니다.")
        중요_작업_로그_저장("작업 완료 후 네이버로 이동 완료")
        time.sleep(3)  # 페이지 로딩 대기
        
        # 로그아웃 버튼 클릭 시도
        try:
            print("🔓 로그아웃 버튼을 찾는 중...")
            로그아웃_버튼 = driver.find_element(By.CSS_SELECTOR, "#account > div.MyView-module__my_info___GNmHz > div > button")
            로그아웃_버튼.click()
            print("✅ 로그아웃 버튼 클릭 완료")
            중요_작업_로그_저장("작업 완료 후 네이버 로그아웃 버튼 클릭 완료")
            time.sleep(10)  # 로그아웃 처리 대기
        except Exception as logout_error:
            print(f"⚠️ 로그아웃 버튼 클릭 중 오류 (로그인 상태가 아닐 수 있음): {logout_error}")
            중요_작업_로그_저장(f"작업 완료 후 네이버 로그아웃 버튼 클릭 실패: {str(logout_error)}")
            
    except Exception as e:
        print(f"⚠️ 네이버로 이동 중 오류 발생: {e}")
        오류_로그_저장(f"작업 완료 후 네이버로 이동 오류: {str(e)}")

    # === 작업 완료 후 크롬창 닫기 ===
    try:
        # 3333.py의 완전한 브라우저 데이터 삭제 함수 실행
        print("\n🧹 크롬창 닫기 전 완전한 브라우저 데이터 삭제를 실행합니다...")
        중요_작업_로그_저장("작업 완료 후 완전한 브라우저 데이터 삭제 시작")
        
        if 완전한_브라우저_데이터_삭제(driver):
            print("✅ 완전한 브라우저 데이터 삭제가 성공적으로 완료되었습니다.")
            중요_작업_로그_저장("작업 완료 후 완전한 브라우저 데이터 삭제 성공")
        else:
            print("⚠️ 완전한 브라우저 데이터 삭제 중 일부 문제가 발생했지만 계속 진행합니다.")
            중요_작업_로그_저장("작업 완료 후 완전한 브라우저 데이터 삭제 부분 실패")
            
    except Exception as e:
        print(f"❌ 완전한 브라우저 데이터 삭제 중 오류 발생: {str(e)}")
        오류_로그_저장(f"작업 완료 후 완전한 브라우저 데이터 삭제 오류: {str(e)}")
        
        # 기본 드라이버 종료라도 시도
        try:
            driver.quit()
            print("기본 크롬창 닫기가 완료되었습니다.")
        except:
            print("기본 크롬창 닫기도 실패했습니다.")
    
    return True


if __name__ == "__main__":
    try:
        print("=== 모든 아이디 시도 및 5분 간격 재시도 시스템 시작 ===")
        print("아이디2 구글 시트에서 실시간으로 계정정보를 가져와 5분 간격으로 계속 재시도합니다.")
        
        # 프로그램 시작 로그
        중요_작업_로그_저장("=== 블로그 포스팅 프로그램 시작 ===")
        
        # 모든 아이디가 사용 중인 상황이 연속으로 발생한 횟수 추적
        모든_아이디_사용중_연속_횟수 = 0
        
        # 모든 사용 가능한 아이디를 시도했지만 성공하지 못한 상황이 연속으로 발생한 횟수 추적
        모든_아이디_시도_실패_연속_횟수 = 0
        _포스팅_재시작_임계값 = 3
        
        while True:  # 무한 루프로 계속 재시도
            try:
                # 아이디2 구글 시트에서 실시간 계정정보 가져오기 (포스팅수 실시간 반영)
                try:
                    df = 작업아이디_포스팅수순_가져오기()
                    if df.empty:
                        print("구글 시트에서 유효한 계정을 가져올 수 없습니다.")
                        print("하루최대포스팅수 제한으로 인해 사용 가능한 아이디가 없습니다.")
                        모든_아이디_시도_실패_연속_횟수 += 1
                        중요_작업_로그_저장(
                            f"사용 가능한 아이디 없음(하루최대포스팅수) - "
                            f"5분 후 재시도 (연속 {모든_아이디_시도_실패_연속_횟수}번째)"
                        )
                        if 모든_아이디_시도_실패_연속_횟수 >= _포스팅_재시작_임계값:
                            print(f"{_포스팅_재시작_임계값}회 연속 실패하여 프로그램을 재시작합니다.")
                            중요_작업_로그_저장(
                                f"사용 가능한 아이디 없음 {_포스팅_재시작_임계값}회 연속 - 프로그램 재시작"
                            )
                            프로그램_같은_터미널_재시작("사용 가능한 아이디 없음 연속 실패")
                        print("5분 후 다시 시도합니다...")
                        time.sleep(300)
                        continue
                except Exception as e:
                    print(f"구글 시트 계정정보 읽기 실패: {e}")
                    print("5분 후 다시 시도합니다...")
                    time.sleep(300)  # 5분 대기
                    continue
                
                # '아이디', '비번', '홍보문구', '하나노란' 컬럼에서 결측치가 없는 행만 필터링
                df = df.dropna(subset=['아이디', '비번', '홍보문구', '하나노란'])
                
                if len(df) == 0:
                    print("유효한 계정 정보가 없습니다.")
                    print("5분 후 다시 시도합니다...")
                    time.sleep(300)  # 5분 대기
                    continue
                
                # 구글 스프레드시트에서 현재 사용 중인 아이디들 가져오기
                사용중인_아이디들 = []
                try:
                    사용중인_아이디들 = 구글스프레드시트_사용중인_아이디_목록_가져오기()
                    print(f"현재 구글 스프레드시트에서 사용 중인 아이디들: {사용중인_아이디들}")
                except Exception as e:
                    print(f"구글 스프레드시트에서 사용 중인 아이디 목록 가져오기 실패: {e}")
                    사용중인_아이디들 = []
                
                # 사용 가능한 아이디들 필터링
                사용가능한_아이디들 = df[~df['아이디'].isin(사용중인_아이디들)]
                
                if len(사용가능한_아이디들) == 0:
                    모든_아이디_사용중_연속_횟수 += 1
                    print(f"모든 아이디가 구글 스프레드시트에서 사용 중입니다. (연속 {모든_아이디_사용중_연속_횟수}번째)")
                    중요_작업_로그_저장(
                        f"모든 아이디 구글 시트 사용 중 - "
                        f"5분 후 재시도 (연속 {모든_아이디_사용중_연속_횟수}번째, "
                        f"사용중={사용중인_아이디들})"
                    )
                    
                    if 모든_아이디_사용중_연속_횟수 >= _포스팅_재시작_임계값:
                        print(f"모든 아이디가 {_포스팅_재시작_임계값}회 연속 사용 중이어서 프로그램을 재시작합니다.")
                        중요_작업_로그_저장(
                            f"모든 아이디 사용 중 {_포스팅_재시작_임계값}회 연속 - 프로그램 재시작"
                        )
                        프로그램_같은_터미널_재시작("모든 아이디 사용 중 연속 실패")
                    
                    print("5분 후 다시 시도합니다...")
                    time.sleep(300)  # 5분 대기
                    continue
                
                # 사용 가능한 아이디가 있으면 카운터 리셋
                if 모든_아이디_사용중_연속_횟수 > 0:
                    print(f"사용 가능한 아이디를 찾았습니다. 연속 대기 카운터를 리셋합니다. (이전 연속 횟수: {모든_아이디_사용중_연속_횟수})")
                    모든_아이디_사용중_연속_횟수 = 0
                
                print(f"사용 가능한 아이디 수: {len(사용가능한_아이디들)}개")
                
                # 이미 포스팅수 순서로 정렬되어 있으므로 그대로 사용
                print("포스팅수가 적은 순서로 정렬된 아이디를 사용합니다.")
                
                # 로컬 작업큐 캐시에서 하나노란 값 가져오기 (작업완료확인 기록용)
                try:
                    지명키워드_df = 지명키워드_df_가져오기()
                    if not 지명키워드_df.empty and '하나노란' in 지명키워드_df.columns:
                        hananoran = str(지명키워드_df.iloc[0]['하나노란']).strip()
                        if hananoran == 'nan':
                            hananoran = ""
                        print(f"작업큐 캐시에서 하나노란 값 가져오기 성공: '{hananoran}'")
                    else:
                        print("작업큐 캐시가 비어있거나 하나노란 컬럼이 없습니다.")
                        hananoran = ""
                except Exception as e:
                    print(f"작업큐 캐시 읽기 중 오류: {e}")
                    hananoran = ""
                
                # 각 사용 가능한 아이디를 포스팅수 순서대로 시도
                시도_요약 = []
                for idx, row in 사용가능한_아이디들.iterrows():
                    id = str(row['아이디'])
                    try:
                        pw = str(row['비번'])
                        # promo_text는 지명 기반으로 선택된 홍보문구 사용 (이미 위에서 선택됨)
                        # hananoran은 지명키워드.xlsx에서 가져온 값 사용
                        account_index = idx
                        
                        print(f"\n=== 아이디 '{id}' 시도 중 ===")
                        
                        # 로그인금지시간대 확인
                        if not 로그인금지시간대_확인(id, df):
                            print(f"아이디 '{id}'는 현재 시간에 로그인이 금지되어 있습니다. 다음 아이디를 시도합니다.")
                            중요_작업_로그_저장(f"아이디 '{id}' 로그인금지시간대 - 스킵")
                            시도_요약.append((id, '로그인금지'))
                            continue
                        
                        # 하루최대포스팅수 최종 안전망 확인 (필터링을 통과했더라도 재확인)
                        try:
                            _최대포스팅수 = pd.to_numeric(row.get('하루최대포스팅수', 3), errors='coerce')
                            if pd.isna(_최대포스팅수) or _최대포스팅수 <= 0:
                                print(f"아이디 '{id}'는 하루최대포스팅수({row.get('하루최대포스팅수')})가 0 이하입니다. 로그인을 건너뜁니다.")
                                중요_작업_로그_저장(
                                    f"아이디 '{id}' 하루최대포스팅수 제한({row.get('하루최대포스팅수')}) - 스킵"
                                )
                                시도_요약.append((id, '하루최대'))
                                continue
                        except Exception as _e:
                            print(f"아이디 '{id}' 하루최대포스팅수 확인 중 오류: {_e}")
                        
                        # 팝업창 차단을 위한 Chrome 옵션 설정 (undetected-chromedriver)
                        chrome_options = uc_포스팅_크롬_옵션_생성()
                        driver = uc_크롬_드라이버_생성(chrome_options)
                        
                        # 네이버 로그인 및 준비
                        if naver_login_and_prepare(driver, id, pw):
                            # 로그인 성공 시 카운터 리셋
                            if 모든_아이디_시도_실패_연속_횟수 > 0:
                                print(f"아이디 '{id}' 로그인 성공! 연속 실패 카운터를 리셋합니다. (이전 연속 횟수: {모든_아이디_시도_실패_연속_횟수})")
                                모든_아이디_시도_실패_연속_횟수 = 0
                            
                            print(f"아이디 '{id}'로 로그인에 성공했습니다!")
                            
                            # 현재 폴더의 최종원고.txt 파일 읽기
                            script_dir = os.path.dirname(os.path.abspath(__file__))
                            markdown_file = resource_path("최종원고.txt")
                            title, content = process_markdown_file(markdown_file)
                            
                            # 지명 기반으로 홍보문구 다시 선택
                            현재_지명 = 지명키워드에서_지명_추출()
                            random_promo_text = get_random_promo_text_from_spreadsheet(df, 현재_지명)
                            
                            # 지명 엑셀파일에서 선택된 하나노란 값 가져오기
                            지명_행 = 지명으로_행_찾기(현재_지명, df)
                            if 지명_행 is not None and "하나노란" in 지명_행.index:
                                지명_하나노란_값 = str(지명_행["하나노란"]).strip()
                                if 지명_하나노란_값 and 지명_하나노란_값 != 'nan':
                                    hananoran = 지명_하나노란_값
                                    print(f"지명 '{현재_지명}'에서 선택된 하나노란 값: {hananoran}")
                            
                            # 블로그 글 작성 시도 (지명 기반으로 선택된 홍보문구 사용)
                            if write_to_naver_blog(driver, title, content, random_promo_text, hananoran, account_index, id):
                                print("정상 완료! 블로그 포스팅 작업이 완료되었습니다.")
                                
                                # === 작업이 정상적으로 완료되면 맨 처음으로 돌아가서 재실행 ===
                                print("작업이 정상적으로 완료되었습니다!")
                                
                                # 1분~2분 랜덤 휴식시간 적용
                                import random
                                휴식_분 = random.randint(1, 2)
                                휴식_초 = 휴식_분 * 60
                                
                                print(f"전체 작업 완료 후 {휴식_분}분({휴식_초}초) 휴식시간을 가집니다...")
                                print("휴식시간 동안 프로그램이 자동으로 재시작됩니다.")
                                
                                # 전체 작업 완료 및 휴식 시작 로그
                                중요_작업_로그_저장(f"전체 작업 완료 후 {휴식_분}분 휴식 시작")
                                
                                # 휴식시간 동안 대기
                                time.sleep(휴식_초)
                                
                                print(f"{휴식_분}분 휴식 완료! 프로그램을 처음부터 다시 실행합니다.")
                                
                                # 휴식 완료 및 재시작 로그
                                중요_작업_로그_저장(f"{휴식_분}분 휴식 완료, 프로그램 재시작")
                                print("프로그램을 처음부터 다시 시작합니다.")
                                프로그램_같은_터미널_재시작("전체 작업 완료 후 재시작")
                            else:
                                print("블로그 글 작성에 실패했습니다.")
                                중요_작업_로그_저장(f"포스팅 실패: {id}")
                                
                                # === 작업 완료 후 크롬창 닫기 전 네이버 랜덤 브라우징 ===
                                print("\n🌐 작업 완료 후 크롬창 닫기 전 네이버 랜덤 브라우징을 시작합니다...")
                                중요_작업_로그_저장("작업 완료 후 크롬창 닫기 전 네이버 랜덤 브라우징 시작")
                                
                                try:
                                    # 네이버 메인 페이지로 이동
                                    print("네이버 메인 페이지로 이동합니다...")
                                    driver.get("https://www.naver.com")
                                    time.sleep(random.uniform(2, 3))
                                    
                                    브라우징_시간 = random.uniform(3, 5)  # 3-5분
                                    if 네이버_랜덤_브라우징(driver, 브라우징_시간):
                                        print("✅ 작업 완료 후 랜덤 브라우징이 완료되었습니다!")
                                        중요_작업_로그_저장("작업 완료 후 크롬창 닫기 전 네이버 랜덤 브라우징 완료")
                                    else:
                                        print("⚠️ 랜덤 브라우징에 실패했지만 계속 진행합니다.")
                                        중요_작업_로그_저장("작업 완료 후 랜덤 브라우징 실패하지만 진행")
                                except Exception as e:
                                    print(f"⚠️ 랜덤 브라우징 중 오류가 발생했지만 계속 진행합니다: {e}")
                                    중요_작업_로그_저장(f"작업 완료 후 랜덤 브라우징 오류하지만 진행: {str(e)}")
                                
                                try:
                                    driver.quit()
                                    print("크롬창을 닫았습니다.")
                                except:
                                    pass
                                
                                # 1-2분 휴식 후 맨 처음으로 재시작
                                휴식_분 = random.randint(1, 2)
                                휴식_초 = 휴식_분 * 60
                                
                                print(f"\n⏰ 포스팅 실패! {휴식_분}분 휴식 후 프로그램을 재시작합니다...")
                                중요_작업_로그_저장(f"포스팅 실패 - {휴식_분}분 휴식 후 재시작 (원고 재생성)")
                                
                                # 휴식시간 동안 대기
                                time.sleep(휴식_초)
                                
                                print(f"{휴식_분}분 휴식 완료! 제목·원고를 새로 생성하며 프로그램을 재시작합니다.")
                                중요_작업_로그_저장(f"{휴식_분}분 휴식 완료 - 원고 재생성 재시작")
                                프로그램_같은_터미널_재시작("포스팅 실패 후 재시도")
                        else:
                            print(f"아이디 '{id}' 로그인에 실패했습니다. 다음 아이디를 시도합니다.")
                            중요_작업_로그_저장(f"아이디 '{id}' 로그인 실패 - 다음 아이디 시도")
                            시도_요약.append((id, '로그인실패'))
                            try:
                                driver.quit()
                            except:
                                pass
                            continue
                            
                    except Exception as e:
                        print(f"아이디 '{id}' 처리 중 오류 발생: {e}")
                        중요_작업_로그_저장(f"아이디 '{id}' 처리 중 오류: {e}")
                        시도_요약.append((id, '처리오류'))
                        try:
                            driver.quit()
                        except:
                            pass
                        continue
                
                # 모든 아이디를 시도했지만 성공하지 못한 경우
                _스킵_사유만 = (
                    len(시도_요약) > 0
                    and all(
                        r in ('로그인금지', '하루최대')
                        for _, r in 시도_요약
                    )
                )
                _요약_문자열 = ', '.join(f"{aid}({reason})" for aid, reason in 시도_요약) if 시도_요약 else '시도 내역 없음'
                
                if _스킵_사유만:
                    print("로그인금지시간/하루최대포스팅수로만 스킵되었습니다. 5분 후 같은 프로세스에서 재시도합니다.")
                    print(f"시도 요약: {_요약_문자열}")
                    중요_작업_로그_저장(
                        f"전체 아이디 스킵(금지시간/최대포스팅) - 5분 후 재시도: {_요약_문자열}"
                    )
                    time.sleep(300)
                    continue
                
                모든_아이디_시도_실패_연속_횟수 += 1
                print(f"모든 사용 가능한 아이디를 시도했지만 성공하지 못했습니다. (연속 {모든_아이디_시도_실패_연속_횟수}번째)")
                print(f"시도 요약: {_요약_문자열}")
                중요_작업_로그_저장(
                    f"모든 사용 가능한 아이디 시도 실패 (연속 {모든_아이디_시도_실패_연속_횟수}번째): {_요약_문자열}"
                )
                
                # 로그인 실패/처리 오류 등: 3회 연속까지 5분 대기, 그 후 재시작
                if 모든_아이디_시도_실패_연속_횟수 >= _포스팅_재시작_임계값:
                    print(f"모든 사용 가능한 아이디를 {_포스팅_재시작_임계값}회 연속 시도했지만 성공하지 못해 프로그램을 재시작합니다.")
                    중요_작업_로그_저장(
                        f"모든 아이디 시도 실패 {_포스팅_재시작_임계값}회 연속 - 프로그램 재시작: {_요약_문자열}"
                    )
                    프로그램_같은_터미널_재시작(f"모든 아이디 시도 실패 {_포스팅_재시작_임계값}회 연속")
                
                print("5분 후 다시 시도합니다...")
                time.sleep(300)  # 5분 대기
                
            except KeyboardInterrupt:
                print("\n사용자에 의해 프로그램이 중단되었습니다.")
                sys.exit(0)
            except Exception as e:
                print(f"오류 발생: {e}")
                import traceback
                traceback.print_exc()
                print("오류 발생! 5분 후 다시 시도합니다...")
                time.sleep(300)  # 5분 대기
                
                # 프로그램 완전 재시작 (리소스 정리 포함)
                프로그램_완전_재시작("내부 루프 오류")
                
    except Exception as e:
        print(f"메인 프로그램 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        print("오류 발생! 5분 후 다시 시도합니다...")
        time.sleep(300)  # 5분 대기
        
        # 프로그램 완전 재시작 (리소스 정리 포함)
        프로그램_완전_재시작("메인 프로그램 오류")