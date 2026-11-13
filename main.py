import sys
import requests
import numpy as np
import pandas as pd
import yfinance as yf
import pyqtgraph as pg

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton, QComboBox,
                             QLabel, QCheckBox, QListWidget, QStatusBar, QButtonGroup)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QRectF, QPointF
from PyQt5.QtGui import QPainter, QPicture, QColor, QBrush
from PyQt5.QtWidgets import QGraphicsRectItem

QUICK_MAP = {
    "BTC": "BTC-USD", "بیت کوین": "BTC-USD", "ETH": "ETH-USD", "اتریوم": "ETH-USD",
    "SOL": "SOL-USD", "طلا": "GC=F", "GOLD": "GC=F", "نقره": "SI=F",
    "نفت": "CL=F", "OIL": "CL=F",
}

THEMES = {
    "تیره حرفه‌ای": {"bg": "#0e1117", "panel": "#161b22", "text": "#ffffff"},
    "روشن": {"bg": "#ffffff", "panel": "#f0f0f0", "text": "#000000"},
    "آبی نیمه‌شب": {"bg": "#0a192f", "panel": "#112240", "text": "#e6f1ff"},
    "بنفش": {"bg": "#1a0b2e", "panel": "#2d1b4e", "text": "#ffffff"},
    "سبز ماتریکس": {"bg": "#001100", "panel": "#002200", "text": "#00ff88"},
}

def yahoo_search(query):
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        if data.get("quotes"):
            return data["quotes"][0]["symbol"]
    except:
        pass
    return None

def resolve_symbol(q):
    q = q.strip()
    if q in QUICK_MAP: return QUICK_MAP[q]
    if q.upper() in QUICK_MAP: return QUICK_MAP[q.upper()]
    if "/" in q:
        a, b = q.upper().split("/")
        if b in ["USDT", "USD"]: return f"{a}-USD"
        if len(a) == 3 and len(b) == 3: return f"{a}{b}=X"
    return q.upper()

def fetch_data(query, timeframe):
    symbol = resolve_symbol(query)
    mapping = {
        "1m": ("7d", "1m"), "5m": ("60d", "5m"), "15m": ("60d", "15m"),
        "30m": ("60d", "30m"), "1h": ("730d", "60m"), "4h": ("730d", "60m"), "1d": ("5y", "1d"),
    }
    period, interval = mapping.get(timeframe, ("60d", "15m"))
    df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
    if df.empty:
        found = yahoo_search(query)
        if found:
            symbol = found
            df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
    if df.empty:
        raise Exception(f"نماد پیدا نشد: {query} - مثال: BTC, AAPL, EURUSD=X, BABA, 0700.HK")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
    if timeframe == "4h":
        df = df.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    return symbol, df

def analyze(df):
    df = df.copy()
    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    ema12 = df['close'].ewm(span=12).mean(); ema26 = df['close'].ewm(span=26).mean()
    df['macd'] = ema12 - ema26; df['macd_s'] = df['macd'].ewm(span=9).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss))

    last = df.iloc[-1]; price = last['close']
    score = 0; reasons = []

    # EMA + MACD + RSI
    if last['ema20'] > last['ema50']: score += 1; reasons.append("✅ روند صعودی EMA20 > EMA50")
    else: score -= 1; reasons.append("❌ روند نزولی EMA20 < EMA50")
    if last['rsi'] < 30: score += 1; reasons.append(f"✅ RSI اشباع فروش: {last['rsi']:.1f}")
    elif last['rsi'] > 70: score -= 1; reasons.append(f"❌ RSI اشباع خرید: {last['rsi']:.1f}")
    else: reasons.append(f"⚪ RSI: {last['rsi']:.1f}")
    if last['macd'] > last['macd_s']: score += 1; reasons.append("✅ MACD صعودی")
    else: score -= 1; reasons.append("❌ MACD نزولی")

    # Swing + BOS / CHoCH اسمارت مانی
    highs = df['high'].values; lows = df['low'].values
    swing_high = swing_low = None
    for i in range(5, len(df)-5):
        if highs[i] == highs[i-5:i+6].max(): swing_high = highs[i]
        if lows[i] == lows[i-5:i+6].min(): swing_low = lows[i]
    if swing_high and price > swing_high:
        score += 2; reasons.append("🚀 شکست سقف - BOS صعودی (Smart Money)")
        if df.iloc[-10]['ema20'] < df.iloc[-10]['ema50']: reasons.append("🔥 CHoCH صعودی - تغییر ساختار بازار")
    if swing_low and price < swing_low:
        score -= 2; reasons.append("🔻 شکست کف - BOS نزولی (Smart Money)")
        if df.iloc[-10]['ema20'] > df.iloc[-10]['ema50']: reasons.append("🔥 CHoCH نزولی - تغییر ساختار بازار")

    # Order Block
    bull_ob = bear_ob = None
    for i in range(len(df)-60, len(df)-3):
        if i < 0: continue
        if df.iloc[i]['close'] < df.iloc[i]['open'] and df.iloc[i+3]['close'] > df.iloc[i]['high']:
            bull_ob = (df.iloc[i]['low'], df.iloc[i]['high'])
        if df.iloc[i]['close'] > df.iloc[i]['open'] and df.iloc[i+3]['close'] < df.iloc[i]['low']:
            bear_ob = (df.iloc[i]['low'], df.iloc[i]['high'])
    if bull_ob: score += 1; reasons.append(f"🟩 Order Block صعودی: {bull_ob[0]:.2f} - {bull_ob[1]:.2f}")
    if bear_ob: score -= 1; reasons.append(f"🟥 Order Block نزولی: {bear_ob[0]:.2f} - {bear_ob[1]:.2f}")

    # FVG
    bull_fvg = bear_fvg = None
    for i in range(2, len(df)):
        if df.iloc[i]['low'] > df.iloc[i-2]['high']: bull_fvg = (df.iloc[i-2]['high'], df.iloc[i]['low'])
        if df.iloc[i]['high'] < df.iloc[i-2]['low']: bear_fvg = (df.iloc[i]['high'], df.iloc[i-2]['low'])
    if bull_fvg: score += 1; reasons.append("🟢 FVG صعودی فعال")
    if bear_fvg: score -= 1; reasons.append("🔴 FVG نزولی فعال")

    # Fibonacci
    if swing_high and swing_low and swing_high > swing_low:
        fib618 = swing_low + 0.618 * (swing_high - swing_low)
        reasons.append(f"📐 فیبوناچی 0.618: {fib618:,.2f}")
        if abs(price - fib618) / price < 0.015: score += 1; reasons.append("✅ قیمت نزدیک حمایت فیبوناچی 0.618")

    if score >= 4: signal = "🟢 خرید قوی / LONG"
    elif score >= 2: signal = "🟢 خرید / LONG"
    elif score <= -4: signal = "🔴 فروش قوی / SHORT"
    elif score <= -2: signal = "🔴 فروش / SHORT"
    else: signal = "⚪ خنثی - صبر کن"

    # مسیر فرضی آینده
    volatility = df['close'].pct_change().std()
    if np.isnan(volatility): volatility = 0.01
    closes = df['close'].values[-30:]
    slope = np.polyfit(range(len(closes)), closes, 1)[0] if len(closes) > 5 else 0
    drift = slope + (score * price * 0.0006)
    future = []
    for i in range(1, 21):
        wave = np.sin(i/3.0) * volatility * price * 0.3
        scenario = 0
        if score >= 2: scenario = -price*0.0015*i if i <= 5 else price*0.002*(i-5)
        elif score <= -2: scenario = price*0.0015*i if i <= 5 else -price*0.002*(i-5)
        future.append(max(price + drift*i + wave + scenario, 0.0001))

    return {"score": score, "signal": signal, "reasons": reasons,
            "future": future, "bull_ob": bull_ob, "bear_ob": bear_ob,
            "bull_fvg": bull_fvg, "bear_fvg": bear_fvg}

class CandlestickItem(pg.GraphicsObject):
    def __init__(self):
        super().__init__(); self.picture = QPicture()
    def set_data(self, data):
        self.picture = QPicture(); p = QPainter(self.picture); w = 0.4
        for (t, o, c, l, h) in data:
            color = "#00c853" if c >= o else "#ff1744"
            p.setPen(pg.mkPen(color)); p.setBrush(pg.mkBrush(color))
            p.drawLine(QPointF(t, l), QPointF(t, h))
            p.drawRect(QRectF(t-w, o, w*2, c-o))
        p.end(); self.prepareGeometryChange()
    def paint(self, p, *args): p.drawPicture(0, 0, self.picture)
    def boundingRect(self): return QRectF(self.picture.boundingRect())

class Worker(QThread):
    finished = pyqtSignal(object, str, object)
    error = pyqtSignal(str)
    def __init__(self, query, tf): super().__init__(); self.query = query; self.tf = tf
    def run(self):
        try:
            symbol, df = fetch_data(self.query, self.tf)
            result = analyze(df)
            self.finished.emit(df, symbol, result)
        except Exception as e: self.error.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Money Analyzer - تحلیلگر بازار مالی")
        self.resize(1400, 800)
        self.tool_mode = "none"; self.pending_point = None
        self.drawing_items = []; self.zone_items = []; self.df = None

        central = QWidget(); self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        top = QHBoxLayout()
        self.search_box = QLineEdit(); self.search_box.setPlaceholderText("سرچ کن: BTC ، AAPL ، طلا ، EURUSD ، BABA ، 0700.HK ، 000001.SS")
        self.search_box.returnPressed.connect(self.load_data)
        search_btn = QPushButton("🔍 جستجو و تحلیل"); search_btn.clicked.connect(self.load_data)
        self.tf_combo = QComboBox(); self.tf_combo.addItems(["1m","5m","15m","30m","1h","4h","1d"]); self.tf_combo.setCurrentText("15m")
        self.tf_combo.currentTextChanged.connect(self.load_data)
        self.theme_combo = QComboBox(); self.theme_combo.addItems(list(THEMES.keys())); self.theme_combo.currentTextChanged.connect(self.apply_theme)
        self.live_check = QCheckBox("لایو 🔴"); self.live_check.setChecked(True)
        top.addWidget(self.search_box); top.addWidget(search_btn)
        top.addWidget(QLabel("تایم‌فریم:")); top.addWidget(self.tf_combo)
        top.addWidget(QLabel("تم:")); top.addWidget(self.theme_combo); top.addWidget(self.live_check)
        main_layout.addLayout(top)

        content = QHBoxLayout()
        tools = QVBoxLayout()
        self.tool_group = QButtonGroup(self)
        for name, mode in [("🖱 موس","none"),("➖ خط افقی","hline"),("➕ خط عمودی","vline"),("📈 خط روند","trend"),("📊 کانال","channel"),("⬛ مستطیل","rect")]:
            b = QPushButton(name); b.setCheckable(True); b.clicked.connect(lambda _, m=mode: self.set_tool(m))
            self.tool_group.addButton(b); tools.addWidget(b)
            if mode == "none": b.setChecked(True)
        clear_btn = QPushButton("🗑 پاک کردن رسم‌ها"); clear_btn.clicked.connect(self.clear_tools); tools.addWidget(clear_btn)
        tools.addStretch(); content.addLayout(tools)

        self.plot = pg.PlotWidget(); self.plot.showGrid(x=True, y=True, alpha=0.3); self.plot.setLabel('left', 'قیمت')
        self.candles = CandlestickItem(); self.plot.addItem(self.candles)
        self.ema20_line = self.plot.plot(pen=pg.mkPen('#FFD700', width=1.5), name="EMA20")
        self.ema50_line = self.plot.plot(pen=pg.mkPen('#00BFFF', width=1.5), name="EMA50")
        self.forecast_line = self.plot.plot(pen=pg.mkPen('#FFFF00', width=2, style=Qt.DashLine), symbol='o', symbolSize=5, symbolBrush='#FFFF00')
        self.plot.scene().sigMouseClicked.connect(self.on_chart_click)
        content.addWidget(self.plot, stretch=3)

        right = QVBoxLayout()
        self.price_label = QLabel("قیمت: -"); self.price_label.setStyleSheet("font-size:18px; font-weight:bold;")
        self.signal_label = QLabel("سیگنال: -"); self.signal_label.setStyleSheet("font-size:22px; font-weight:bold;")
        self.score_label = QLabel("امتیاز: -")
        self.reasons_list = QListWidget()
        disclaimer = QLabel("⚠️ هشدار: این برنامه فقط ابزار تحلیله و توصیه مالی نیست.\nسود و ضرر کاملاً گردن خودتونه!")
        disclaimer.setStyleSheet("color:#ff1744; font-weight:bold;"); disclaimer.setWordWrap(True)
        help_label = QLabel("مثال‌ها:\nآمریکا: AAPL, TSLA, NVDA\nچین: BABA, 0700.HK, 000001.SS, ^HSI\nکریپتو: BTC, ETH, SOL\nفارکس: EURUSD=X, EUR/USD\nطلا: GC=F | نفت: CL=F")
        help_label.setWordWrap(True)
        right.addWidget(self.price_label); right.addWidget(self.signal_label); right.addWidget(self.score_label)
        right.addWidget(QLabel("دلایل تحلیل (Smart Money / FVG / Fib):")); right.addWidget(self.reasons_list)
        right.addWidget(disclaimer); right.addWidget(help_label)
        content.addLayout(right, stretch=1)
        main_layout.addLayout(content)

        self.setStatusBar(QStatusBar()); self.statusBar().showMessage("آماده - یک نماد سرچ کن")
        self.timer = QTimer(); self.timer.setInterval(5000); self.timer.timeout.connect(self.auto_refresh); self.timer.start()
        self.apply_theme(); self.search_box.setText("BTC"); self.load_data()

    def set_tool(self, mode): self.tool_mode = mode; self.pending_point = None
    def apply_theme(self):
        t = THEMES[self.theme_combo.currentText()]
        self.plot.setBackground(t["bg"])
        self.setStyleSheet("QMainWindow{background-color:"+t["panel"]+"; color:"+t["text"]+";} QPushButton{padding:6px;} QLineEdit,QComboBox{padding:6px;}")
    def auto_refresh(self):
        if self.live_check.isChecked(): self.load_data()
    def load_data(self):
        query = self.search_box.text().strip()
        if not query: return
        self.statusBar().showMessage(f"در حال دریافت {query} ...")
        self.worker = Worker(query, self.tf_combo.currentText())
        self.worker.finished.connect(self.on_data); self.worker.error.connect(lambda e: self.statusBar().showMessage("خطا: "+e))
        self.worker.start()
    def on_data(self, df, symbol, result):
        self.df = df
        data = [(i, r['open'], r['close'], r['low'], r['high']) for i, (_, r) in enumerate(df.iterrows())]
        self.candles.set_data(data)
        ema20 = df['close'].ewm(span=20).mean(); ema50 = df['close'].ewm(span=50).mean()
        self.ema20_line.setData(list(range(len(df))), ema20.values)
        self.ema50_line.setData(list(range(len(df))), ema50.values)
        fx = list(range(len(df)-1, len(df)+len(result["future"])))
        fy = [df.iloc[-1]['close']] + result["future"]
        self.forecast_line.setData(fx, fy)

        for z in self.zone_items: self.plot.removeItem(z)
        self.zone_items = []
        for zone, color in [(result["bull_ob"], (0,255,0,45)), (result["bear_ob"], (255,0,0,45)), (result["bull_fvg"], (0,255,255,35)), (result["bear_fvg"], (255,165,0,35))]:
            if zone:
                item = pg.LinearRegionItem(values=zone, orientation='horizontal', movable=False, brush=color, pen=pg.mkPen('transparent'))
                self.plot.addItem(item); self.zone_items.append(item)

        ticks = [(i, str(df.index[i])[:16]) for i in range(0, len(df), max(1, len(df)//8))]
        self.plot.getAxis('bottom').setTicks([ticks])
        last = df.iloc[-1]
        self.price_label.setText(f"{symbol} | قیمت: {last['close']:,.2f}")
        self.signal_label.setText(result["signal"]); self.score_label.setText(f"امتیاز نهایی: {result['score']}")
        self.reasons_list.clear(); self.reasons_list.addItems(result["reasons"])
        self.statusBar().showMessage(f"آپدیت شد: {symbol} - خط زرد = مسیر فرضی آینده")

    def on_chart_click(self, ev):
        if self.tool_mode == "none": return
        vb = self.plot.getViewBox(); pos = vb.mapSceneToView(ev.scenePos()); x, y = pos.x(), pos.y()
        if self.tool_mode == "hline":
            item = pg.InfiniteLine(pos=y, angle=0, movable=True, pen=pg.mkPen('#00FFFF', width=2)); self.plot.addItem(item); self.drawing_items.append(item); return
        if self.tool_mode == "vline":
            item = pg.InfiniteLine(pos=x, angle=90, movable=True, pen=pg.mkPen('#00FFFF', width=2)); self.plot.addItem(item); self.drawing_items.append(item); return
        if self.pending_point is None:
            self.pending_point = (x, y); self.statusBar().showMessage("نقطه اول ثبت شد، نقطه دوم رو بزن"); return
        x1, y1 = self.pending_point; self.pending_point = None
        if self.tool_mode == "trend":
            item = self.plot.plot([x1, x], [y1, y], pen=pg.mkPen('#00FFFF', width=2)); self.drawing_items.append(item)
        elif self.tool_mode == "channel":
            offset = abs(y - y1) * 0.5 + (y * 0.01)
            i1 = self.plot.plot([x1, x], [y1, y], pen=pg.mkPen('#FF00FF', width=2))
            i2 = self.plot.plot([x1, x], [y1+offset, y+offset], pen=pg.mkPen('#FF00FF', width=2))
            self.drawing_items.extend([i1, i2])
        elif self.tool_mode == "rect":
            rx, ry = min(x1, x), min(y1, y)
            item = QGraphicsRectItem(rx, ry, abs(x-x1), abs(y-y1)); item.setPen(pg.mkPen('#FFFF00', width=2)); item.setBrush(QBrush(QColor(255,255,0,40)))
            self.plot.addItem(item); self.drawing_items.append(item)

    def clear_tools(self):
        for i in self.drawing_items:
            try: self.plot.removeItem(i)
            except: pass
        self.drawing_items = []

if __name__ == "__main__":
    app = QApplication(sys.argv); win = MainWindow(); win.show(); sys.exit(app.exec_())