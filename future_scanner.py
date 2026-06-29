# ==========================================
# XT.com Futures Scanner - Daily & Hourly EMA
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
import requests
from google.oauth2.service_account import Credentials

warnings.filterwarnings('ignore', category=DeprecationWarning)

SHEET_ID = os.environ['SHEET_ID']
SHEET_NAME = os.environ.get('SHEET_NAME', 'Bullish_Trend')
GOOGLE_CREDENTIALS_JSON = os.environ['GOOGLE_CREDENTIALS_JSON']
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_IDS = os.environ.get('TELEGRAM_CHAT_IDS', '').split(',')


def is_ascii_safe(text):
    try:
        return text.isascii()
    except:
        return False


def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean().iloc[-1]


def get_iran_shamsi_timestamp():
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
    """لینک TradingView که مستقیم باز شود - بدون نیاز به permission"""
    base = symbol.split('/')[0]
    return f"https://www.tradingview.com/symbols/XT-{base}USDT/"


def get_previous_data():
    """خواندن داده‌های قبلی از گوگل شیت"""
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        records = sheet.get_all_records()
        
        previous_data = {}
        for row in records:
            if 'Symbol' in row and row['Symbol']:
                symbol = row['Symbol']
                try:
                    price = float(row.get('Price ($)', 0))
                    previous_data[symbol] = {
                        'price': price,
                        'ema50': float(row.get('EMA50 ($)', 0)),
                        'ema200': float(row.get('EMA200 ($)', 0)),
                        'risk': float(str(row.get('Risk %', '0')).replace('%', ''))
                    }
                except:
                    pass
        
        return previous_data
    except Exception as e:
        print(f"⚠️ Error reading previous data: {e}")
        return {}


def write_to_google_sheet(results):
    """نوشتن بهینه در گوگل شیت - فقط 6 API Call"""
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        
        # ساخت همه داده‌ها یکجا
        shamsi_ts = get_iran_shamsi_timestamp()
        
        # هدر
        all_data = [["Timestamp", "Symbol", "Price ($)", "EMA50 ($)", "EMA200 ($)", "Risk %", "TradingView"]]
        
        # داده‌ها
        for row in results:
            all_data.append([
                shamsi_ts,
                row['Symbol'],
                row['Price ($)'],
                row['EMA50 ($)'],
                row['EMA200 ($)'],
                f"{row['Risk %']}%",
                row['TradingView Link']
            ])
        
        # پاک کردن و نوشتن یکجا (بهینه)
        sheet.clear()                              # 1 API call
        sheet.update('A1', all_data)               # 1 API call (همه داده‌ها یکجا!)
        sheet.format('A1:G1', {'textFormat': {'bold': True}})  # 1 API call
        
        # تنظیم عرض ستون‌ها
        sheet.columns_auto_resize(1, 7)            # 1 API call
        
        print(f"✅ Results written to Google Sheet: {len(results)} coins (6 API calls)")
        return True
        
    except Exception as e:
        print(f"❌ Error writing to Google Sheet: {e}")
        return False


def send_telegram(message):
    """ارسال پیام به تلگرام"""
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ Telegram bot token not set")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    for chat_id in TELEGRAM_CHAT_IDS:
        if not chat_id.strip():
            continue
        try:
            requests.post(url, json={
                'chat_id': chat_id.strip(),
                'text': message,
                'parse_mode': 'HTML'
            }, timeout=10)
            print(f"✅ Message sent to {chat_id}")
        except Exception as e:
            print(f"⚠️ Error sending to {chat_id}: {e}")


def format_number(num):
    """فرمت اعداد برای خوانایی بهتر"""
    if num >= 1:
        return f"{num:.4f}"
    else:
        return f"{num:.8f}"


def send_telegram_report(total_scanned, total_selected, new_data, previous_data, added_symbols, removed_symbols):
    """ارسال گزارش جامع به تلگرام"""
    timestamp = get_iran_shamsi_timestamp()
    
    msg = f"📊 <b>XT FUTURES SCANNER REPORT</b>\n"
    msg += f"🕐 <b>Time:</b> {timestamp}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # آمار کلی با فیلترهای جداگانه
    msg += f"🔍 <b>Total Scanned:</b> {total_scanned} pairs\n"
    msg += f"✅ <b>Selected:</b> {total_selected} coins\n"
    msg += f"📈 <b>Filter-1:</b> Price &gt; EMA50 (1D)\n"
    msg += f"📈 <b>Filter-2:</b> Price &gt; EMA50 &gt; EMA200 (1H)\n\n"
    
    # تغییرات
    if added_symbols or removed_symbols:
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"🔄 <b>CHANGES FROM LAST SCAN</b>\n\n"
        
        if added_symbols:
            msg += f"🟢 <b>NEW ADDITIONS ({len(added_symbols)}):</b>\n"
            for symbol in sorted(added_symbols):
                tv_link = get_tradingview_link(symbol)
                base = symbol.split('/')[0]
                # فقط نام ارز با لینک - بدون قیمت و ریسک
                msg += f"  ➕ <a href='{tv_link}'>{base}/USDT</a>\n"
            msg += "\n"
        
        if removed_symbols:
            msg += f"🔴 <b>REMOVED ({len(removed_symbols)}):</b>\n"
            for symbol in sorted(removed_symbols):
                base = symbol.split('/')[0]
                msg += f"  ➖ {base}/USDT\n"
            msg += "\n"
    
    # بیشترین تغییرات قیمت
    if previous_data and new_data:
        price_changes = []
        for symbol, data in new_data.items():
            if symbol in previous_data and previous_data[symbol]['price'] > 0:
                old_price = previous_data[symbol]['price']
                new_price = data['price']
                change_pct = ((new_price - old_price) / old_price) * 100
                price_changes.append({
                    'symbol': symbol,
                    'change': change_pct,
                    'old_price': old_price,
                    'new_price': new_price
                })
        
        if price_changes:
            price_changes.sort(key=lambda x: x['change'], reverse=True)
            
            msg += "━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"📈 <b>TOP PRICE MOVERS</b>\n\n"
            
            msg += f"🟢 <b>Biggest Gainers:</b>\n"
            for item in price_changes[:3]:
                base = item['symbol'].split('/')[0]
                tv_link = get_tradingview_link(item['symbol'])
                msg += f"  📈 <a href='{tv_link}'>{base}</a>: {item['change']:+.2f}% (${format_number(item['old_price'])} → ${format_number(item['new_price'])})\n"
            
            losers = sorted(price_changes, key=lambda x: x['change'])[:3]
            if losers and losers[0]['change'] < 0:
                msg += f"\n🔴 <b>Biggest Losers:</b>\n"
                for item in losers:
                    base = item['symbol'].split('/')[0]
                    tv_link = get_tradingview_link(item['symbol'])
                    msg += f"  📉 <a href='{tv_link}'>{base}</a>: {item['change']:+.2f}% (${format_number(item['old_price'])} → ${format_number(item['new_price'])})\n"
            
            msg += "\n"
    
    # تحلیل ریسک
    if new_data:
        sorted_by_risk = sorted(new_data.items(), key=lambda x: x[1].get('risk', 0), reverse=True)
        
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"⚠️ <b>RISK ANALYSIS</b>\n\n"
        
        msg += f"🔥 <b>Highest Risk (EMA50 vs EMA200):</b>\n"
        for symbol, data in sorted_by_risk[:3]:
            base = symbol.split('/')[0]
            tv_link = get_tradingview_link(symbol)
            risk = data.get('risk', 0)
            msg += f"  ⚡ <a href='{tv_link}'>{base}</a>: {risk}%\n"
        
        msg += f"\n💚 <b>Lowest Risk:</b>\n"
        for symbol, data in sorted_by_risk[-3:]:
            base = symbol.split('/')[0]
            tv_link = get_tradingview_link(symbol)
            risk = data.get('risk', 0)
            msg += f"  ✅ <a href='{tv_link}'>{base}</a>: {risk}%\n"
        
        msg += "\n"
    
    # لیست فعلی - فقط 3 ارز
    if new_data:
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📋 <b>CURRENT LIST (Top 3)</b>\n\n"
        
        sorted_list = sorted(new_data.items(), key=lambda x: x[1].get('risk', 0))
        
        for i, (symbol, data) in enumerate(sorted_list[:3], 1):
            base = symbol.split('/')[0]
            tv_link = get_tradingview_link(symbol)
            # فقط نام ارز با لینک - بدون قیمت و ریسک
            msg += f"{i}. <a href='{tv_link}'>{base}</a>\n"
        
        if len(new_data) > 3:
            msg += f"\n<i>... and {len(new_data) - 3} more coins</i>\n"
    
    msg += "\n━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🔗 <a href='https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit'>📊 View Full Data in Google Sheet</a>"
    
    send_telegram(msg)


def scan_xt_futures():
    print("🔄 Connecting to XT.com Futures market...")

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
        total_scanned = len(futures_pairs)
        print(f"✅ Found {total_scanned} active futures pairs on XT")
    except Exception as e:
        print(f"❌ Error connecting to XT: {e}")
        return

    print("⏳ Checking daily and hourly filters...\n")

    # خواندن داده‌های قبلی
    previous_data = get_previous_data()
    previous_symbols = set(previous_data.keys())
    print(f"📋 Previous scan: {len(previous_symbols)} coins")

    results = []
    skipped_non_ascii = 0

    for symbol in tqdm(futures_pairs, desc="📊 Scanning futures market"):
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
            ema50_1h = calculate_ema(df_1h['close'], 50)
            ema200_1h = calculate_ema(df_1h['close'], 200)

            if current_price > ema50_1h > ema200_1h:
                risk_pct = ((ema50_1h - ema200_1h) / ema200_1h) * 100
                tv_link = get_tradingview_link(symbol)

                results.append({
                    'Symbol': symbol,
                    'Price ($)': round(current_price, 8),
                    'EMA50 ($)': round(ema50_1h, 8),
                    'EMA200 ($)': round(ema200_1h, 8),
                    'Risk %': round(risk_pct, 2),
                    'TradingView Link': tv_link
                })

            time.sleep(0.2)

        except Exception:
            continue

    if skipped_non_ascii > 0:
        print(f"\n⏭️ {skipped_non_ascii} coins skipped (non-ASCII characters)")

    if not results:
        print("\n⚠️ No coins found with these conditions")
        send_telegram(f"⚠️ <b>XT Scanner Alert</b>\n\nNo coins found with current filters.\nTime: {get_iran_shamsi_timestamp()}")
        return

    df = pd.DataFrame(results)
    df = df.sort_values('Risk %', ascending=True).reset_index(drop=True)

    print("\n" + "="*70)
    print(f"✅ Scan complete — {len(df)} coins selected")
    print("="*70)

    # نوشتن در گوگل شیت (بهینه)
    write_to_google_sheet(results)
    
    # محاسبه تغییرات
    current_symbols = set(df['Symbol'].tolist())
    added_symbols = current_symbols - previous_symbols
    removed_symbols = previous_symbols - current_symbols
    
    # ساخت دیکشنری داده‌های جدید
    new_data = {}
    for _, row in df.iterrows():
        new_data[row['Symbol']] = {
            'price': row['Price ($)'],
            'ema50': row['EMA50 ($)'],
            'ema200': row['EMA200 ($)'],
            'risk': row['Risk %']
        }
    
    print(f"\n📊 Changes:")
    print(f"  ➕ Added: {len(added_symbols)}")
    print(f"  ➖ Removed: {len(removed_symbols)}")
    
    # ارسال گزارش به تلگرام
    send_telegram_report(total_scanned, len(df), new_data, previous_data, added_symbols, removed_symbols)
    
    print(f"📅 Timestamp: {get_iran_shamsi_timestamp()}")


if __name__ == "__main__":
    scan_xt_futures()
