# ==========================================
# XT.com Futures Scanner - Daily & Hourly EMA
# اجرا روی GitHub Actions
# ==========================================

import ccxt
import pandas as pd
from tqdm import tqdm
import time
from datetime import datetime
import urllib.parse
import jdatetime
import pytz
import warnings
import os
import json
import gspread
from google.oauth2.service_account import Credentials

warnings.filterwarnings('ignore', category=DeprecationWarning)

# تنظیمات از environment variables
SHEET_ID = os.environ['SHEET_ID']
SHEET_NAME = os.environ.get('SHEET_NAME', 'Bullish_Trend')
GOOGLE_CREDENTIALS_JSON = os.environ['GOOGLE_CREDENTIALS_JSON']


def is_ascii_safe(text):
    try:
        return text.isascii()
    except:
        return False


def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean().iloc[-1]


def get_iran_shamsi_timestamp():
    """تاریخ و ساعت شمسی ایران"""
    tehran_tz = pytz.timezone('Asia/Tehran')
    now_tehran = datetime.now(tehran_tz)
    jalali_date = jdatetime.date.fromgregorian(
        year=now_tehran.year,
        month=now_tehran.month,
        day=now_tehran.day
    )
    formatted_date = jalali_date.strftime('%Y/%m/%d')
    formatted_time = now_tehran.strftime('%H:%M:%S')
    return f"{formatted_date} - {formatted_time}"


def get_tradingview_link(symbol):
    base = symbol.split('/')[0]
    tv_symbol = f":{base}USDT"
    encoded_symbol = urllib.parse.quote(tv_symbol)
    return f"https://www.tradingview.com/chart/?symbol={encoded_symbol}"


def write_to_google_sheet(results):
    """نوشتن نتایج در گوگل شیت"""
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # باز کردن شیت
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        
        # پاک کردن محتوای قبلی
        sheet.clear()
        
        # اضافه کردن هدر
        timestamp = get_iran_shamsi_timestamp()
        header = [f"XT Futures EMA Scan - {timestamp} | تعداد: {len(results)}"]
        sheet.append_row(header)
        sheet.append_row([""])
        
        # هدر ستون‌ها
        headers = ["Timestamp", "Symbol", "Price ($)", "EMA50 ($)", "Distance %", "TradingView"]
        sheet.append_row(headers)
        
        # اضافه کردن داده‌ها
        shamsi_ts = get_iran_shamsi_timestamp()
        for row in results:
            sheet.append_row([
                shamsi_ts,
                row['Symbol'],
                row['Price ($)'],
                row['EMA(50)'],
                f"{row['Distance %']}%",
                row['TradingView Link']
            ])
        
        # فرمت‌بندی
        sheet.format('A1:F1', {'textFormat': {'bold': True, 'fontSize': 14}})
        sheet.format('A3:F3', {'textFormat': {'bold': True}})
        sheet.format('A4:F4', {'textFormat': {'bold': True}})
        
        # عرض ستون‌ها
        sheet.column_dimensions['A'].width = 20
        sheet.column_dimensions['B'].width = 20
        sheet.column_dimensions['C'].width = 15
        sheet.column_dimensions['D'].width = 15
        sheet.column_dimensions['E'].width = 12
        sheet.column_dimensions['F'].width = 60
        
        print(f"✅ نتایج در گوگل شیت نوشته شد: {len(results)} ارز")
        return True
        
    except Exception as e:
        print(f"❌ خطا در نوشتن در گوگل شیت: {e}")
        return False


def scan_xt_futures():
    print("🔄 در حال اتصال به بازار فیوچرز صرافی XT.com...")

    exchange = ccxt.xt({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'}
    })

    try:
        markets = exchange.load_markets()
        futures_pairs = [
            symbol for symbol, market in markets.items()
            if market['swap'] and market['active']
        ]
        print(f"✅ تعداد {len(futures_pairs)} جفت ارز فیوچرز فعال در XT پیدا شد")
    except Exception as e:
        print(f"❌ خطا در اتصال به XT: {e}")
        return

    print("⏳ در حال بررسی فیلترهای روزانه و ساعتی...\n")

    results = []
    skipped_non_ascii = 0

    for symbol in tqdm(futures_pairs, desc="📊 اسکن بازار فیوچرز"):
        try:
            base_symbol = symbol.split('/')[0]
            if not is_ascii_safe(base_symbol):
                skipped_non_ascii += 1
                continue

            # فیلتر ۱: روزانه
            ohlcv_1d = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=100)
            if len(ohlcv_1d) < 50:
                continue

            df_1d = pd.DataFrame(ohlcv_1d, columns=['timestamp','open','high','low','close','volume'])
            current_price = df_1d['close'].iloc[-1]
            ema50_1d = calculate_ema(df_1d['close'], 50)

            if current_price <= ema50_1d:
                continue

            # فیلتر ۲: ساعتی
            ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            if len(ohlcv_1h) < 200:
                continue

            df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp','open','high','low','close','volume'])
            ema50_1h  = calculate_ema(df_1h['close'], 50)
            ema200_1h = calculate_ema(df_1h['close'], 200)

            if current_price > ema50_1h > ema200_1h:
                distance_pct = ((current_price - ema50_1d) / ema50_1d) * 100
                tv_link = get_tradingview_link(symbol)

                results.append({
                    'Symbol':          symbol,
                    'Price ($)':       round(current_price, 8),
                    'EMA(50)':         round(ema50_1d, 8),
                    'Distance %':      round(distance_pct, 2),
                    'TradingView Link': tv_link
                })

            time.sleep(0.2)

        except Exception:
            continue

    if skipped_non_ascii > 0:
        print(f"\n⏭️ {skipped_non_ascii} ارز به دلیل کاراکتر غیرانگلیسی نادیده گرفته شد.")

    if not results:
        print("\n⚠️ هیچ ارزی با این شرایط پیدا نشد")
        return

    df = pd.DataFrame(results)
    df = df.sort_values('Distance %', ascending=False).reset_index(drop=True)

    print("\n" + "="*70)
    print(f"✅ اسکن کامل شد — {len(df)} ارز با شرایط مطلوب یافت شد")
    print("="*70)

    # نوشتن در گوگل شیت
    write_to_google_sheet(results)
    
    print(f"📅 تاریخ شمسی: {get_iran_shamsi_timestamp()}")


if __name__ == "__main__":
    scan_xt_futures()
