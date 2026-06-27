import ccxt
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import os
import json

SHEET_ID = os.environ['SHEET_ID']
SHEET_NAME = os.environ.get('SHEET_NAME', 'Sheet1')
GOOGLE_CREDENTIALS_JSON = os.environ['GOOGLE_CREDENTIALS_JSON']
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_IDS = os.environ['TELEGRAM_CHAT_IDS'].split(',')

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            requests.post(url, json={
                'chat_id': chat_id.strip(),
                'text': message,
                'parse_mode': 'HTML'
            }, timeout=10)
        except Exception as e:
            print(f"⚠️ خطا در ارسال تلگرام به {chat_id}: {e}")

def get_symbols_from_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    records = sheet.get_all_records()
    symbols = [row['Symbol'] for row in records if row.get('Symbol')]
    print(f"✅ {len(symbols)} symbol از شیت خونده شد")
    return symbols

def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean()

def check_crossover(exchange, symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=250)
        if len(ohlcv) < 200:
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        ema50 = calculate_ema(df['close'], 50)
        ema200 = calculate_ema(df['close'], 200)
        for j in range(-3, 0):
            e50_cur = ema50.iloc[j]
            e200_cur = ema200.iloc[j]
            e50_prv = ema50.iloc[j-1]
            e200_prv = ema200.iloc[j-1]
            if e50_prv <= e200_prv and e50_cur > e200_cur:
                return {
                    'symbol': symbol,
                    'cross': 'BULLISH',
                    'price': round(df['close'].iloc[-1], 8),
                    'ema50': round(e50_cur, 8),
                    'ema200': round(e200_cur, 8)
                }
            if e50_prv >= e200_prv and e50_cur < e200_cur:
                return {
                    'symbol': symbol,
                    'cross': 'BEARISH',
                    'price': round(df['close'].iloc[-1], 8),
                    'ema50': round(e50_cur, 8),
                    'ema200': round(e200_cur, 8)
                }
        return None
    except Exception as e:
        print(f"⚠️ خطا در {symbol}: {e}")
        return None

def main():
    symbols = get_symbols_from_sheet()
    if not symbols:
        print("❌ هیچ symbolی توی شیت نیست")
        return

    exchange = ccxt.xt({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'}
    })

    crossovers = []
    for symbol in symbols:
        result = check_crossover(exchange, symbol)
        if result:
            crossovers.append(result)
            print(f"🔔 کراس پیدا شد: {result['symbol']} - {result['cross']}")

    print(f"\n📊 نتیجه: {len(crossovers)} کراس از {len(symbols)} symbol")

    if crossovers:
        msg = f"📊 <b>EMA Crossover Alert</b>\n"
        msg += f"از {len(symbols)} symbol بررسی شد\n\n"
        for c in crossovers:
            emoji = "🟢" if c['cross'] == 'BULLISH' else "🔴"
            msg += f"{emoji} <b>{c['symbol']}</b>\n"
            msg += f"نوع: <b>{c['cross']}</b>\n"
            msg += f"قیمت: {c['price']}\n"
            msg += f"EMA50: {c['ema50']}\n"
            msg += f"EMA200: {c['ema200']}\n\n"
        send_telegram(msg)
        print("✅ پیام تلگرام ارسال شد")
    else:
        print("هیچ کراسی پیدا نشد، پیامی ارسال نشد")

if __name__ == '__main__':
    main()
