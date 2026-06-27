from flask import Flask, jsonify, request
import ccxt
import pandas as pd
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# ==========================================
# توابع کمکی
# ==========================================

def calculate_ema(data, period):
    """محاسبه EMA با استفاده از pandas"""
    return data.ewm(span=period, adjust=False).mean()

def get_tradingview_link(symbol):
    """ساخت لینک TradingView برای فیوچرز XT"""
    # فرمت استاندارد XT در تریدینگ ویو: XT:BTCUSDT
    base = symbol.split('/')[0]
    tv_symbol = f"XT:{base}USDT"
    encoded_symbol = urllib.parse.quote(tv_symbol)
    return f"https://www.tradingview.com/chart/?symbol={encoded_symbol}"

# ==========================================
# اندپوینت ۱: فیلتر کردن کل فیوچرز (D1 و H1)
# ==========================================
@app.route('/api/filter_futures', methods=['POST'])
def filter_futures():
    try:
        # اتصال به صرافی XT (بخش فیوچرز)
        exchange = ccxt.xt({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        markets = exchange.load_markets()
        
        # دریافت فقط جفت‌ارزهای فعال فیوچرز که به USDT ختم می‌شوند
        futures_pairs = [
            symbol for symbol, market in markets.items()
            if market.get('swap') and market.get('active') and symbol.endswith('/USDT:USDT')
        ]
        
        results = []
        
        # تابع پردازش یک نماد (برای اجرای موازی)
        def process_symbol(symbol):
            try:
                # --- بررسی تایم‌فریم روزانه (D1) ---
                ohlcv_1d = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=100)
                if len(ohlcv_1d) < 50: return None
                
                df_1d = pd.DataFrame(ohlcv_1d, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                price_1d = df_1d['close'].iloc[-1]
                ema50_1d = calculate_ema(df_1d['close'], 50).iloc[-1]
                
                # شرط اول: Price > EMA(50) در روزانه
                if price_1d <= ema50_1d: return None
                
                # --- بررسی تایم‌فریم ساعتی (H1) ---
                ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
                if len(ohlcv_1h) < 200: return None
                
                df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                price_1h = df_1h['close'].iloc[-1]
                ema50_1h = calculate_ema(df_1h['close'], 50).iloc[-1]
                ema200_1h = calculate_ema(df_1h['close'], 200).iloc[-1]
                
                # شرط دوم: Price > EMA(50) > EMA(200) در ساعتی
                if price_1h > ema50_1h > ema200_1h:
                    return {
                        'Symbol': symbol,
                        'Price': round(price_1h, 8),
                        'EMA50_H1': round(ema50_1h, 8),
                        'EMA200_H1': round(ema200_1h, 8),
                        'Distance%': round(((price_1h - ema50_1h) / ema50_1h) * 100, 2),
                        'TradingView Link': get_tradingview_link(symbol)
                    }
                return None
            except Exception:
                return None

        # اجرای موازی (۱۰ ترید همزمان) برای جلوگیری از Timeout در n8n
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(process_symbol, sym): sym for sym in futures_pairs}
            for future in as_completed(futures):
                res = future.result()
                if res:
                    results.append(res)
                
        # مرتب‌سازی بر اساس بیشترین فاصله از EMA50
        results.sort(key=lambda x: x['Distance%'], reverse=True)
        
        return jsonify({
            "status": "success",
            "count": len(results),
            "data": results
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# اندپوینت ۲: بررسی کراس ۵ دقیقه (ورودی از n8n)
# ==========================================
@app.route('/api/check_5m_crossover', methods=['POST'])
def check_5m_crossover():
    data = request.get_json()
    
    # اعتبارسنجی ورودی
    if not data or 'symbols' not in data:
        return jsonify({"error": "symbols list is required"}), 400
    
    symbols = data['symbols']
    if not isinstance(symbols, list) or len(symbols) == 0:
        return jsonify({"error": "symbols must be a non-empty list"}), 400
        
    try:
        exchange = ccxt.xt({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        
        crossovers = []
        
        # تابع بررسی کراس برای یک نماد
        def process_crossover(symbol):
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=250)
                if len(ohlcv) < 200: return None
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                ema50 = calculate_ema(df['close'], 50)
                ema200 = calculate_ema(df['close'], 200)
                
                # بررسی ۳ کندل اخیر (۱۵ دقیقه گذشته) برای پیدا کردن کراس
                for j in range(-3, 0):
                    e50_cur = ema50.iloc[j]
                    e200_cur = ema200.iloc[j]
                    e50_prv = ema50.iloc[j-1]
                    e200_prv = ema200.iloc[j-1]
                    
                    # Cross Up (BULLISH): قبلاً EMA50 زیر EMA200 بوده، الان رفته بالا
                    if e50_prv <= e200_prv and e50_cur > e200_cur:
                        return {
                            'symbol': symbol,
                            'cross': 'BULLISH',
                            'price': round(df['close'].iloc[-1], 8),
                            'ema50': round(e50_cur, 8),
                            'ema200': round(e200_cur, 8),
                            'tradingview_link': get_tradingview_link(symbol)
                        }
                    # Cross Down (BEARISH): قبلاً EMA50 بالای EMA200 بوده، الان رفته پایین
                    if e50_prv >= e200_prv and e50_cur < e200_cur:
                        return {
                            'symbol': symbol,
                            'cross': 'BEARISH',
                            'price': round(df['close'].iloc[-1], 8),
                            'ema50': round(e50_cur, 8),
                            'ema200': round(e200_cur, 8),
                            'tradingview_link': get_tradingview_link(symbol)
                        }
                return None
            except Exception:
                return None

        # اجرای موازی برای سرعت بیشتر
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(process_crossover, sym): sym for sym in symbols}
            for future in as_completed(futures):
                res = future.result()
                if res:
                    crossovers.append(res)
                    
        return jsonify({
            "status": "success",
            "count": len(crossovers),
            "crossovers": crossovers
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# اجرای سرور
# ==========================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
