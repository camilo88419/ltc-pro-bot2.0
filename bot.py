import time, io, requests, numpy as np, pandas as pd, matplotlib.pyplot as plt, threading
from datetime import datetime, timezone

# === CONFIG ===
TOKEN   = "8190184114:AAFVwCQDkvZjEOKppELJzYXaCOSvF3LrLGY"
CHAT_ID = "1545010843"
SYMBOL  = "LTCUSDT"
BINANCE_URL = "https://api.binance.com/api/v3/klines"
ANALYSIS_INTERVAL_SEC = 45  # revisar cada 45 segundos

# === FUNCIONES BASE ===
def get_klines(symbol, interval, limit=500):
    r = requests.get(BINANCE_URL, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
    r.raise_for_status()
    df = pd.DataFrame(r.json(), columns=[
        "open_time","open","high","low","close","volume","close_time",
        "qav","num_trades","taker_base_vol","taker_quote_vol","ignore"
    ])
    df[["open","high","low","close","volume","taker_quote_vol"]] = df[["open","high","low","close","volume","taker_quote_vol"]].astype(float)
    df["vol_usdt"] = df["taker_quote_vol"]
    df["close_dt"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df

def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(series, n=7):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    return 100 - (100 / (1 + rs))

def atr(df, n=14):
    tr = np.maximum(df["high"] - df["low"],
                    np.maximum(abs(df["high"] - df["close"].shift()),
                               abs(df["low"] - df["close"].shift())))
    return tr.rolling(n).mean()

# === TELEGRAM ===
def send_msg(t):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": t, "parse_mode":"Markdown"})

def send_img(img, caption):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", img, "image/png")}
    data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode":"Markdown"}
    requests.post(url, data=data, files=files)

# === ANÁLISIS ===
def analyze():
    d1, d5, d15 = get_klines(SYMBOL, "1m", 500), get_klines(SYMBOL, "5m", 500), get_klines(SYMBOL, "15m", 200)
    for d in (d1, d5, d15):
        d["ema9"], d["ema25"], d["ema99"] = ema(d["close"],9), ema(d["close"],25), ema(d["close"],99)
        d["rsi7"], d["atr"] = rsi(d["close"]), atr(d)

    # Filtros macro
    trend_up = d15["ema25"].iloc[-1] > d15["ema99"].iloc[-1]
    trend_dn = d15["ema25"].iloc[-1] < d15["ema99"].iloc[-1]

    # Filtros 5m
    timing_up = (d5["ema9"].iloc[-1] > d5["ema25"].iloc[-1]) and (d5["rsi7"].iloc[-1] > 55)
    timing_dn = (d5["ema9"].iloc[-1] < d5["ema25"].iloc[-1]) and (d5["rsi7"].iloc[-1] < 45)

    # Filtros 1m
    d = d1
    vol_avg = d["vol_usdt"].tail(20).mean()
    vol_ok = d["vol_usdt"].iloc[-1] > vol_avg * 1.1
    atr_ok = d["atr"].iloc[-1] > d["atr"].tail(50).mean()
    impulse = abs(d["close"].iloc[-1]-d["open"].iloc[-1]) > 0.7*(d["high"].iloc[-1]-d["low"].iloc[-1])

    long_cond = trend_up and timing_up and d["rsi7"].iloc[-1]>55 and vol_ok and atr_ok and impulse
    short_cond= trend_dn and timing_dn and d["rsi7"].iloc[-1]<45 and vol_ok and atr_ok and impulse

    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    bias = (1 if trend_up else -1, 1 if timing_up else -1, 1 if d["ema9"].iloc[-1]>d["ema25"].iloc[-1] else -1)
    conf = int((sum(1 for x in bias if x==1)/3)*100)

    if long_cond:
        text = f"🟢 *Señal LONG [{SYMBOL}]* {ts}\nPrecio: {d['close'].iloc[-1]:.2f} USDT\nRSI: {d['rsi7'].iloc[-1]:.1f} | Vol: {d['vol_usdt'].iloc[-1]/1000:.1f}K USDT\n🎯 TP: {d['close'].iloc[-1]+0.25:.2f} | 🛑 SL: {d['close'].iloc[-1]-0.25:.2f}"
    elif short_cond:
        text = f"🔴 *Señal SHORT [{SYMBOL}]* {ts}\nPrecio: {d['close'].iloc[-1]:.2f} USDT\nRSI: {d['rsi7'].iloc[-1]:.1f} | Vol: {d['vol_usdt'].iloc[-1]/1000:.1f}K USDT\n🎯 TP: {d['close'].iloc[-1]-0.25:.2f} | 🛑 SL: {d['close'].iloc[-1]+0.25:.2f}"
    else:
        text = f"📊 {SYMBOL} — Sin señal (Conf {conf}%)  {ts}\nPrecio: {d['close'].iloc[-1]:.2f} | RSI1m: {d['rsi7'].iloc[-1]:.1f}\nVol: {d['vol_usdt'].iloc[-1]/1000:.1f}K USDT | Bias(15/5/1m): {bias}"

    # === GRAFICO ===
    fig, ax1 = plt.subplots(figsize=(12,6))
    d[-150:].plot(x="close_dt", y="close", ax=ax1, label="Close", color="white", lw=1.4)
    d[-150:].plot(x="close_dt", y="ema9",  ax=ax1, lw=1.0)
    d[-150:].plot(x="close_dt", y="ema25", ax=ax1, lw=1.0)
    d[-150:].plot(x="close_dt", y="ema99", ax=ax1, lw=1.0)
    ax1.grid(True, alpha=0.25); ax1.legend(); ax1.set_title(f"{SYMBOL} — EMAs + RSI (1m)")

    ax2 = ax1.twinx()
    ax2.plot(d["close_dt"].iloc[-150:], d["rsi7"].iloc[-150:], color="violet", lw=0.8)
    ax2.axhline(70, ls="--", lw=0.8, color="r"); ax2.axhline(30, ls="--", lw=0.8, color="g")
    ax2.set_ylim(0,100)

    buf = io.BytesIO()
    plt.tight_layout(); plt.savefig(buf, format="png", dpi=120, facecolor="black")
    plt.close(fig); buf.seek(0)

    return text, buf

# === LOOP PRINCIPAL ===
def main_loop():
    while not stop_flag.is_set():
        try:
            text, img = analyze()
            send_img(img, text)
        except Exception as e:
            send_msg(f"⚠️ Error: {e}")
        time.sleep(ANALYSIS_INTERVAL_SEC)

# === CONTROL DESDE TELEGRAM ===
bot_active = False
stop_flag = threading.Event()

def check_commands():
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        r = requests.get(url, timeout=10)
        updates = r.json().get("result", [])
        if not updates:
            return None
        return updates[-1]["message"]["text"].strip().lower()
    except:
        return None

def command_listener():
    global bot_active
    send_msg("🤖 Bot online. Usa /startbot para iniciar o /stopbot para detener.")
    last_cmd = None
    while True:
        cmd = check_commands()
        if cmd and cmd != last_cmd:
            last_cmd = cmd
            if cmd == "/startbot" and not bot_active:
                bot_active = True
                stop_flag.clear()
                send_msg("✅ *Bot iniciado.* Comenzando análisis cada 45s...")
                threading.Thread(target=main_loop).start()

            elif cmd == "/stopbot" and bot_active:
                bot_active = False
                stop_flag.set()
                send_msg("🛑 *Bot detenido.* No enviará más alertas.")
        time.sleep(10)

if __name__ == "__main__":
    command_listener()
