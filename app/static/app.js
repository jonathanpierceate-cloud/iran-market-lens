(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { summary: null, gold: null, dollar: null, tepix: null, funds: [], watchlist: [], currentView: "overview" };
  const fundSortState = { key: "data_timestamp", direction: -1 };
  const nf = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
  const en = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
  const dates = new Intl.DateTimeFormat("fa-IR-u-nu-latn", { dateStyle: "medium", timeStyle: "short" });
  const text = (value, fallback = "—") => value === null || value === undefined || value === "" ? fallback : String(value);
  const num = (value, digits = 2) => value === null || value === undefined || !Number.isFinite(Number(value)) ? "—" : new Intl.NumberFormat("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(Number(value));
  const money = (value) => value === null || value === undefined || !Number.isFinite(Number(value)) ? "—" : en.format(Number(value));
  const pct = (value) => value === null || value === undefined ? "—" : `${Number(value) > 0 ? "+" : ""}${num(value)}%`;
  const toEnglishDigits = (value) => String(value ?? "")
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)))
    .replace(/٫/g, ".")
    .replace(/٬/g, ",")
    .replace(/٪/g, "%");
 const formatDate = (value) => {
   if (!value) return "—";
   const d = new Date(value);
   if (Number.isNaN(d.getTime())) return value;
   return dates.format(d);
 };
  function installEnglishDigits() {
    const root = document.body;
    if (!root) return;
    const normalizeNode = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        const next = toEnglishDigits(node.nodeValue);
        if (next !== node.nodeValue) node.nodeValue = next;
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
      let current;
      while ((current = walker.nextNode())) {
        const next = toEnglishDigits(current.nodeValue);
        if (next !== current.nodeValue) current.nodeValue = next;
      }
      ["aria-label", "title", "placeholder"].forEach((attribute) => {
        if (node.hasAttribute(attribute)) node.setAttribute(attribute, toEnglishDigits(node.getAttribute(attribute)));
      });
    };
    normalizeNode(root);
    const observer = new MutationObserver((mutations) => mutations.forEach((mutation) => mutation.addedNodes.forEach(normalizeNode)));
    observer.observe(root, { childList: true, subtree: true });
  }
 const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const trendText = (value) => ({ bullish: "صعودی", bearish: "نزولی", neutral: "خنثی", unavailable: "داده ناکافی" }[value] || "داده ناکافی");
  const statusText = (status) => ({ available: "تازه", connected: "متصل", stale: "کهنه", cached_after_source_error: "آخرین داده", failed: "خطا", not_tested: "بررسی‌نشده", unavailable: "در دسترس نیست", disabled: "غیرفعال" }[status] || status || "نامشخص");

  async function api(path, options = {}) {
    const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.error || `خطای ${response.status}`);
    return data;
  }

  function toast(message, isError = false) {
    const node = $("#toast");
    node.textContent = message;
    node.style.background = isError ? "#4b222a" : "#173451";
    node.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.classList.remove("show"), 3200);
  }

  function localDateClock() {
    const now = new Date();
    $("#clock").textContent = new Intl.DateTimeFormat("fa-IR-u-nu-latn", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tehran" }).format(now);
  }

  function freshness(node, status, timestamp) {
    if (!node) return;
    node.classList.remove("good", "stale", "bad");
    node.classList.add(status === "available" || status === "connected" ? "good" : status === "failed" || status === "stale" ? "stale" : "bad");
    node.innerHTML = `<i></i>${esc(statusText(status))}${timestamp ? ` · ${esc(formatDate(timestamp))}` : ""}`;
  }

  function changeClass(value) { return value > 0 ? "positive" : value < 0 ? "negative" : ""; }

  function marketQuote(quote, prefix) {
    const currency = prefix === "gold" ? "USD" : "IRR";
    const priceEl = $(`#${prefix}-price`);
    if (!quote || quote.price == null) {
      priceEl.textContent = "داده در دسترس نیست";
      priceEl.classList.add("unavailable-text");
      $(`#${prefix}-source`).textContent = quote?.source || "—";
      $(`#${prefix}-time`).textContent = "—";
      freshness($(`#${prefix}-freshness`), "unavailable", null);
      return;
    }
    priceEl.classList.remove("unavailable-text");
    priceEl.textContent = money(quote.price);
    const daily = quote.returns?.daily;
    const ch = $(`#${prefix}-change`);
    ch.textContent = pct(daily);
    ch.className = `change-pill ${daily === null ? "" : changeClass(daily)}`;
    $(`#${prefix}-source`).textContent = quote.source || "—";
    $(`#${prefix}-time`).textContent = formatDate(quote.data_timestamp);
    freshness($(`#${prefix}-freshness`), quote.status, quote.data_timestamp);
    const trend = $(`#${prefix}-trend`);
    trend.textContent = trendText(quote.analysis?.medium_term_trend);
    trend.className = `trend ${quote.analysis?.medium_term_trend || "neutral"}`;
    const scoreEl = $(`#${prefix}-score`);
    if (scoreEl) scoreEl.textContent = quote.analysis?.technical_score == null ? "—" : `${num(quote.analysis.technical_score, 0)} / ۱۰۰`;
  }

  function drawChart(canvas, bars, { color = "#e4b34e", mode = "candles", volume = false } = {}) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(rect.width * dpr); canvas.height = Math.floor(rect.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = rect.width, h = rect.height, pad = { top: 9, right: 42, bottom: volume ? 20 : 17, left: 3 };
    ctx.clearRect(0, 0, w, h);
    const valid = (bars || []).filter((b) => b.close != null).slice(-180);
    if (!valid.length) return;
    const max = Math.max(...valid.map((b) => Math.max(Number(b.high ?? b.close), Number(b.close))));
    const min = Math.min(...valid.map((b) => Math.min(Number(b.low ?? b.close), Number(b.close))));
    const spread = max - min || Math.max(1, max * .01);
    const top = pad.top, bottom = h - pad.bottom;
    const y = (v) => bottom - ((Number(v) - min) / spread) * (bottom - top);
    ctx.strokeStyle = "rgba(126,146,170,.13)"; ctx.lineWidth = 1;
    ctx.fillStyle = "#71839a"; ctx.font = "8px DM Mono, monospace"; ctx.textAlign = "left";
    for (let i = 0; i < 4; i++) {
      const yy = top + i * (bottom - top) / 3;
      ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(w - pad.right + 3, yy); ctx.stroke();
      ctx.fillText(en.format(max - (spread * i / 3)), w - pad.right + 7, yy + 3);
    }
    const chartW = w - pad.right, slot = chartW / Math.max(1, valid.length);
    if (mode === "candles") {
      valid.forEach((bar, i) => {
        const x = i * slot + slot / 2;
        const open = Number(bar.open ?? (i ? valid[i - 1].close : bar.close));
        const close = Number(bar.close), high = Number(bar.high ?? Math.max(open, close)), low = Number(bar.low ?? Math.min(open, close));
        const up = close >= open;
        ctx.strokeStyle = up ? "#52c59a" : "#ec7787"; ctx.fillStyle = ctx.strokeStyle;
        ctx.beginPath(); ctx.moveTo(x, y(high)); ctx.lineTo(x, y(low)); ctx.stroke();
        const candleW = Math.max(1.5, Math.min(7, slot * .57));
        const bodyTop = Math.min(y(open), y(close)), bodyH = Math.max(1, Math.abs(y(open) - y(close)));
        ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyH);
        if (volume && bar.volume) {
          const volumeMax = Math.max(...valid.map((v) => Number(v.volume || 0))) || 1;
          const volumeHeight = 10 * Number(bar.volume) / volumeMax;
          ctx.globalAlpha = .35; ctx.fillRect(x - candleW / 2, h - 13 - volumeHeight, candleW, volumeHeight); ctx.globalAlpha = 1;
        }
      });
    } else {
      const gradient = ctx.createLinearGradient(0, top, 0, bottom);
      gradient.addColorStop(0, `${color}30`); gradient.addColorStop(1, `${color}00`);
      ctx.beginPath(); valid.forEach((bar, i) => { const x = i * slot + slot / 2; i ? ctx.lineTo(x, y(bar.close)) : ctx.moveTo(x, y(bar.close)); });
      ctx.lineTo((valid.length - 1) * slot + slot / 2, bottom); ctx.lineTo(slot / 2, bottom); ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
      ctx.beginPath(); valid.forEach((bar, i) => { const x = i * slot + slot / 2; i ? ctx.lineTo(x, y(bar.close)) : ctx.moveTo(x, y(bar.close)); });
      ctx.strokeStyle = color; ctx.lineWidth = 1.7; ctx.stroke();
    }
    const dateLabel = new Intl.DateTimeFormat("fa-IR-u-nu-latn", { month: "short", day: "numeric" });
    const dateTicks = [...new Set([0, Math.floor((valid.length - 1) / 2), valid.length - 1])];
    ctx.fillStyle = "#8192a8"; ctx.font = "11px Tahoma, sans-serif";
    dateTicks.forEach((i, tick) => {
      const stamp = new Date(valid[i].timestamp);
      if (Number.isNaN(stamp.getTime())) return;
      ctx.textAlign = tick === 0 ? "left" : tick === dateTicks.length - 1 ? "right" : "center";
      ctx.fillText(dateLabel.format(stamp), i * slot + slot / 2, h - 3);
    });
    canvas.onmousemove = (event) => {
      const x = event.offsetX, i = Math.max(0, Math.min(valid.length - 1, Math.floor(x / slot)));
      const bar = valid[i];
      canvas.title = `${formatDate(bar.timestamp)} · ${en.format(bar.close)}`;
      const tip = canvas.dataset.tipTarget && $(canvas.dataset.tipTarget);
      if (tip) tip.textContent = `${formatDate(bar.timestamp)} · ${en.format(bar.close)}`;
    };
  }

  function renderMetrics(prefix, quote) {
    const target = $(`#${prefix}-metrics`);
    if (!quote?.price) { target.innerHTML = `<div class="metric-cell"><span>وضعیت</span><b>داده در دسترس نیست</b></div>`; return; }
    const labels = [["Open", "بازشدن", quote.open], ["High", "بیشینه", quote.high], ["Low", "کمینه", quote.low], ["Daily", "روزانه", quote.returns?.daily], ["1M", "ماهانه", quote.returns?.monthly], ["1Y", "یک‌ساله", quote.returns?.one_year]];
    target.innerHTML = labels.map(([key, label, value]) => `<div class="metric-cell"><span>${label}</span><b>${key === "Daily" || key === "1M" || key === "1Y" ? pct(value) : value == null ? "—" : money(value)}</b></div>`).join("");
  }

  const indicatorFa = { "RSI(14)": "شاخص قدرت نسبی", "MFI(14)": "شاخص جریان پول", "CCI(14)": "شاخص کانال کالا", "WR(14)": "Williams %R", "SO(14)": "نوسان‌گر تصادفی", "Aroon(25)": "آرون", "ARRON(25)": "آرون", "ADX(14)": "قدرت روند", "AO(5,34)": "شتاب Awesome", "StochRSI(14)": "استوکاستیک RSI", "MACD(12,26,9)": "مکدی", "MTM(6)": "شتاب قیمت", "Ichimoku(9,26,52,26)": "ایچیموکو", "ATR(14)": "دامنه واقعی میانگین", "KELTNER(16)": "کانال کلتنر", "BB(20)": "باند بولینگر", "VRSI(14)": "RSI حجم", "VMACD(12,26)": "مکدی حجم", "OBV(20)": "حجم تعادلی", "RV(15)": "نوسان تاریخی ۱۵روزه", "RV(30)": "نوسان تاریخی ۳۰روزه", "RV(90)": "نوسان تاریخی ۹۰روزه", "SM(15)": "شاخص SM (تعریف نشده)" };
  const factorFa = { trend: "روند", momentum: "شتاب", moving_averages: "میانگین‌ها", volume: "حجم", volatility: "نوسان", oscillators: "نوسان‌گرها", support_resistance: "حمایت و مقاومت" };
  const signalFa = { strong_buy: "بررسی خرید · قوی", buy: "بررسی خرید", hold: "انتظار / نگهداری", sell: "احتیاط", strong_sell: "ریسک بالا", unavailable: "داده ناکافی" };

  function indicatorMeaning(key, value) {
    if (/^(EMA|SMA)\(/.test(key)) return `میانگین قیمت در دوره ${key.match(/\d+/)?.[0] || "مشخص"}؛ قیمت بالاتر از آن معمولاً به نفع روند صعودی است.`;
    const meanings = {
      "RSI(14)": "قدرت حرکت قیمت در ۱۴ دوره؛ زیر ۳۰ فروش‌زدگی و بالای ۷۰ خریدزدگی است. این وضعیت به‌تنهایی سیگنال معامله نیست.",
      "MFI(14)": "فشار خرید و فروش با درنظرگرفتن حجم؛ زیر ۲۰ فروش‌زدگی و بالای ۸۰ خریدزدگی را نشان می‌دهد.",
      "CCI(14)": "فاصله قیمت از میانگین؛ بالای ۱۰۰ حرکت قوی و زیر منفی ۱۰۰ ضعف یا فروش‌زدگی را نشان می‌دهد.",
      "WR(14)": "جایگاه قیمت در دامنه ۱۴ دوره؛ بالای منفی ۲۰ خریدزدگی و زیر منفی ۸۰ فروش‌زدگی است.",
      "SO(14)": "جایگاه قیمت در دامنه اخیر؛ بالای ۸۰ خریدزدگی و زیر ۲۰ فروش‌زدگی است.",
      "Aroon(25)": "تازگی ثبت سقف و کف ۲۵ دوره را می‌سنجد؛ خط بالاتر جهت غالب را نشان می‌دهد.",
      "ARRON(25)": "تازگی ثبت سقف و کف ۲۵ دوره را می‌سنجد؛ خط بالاتر جهت غالب را نشان می‌دهد.",
      "ADX(14)": "قدرت روند را می‌سنجد، نه جهت آن؛ بالای ۲۵ معمولاً روند قوی‌تر است. جهت از +DI و −DI خوانده می‌شود.",
      "AO(5,34)": "شتاب کوتاه‌مدت در برابر بلندمدت؛ مثبت به نفع شتاب صعودی و منفی نشانه شتاب نزولی است.",
      "StochRSI(14)": "سرعت تغییر RSI؛ بالای ۸۰ یا زیر ۲۰ یعنی حرکت به ناحیه افراطی رسیده و احتمال نوسان برگشتی بیشتر است.",
      "MACD(12,26,9)": "اختلاف میانگین‌های نمایی؛ هیستوگرام مثبت یعنی خط MACD بالای خط سیگنال و منفی یعنی پایین آن است.",
      "MTM(6)": "تغییر قیمت نسبت به ۶ دوره قبل؛ مثبت یعنی شتاب رو به بالا و منفی یعنی شتاب رو به پایین.",
      "Ichimoku(9,26,52,26)": "خط عددی مقدار تنکان است؛ وضعیت روند را با جای قیمت نسبت به ابر و تقاطع تنکان/کیجون بسنجید.",
      "ATR(14)": "میانگین دامنه نوسان قیمت؛ عدد بزرگ‌تر یعنی حرکت روزانه بیشتر، نه جهت صعود یا نزول.",
      "KELTNER(16)": "میانگین میانی و کانال نوسان؛ خروج از کانال می‌تواند حرکت پرقدرت یا کشیدگی قیمت باشد.",
      "BB(20)": "میانگین میانی و باند نوسان؛ نزدیک یا بیرون باند بودن، کشیدگی حرکت را نشان می‌دهد و جهت قطعی نیست.",
      "VRSI(14)": "RSI محاسبه‌شده روی حجم معاملات؛ تغییر فشار حجم را نشان می‌دهد، نه جهت مستقیم قیمت.",
      "VMACD(12,26)": "شتاب تغییر حجم؛ مثبت یعنی میانگین کوتاه حجم بالاتر از بلندمدت است.",
      "OBV(20)": "حجم تجمعی با جهت حرکت قیمت؛ مقایسه با میانگین ۲۰روزه به تأیید یا تضعیف روند کمک می‌کند.",
      "RV(15)": "نوسان تاریخی سالانه‌شده بر پایه بازده ۱۵روزه؛ مقدار بیشتر یعنی ریسک نوسان بیشتر، نه جهت خاص.",
      "RV(30)": "نوسان تاریخی سالانه‌شده بر پایه بازده ۳۰روزه؛ مقدار بیشتر یعنی ریسک نوسان بیشتر، نه جهت خاص.",
      "RV(90)": "نوسان تاریخی سالانه‌شده بر پایه بازده ۹۰روزه؛ مقدار بیشتر یعنی ریسک نوسان بیشتر، نه جهت خاص.",
      "SM(15)": "در مشخصات ارسالی، تعریف محاسباتی این شاخص روشن نبود؛ بنابراین مقدار قابل اتکا محاسبه نشده است."
    };
    return meanings[key] || value?.interpretation || "برای این شاخص تفسیر کافی ثبت نشده است.";
  }

  function indicatorNumericSummary(name, item) {
    const parts = Array.isArray(item?.value) ? item.value : Object.entries(item || {}).filter(([key, value]) => key !== "value" && Number.isFinite(Number(value))).map(([key, value]) => ({ name: key, value }));
    const values = Object.fromEntries(parts.map((part) => [String(part.name || "").toLowerCase(), Number(part.value)]));
    if (!Array.isArray(item?.value) && Number.isFinite(Number(item?.value))) values.value = Number(item.value);
    const value = (...keys) => keys.map((key) => values[String(key).toLowerCase()]).find((number) => Number.isFinite(number));
    const signal = String(item?.signal || "").toLowerCase().replace(/[^a-z]/g, "");
    const signalText = signal === "buy" || signal === "bullish" || signal === "strongbuy" ? "مثبت"
      : signal === "sell" || signal === "bearish" || signal === "strongsell" ? "منفی"
        : signal === "overbought" ? "خریدزدگی" : signal === "oversold" ? "فروش‌زدگی"
          : signal === "lowvolume" ? "حجم پایین" : signal === "highvolume" ? "حجم بالا" : "خنثی";
    const first = value("value", "rsi", "mfi", "cci", "wr", "awesome", "mtm", "rv", "sm", "vrsi", "obv");
    if (/^rsi/i.test(name) && Number.isFinite(first)) return `عدد ${num(first, 2)} است؛ ${first >= 70 ? "بالاتر از ۷۰ و در ناحیه خریدزدگی است، پس احتمال اصلاح کوتاه‌مدت وجود دارد." : first <= 30 ? "زیر ۳۰ و در ناحیه فروش‌زدگی است، پس امکان برگشت وجود دارد." : "در محدوده میانی ۳۰ تا ۷۰ است و افراط دیده نمی‌شود."}`;
    if (/^mfi/i.test(name) && Number.isFinite(first)) return `عدد ${num(first, 2)} است؛ ${first >= 80 ? "بالاتر از ۸۰ و نشان‌دهنده خریدزدگی جریان پول است." : first <= 20 ? "زیر ۲۰ و نشان‌دهنده فروش‌زدگی جریان پول است." : "در محدوده میانی جریان پول قرار دارد."}`;
    if (/^cci/i.test(name) && Number.isFinite(first)) return `عدد ${num(first, 2)} است؛ ${first >= 100 ? "بالاتر از ۱۰۰ و نشان‌دهنده حرکت قوی اما کشیده‌شده است." : first <= -100 ? "پایین‌تر از منفی ۱۰۰ و نشان‌دهنده فروش‌زدگی است." : "بین منفی ۱۰۰ و مثبت ۱۰۰ قرار دارد."}`;
    if (/^wr/i.test(name) && Number.isFinite(first)) return `عدد ${num(first, 2)} است؛ ${first >= -20 ? "نزدیک صفر و در ناحیه خریدزدگی است." : first <= -80 ? "زیر منفی ۸۰ و در ناحیه فروش‌زدگی است." : "در محدوده میانی دامنه قیمت است."}`;
    if (/^so/i.test(name)) {
      const k = value("k"), d = value("d");
      return `K=${num(k, 2)} و D=${num(d, 2)} است؛ ${k >= 80 && d >= 80 ? "هر دو بالای ۸۰ و در ناحیه خریدزدگی‌اند." : k <= 20 && d <= 20 ? "هر دو زیر ۲۰ و در ناحیه فروش‌زدگی‌اند." : k > d ? "K بالاتر از D است و شتاب کوتاه‌مدت بهتر شده." : "K پایین‌تر از D است و شتاب کوتاه‌مدت ضعیف‌تر شده."}`;
    }
    if (/aroon|arron/i.test(name)) {
      const up = value("up"), down = value("down");
      return `Aroon صعودی=${num(up, 0)} و نزولی=${num(down, 0)} است؛ ${up > down ? "برتری با روند صعودی است." : down > up ? "برتری با روند نزولی است." : "جهت روند برابر و خنثی است."}`;
    }
    if (/^adx/i.test(name) && Number.isFinite(first)) return `عدد ${num(first, 2)} است؛ ${first >= 25 ? "بالاتر از ۲۵ و نشان‌دهنده روند قدرتمندتر است." : "زیر ۲۵ و نشان‌دهنده روند کم‌قدرت است."} جهت را باید از سایر شاخص‌ها خواند.`;
    if (/^ao/i.test(name) && Number.isFinite(first)) return `عدد ${num(first, 2)} است؛ ${first > 0 ? "بالای صفر و به نفع شتاب صعودی است." : first < 0 ? "زیر صفر و به نفع شتاب نزولی است." : "روی صفر و خنثی است."}`;
    if (/stochrsi/i.test(name) && Number.isFinite(first)) return `عدد ${num(first, 3)} است؛ ${first >= .8 ? "بالاتر از ۰٫۸۰ و در خریدزدگی است." : first <= .2 ? "زیر ۰٫۲۰ و در فروش‌زدگی است." : "در محدوده میانی است."}`;
    if (/^macd/i.test(name)) {
      const macd = value("macd"), line = value("signal");
      return `MACD=${num(macd, 2)} و خط سیگنال=${num(line, 2)} است؛ ${macd > line ? "MACD بالاتر از سیگنال و شتاب صعودی است." : macd < line ? "MACD پایین‌تر از سیگنال و شتاب نزولی است." : "دو خط تقریباً برابرند."}`;
    }
    if (/^mtm/i.test(name) && Number.isFinite(first)) return `عدد ${num(first, 2)} است؛ ${first > 0 ? "مثبت و نشان‌دهنده شتاب رو به بالا است." : first < 0 ? "منفی و نشان‌دهنده شتاب رو به پایین است." : "نزدیک صفر و خنثی است."}`;
    if (/^trend/i.test(name)) return `سیگنال رسمی ره‌آورد «${signalText}» است و جهت روند را مشخص می‌کند.`;
    if (/^ema|^sma/i.test(name)) {
      const distance = value("distance");
      return `میانگین روی ${num(first, 2)} است؛ ${Number.isFinite(distance) ? `فاصله قیمت ${pct(distance * 100)} است و قیمت ${distance >= 0 ? "بالاتر" : "پایین‌تر"} از این میانگین قرار دارد.` : `سیگنال ره‌آورد ${signalText} است.`}`;
    }
    if (/^bb|^keltner/i.test(name)) {
      const upper = value("upper"), lower = value("lower"), distance = value("distance"), dl = value("dl");
      return `باند بالا ${num(upper, 2)} و پایین ${num(lower, 2)} است؛ ${Number.isFinite(distance) ? `فاصله از باند بالا ${pct(distance * 100)}${Number.isFinite(dl) ? ` و از باند پایین ${pct(dl * 100)}` : ""} است.` : `سیگنال ره‌آورد ${signalText} است.`}`;
    }
    if (/ichimoku/i.test(name)) {
      const tenkan = value("tenken_sen_formula"), kijun = value("kijun_sen_formula");
      return `تنکن ${num(tenkan, 2)} و کیجون ${num(kijun, 2)} است؛ ${tenkan > kijun ? "تنکن بالاتر از کیجون و متمایل به صعود است." : "تنکن پایین‌تر از کیجون و متمایل به ضعف است."}`;
    }
    if (/pivotpoint|pivot/i.test(name)) {
      const pivot = value("pivot"), r1 = value("r1"), s1 = value("s1");
      return `پیوت ${num(pivot, 2)}، مقاومت اول ${num(r1, 2)} و حمایت اول ${num(s1, 2)} است؛ این‌ها سطح قیمت‌اند، نه امتیاز.`;
    }
    if (/^rv/i.test(name) && Number.isFinite(first)) return `عدد ${num(first, 3)} است؛ ${first < 1 ? "پایین‌تر از خط مبنای ۱ و نشان‌دهنده حجم کمتر از مرجع است." : "بالاتر از خط مبنای ۱ و نشان‌دهنده حجم بیشتر از مرجع است."}`;
    if (/^vmacd/i.test(name)) {
      const line = value("vmacd"), signalLine = value("signal");
      return `VMACD=${num(line, 2)} و سیگنال=${num(signalLine, 2)} است؛ ${line > signalLine ? "شتاب حجم بهتر شده." : "شتاب حجم ضعیف‌تر شده."}`;
    }
    if (/^obv/i.test(name) && Number.isFinite(first)) return `عدد انباشته OBV برابر ${num(first, 0)} است؛ جهت تغییرات آن برای تأیید روند مهم‌تر از خود عدد است.`;
    if (Number.isFinite(first)) return `عدد ${num(first, 2)} است و سیگنال رسمی ره‌آورد «${signalText}» ثبت شده.`;
    return `عدد مستقیمی برای این شاخص منتشر نشده؛ سیگنال رسمی ره‌آورد «${signalText}» است.`;
  }

  function indicatorAssessment(key, value) {
    const signal = value?.signal || "neutral";
    const unavailable = value?.value == null || signal === "unavailable";
    if (unavailable) return { state: "unknown", label: "داده ناکافی" };
    if (key === "ADX(14)") {
      const plus = Number(value.plus_di), minus = Number(value.minus_di);
      if (signal !== "strong") return { state: "neutral", label: "روند کم‌قدرت" };
      if (Number.isFinite(plus) && Number.isFinite(minus) && plus !== minus)
        return plus > minus ? { state: "positive", label: "روند قوی صعودی" } : { state: "caution", label: "روند قوی نزولی" };
      return { state: "neutral", label: "روند قوی" };
    }
    if (["ATR(14)", "RV(15)", "RV(30)", "RV(90)", "VRSI(14)"].includes(key)) return { state: "neutral", label: "معیار نوسان/حجم" };
    if (["RSI(14)", "MFI(14)", "CCI(14)", "WR(14)", "SO(14)", "StochRSI(14)"].includes(key)) {
      if (signal === "oversold") return { state: "caution", label: "فروش‌زدگی · بااحتیاط" };
      if (signal === "overbought") return { state: "caution", label: "خریدزدگی · بااحتیاط" };
      return { state: "neutral", label: "محدوده میانی" };
    }
    if (["BB(20)", "KELTNER(16)"].includes(key)) {
      if (signal === "breakout_up") return { state: "caution", label: "بالاتر از کانال · کشیدگی" };
      if (signal === "breakout_down") return { state: "caution", label: "پایین‌تر از کانال · ضعف" };
      return { state: "neutral", label: "داخل کانال" };
    }
    if (key.startsWith("EMA(") || key.startsWith("SMA(")) return signal === "bullish" ? { state: "positive", label: "قیمت بالای میانگین" } : { state: "caution", label: "قیمت زیر میانگین" };
    if (key === "Aroon(25)" || key === "ARRON(25)") {
      const up = Number(value.up), down = Number(value.down);
      if (Number.isFinite(up) && Number.isFinite(down) && Math.max(up, down) < 50) return { state: "neutral", label: "روند کم‌رنگ" };
    }
    if (signal === "bullish") return { state: "positive", label: "مثبت برای روند" };
    if (signal === "bearish") return { state: "caution", label: "فشار منفی" };
    if (signal === "strong") return { state: "neutral", label: "روند قوی" };
    return { state: "neutral", label: "خنثی" };
  }

  function indicatorExtra(key, value) {
    if (key === "MACD(12,26,9)") return value.histogram == null ? "هیستوگرام در دسترس نیست" : `هیستوگرام ${num(value.histogram, 3)} · ${value.histogram > 0 ? "شتاب بالای خط سیگنال" : value.histogram < 0 ? "شتاب زیر خط سیگنال" : "برابر خط سیگنال"}`;
    if (key === "ADX(14)") return `+DI ${num(value.plus_di, 1)} · −DI ${num(value.minus_di, 1)}`;
    if (key === "Aroon(25)" || key === "ARRON(25)") return `بالا ${num(value.up, 0)} · پایین ${num(value.down, 0)}`;
    if (key === "SO(14)") return `%K ${num(value["%K"], 1)} · %D ${num(value["%D"], 1)}`;
    if (key === "Ichimoku(9,26,52,26)") return `ابر: ${({ above: "قیمت بالای ابر", below: "قیمت زیر ابر", inside: "قیمت داخل ابر" })[value.price_vs_cloud] || "نامشخص"}`;
    if (key === "BB(20)" || key === "KELTNER(16)") return `بالا ${num(value.upper, 2)} · میانی ${num(value.middle ?? value.value, 2)} · پایین ${num(value.lower, 2)}`;
    if (key === "OBV(20)") return `میانگین حجم تعادلی ۲۰دوره: ${num(value.sma20, 0)}`;
    return "";
  }

  function indicatorChartHtml(a) {
    const series = a?.indicators?.chart_series;
    const availableCount = series?.close?.length || 0;
    const count = Math.min(90, availableCount);
    if (count < 35) return `<div class="chart-empty">تاریخچه فعلی ${nf.format(a?.indicators?.observations ?? availableCount)} مشاهده دارد؛ برای رسم روند قابل‌خواندن RSI، MACD و ADX دست‌کم ۳۵ مشاهده لازم است.</div>`;
    const offset = (series.close.length || 0) - count;
    const take = (key) => (series[key] || []).slice(offset, offset + count).map((v) => v == null || !Number.isFinite(Number(v)) ? null : Number(v));
    const data = Object.fromEntries(["close", "ema20", "ema50", "bb_upper", "bb_lower", "rsi", "macd", "macd_signal", "macd_histogram", "adx"].map((key) => [key, take(key)]));
    const timestamps = (series.timestamps || []).slice(offset, offset + count);
    const W = 1080, H = 720, left = 76, right = 24, plotW = W - left - right;
    const panels = { price: { top: 42, height: 258 }, rsi: { top: 340, height: 92 }, macd: { top: 472, height: 100 }, adx: { top: 610, height: 70 } };
    const x = (i) => left + i * plotW / (count - 1);
    const finite = (key) => data[key].filter(Number.isFinite);
    const extent = (keys, symmetric = false) => {
      const vals = keys.flatMap(finite);
      let min = vals.length ? Math.min(...vals) : 0, max = vals.length ? Math.max(...vals) : 1;
      if (symmetric) { const span = Math.max(Math.abs(min), Math.abs(max), 1); min = -span; max = span; }
      const pad = (max - min || 1) * .08; return [min - pad, max + pad];
    };
    const scales = { price: extent(["close", "bb_upper", "bb_lower"]), rsi: [0, 100], macd: extent(["macd", "macd_signal", "macd_histogram"], true), adx: [0, 100] };
    const y = (panel, value) => panels[panel].top + panels[panel].height - ((value - scales[panel][0]) / (scales[panel][1] - scales[panel][0])) * panels[panel].height;
    const path = (key, panel) => {
      let d = "", pen = false;
      data[key].forEach((v, i) => { if (!Number.isFinite(v)) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(panel, v).toFixed(1)} `; pen = true; });
      return d;
    };
    const band = (() => {
      const indexes = data.bb_upper.map((v, i) => v != null && data.bb_lower[i] != null ? i : -1).filter((i) => i >= 0);
      if (indexes.length < 2) return "";
      return `${indexes.map((i, k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y("price", data.bb_upper[i]).toFixed(1)}`).join(" ")} ${indexes.reverse().map((i) => `L${x(i).toFixed(1)},${y("price", data.bb_lower[i]).toFixed(1)}`).join(" ")} Z`;
    })();
    const panelGrid = (name, label, ticks) => {
      const p = panels[name];
      return `<rect class="chart-panel-bg" x="${left}" y="${p.top}" width="${plotW}" height="${p.height}" rx="10"/><text class="chart-panel-title" x="${left - 12}" y="${p.top + 15}" text-anchor="end">${label}</text>${ticks.map((t) => `<line class="chart-gridline" x1="${left}" x2="${W - right}" y1="${y(name, t)}" y2="${y(name, t)}"/><text class="chart-axis-label" x="${left - 9}" y="${y(name, t) + 4}" text-anchor="end">${num(t, name === "price" ? 0 : 0)}</text>`).join("")}`;
    };
    const priceTicks = Array.from({ length: 5 }, (_, i) => scales.price[1] - (scales.price[1] - scales.price[0]) * i / 4);
    const macdTicks = [scales.macd[1], scales.macd[1] / 2, 0, scales.macd[0] / 2, scales.macd[0]];
    const macdBars = data.macd_histogram.map((v, i) => v == null ? "" : `<rect class="macd-bar ${v >= 0 ? "up" : "down"}" x="${x(i) - Math.max(1, plotW / count * .32)}" y="${Math.min(y("macd", 0), y("macd", v))}" width="${Math.max(1, plotW / count * .64)}" height="${Math.max(1, Math.abs(y("macd", v) - y("macd", 0)))}" rx="1"/>`).join("");
    const xTicks = [0, Math.floor((count - 1) / 4), Math.floor((count - 1) / 2), Math.floor((count - 1) * 3 / 4), count - 1];
    const datesHtml = [...new Set(xTicks)].map((i) => {
      const date = timestamps[i] ? new Date(timestamps[i]) : null;
      const label = date && !Number.isNaN(date.getTime()) ? new Intl.DateTimeFormat("fa-IR", { month: "short", day: "numeric" }).format(date) : "";
      return `<text class="chart-axis-label" x="${x(i)}" y="704" text-anchor="middle">${esc(label)}</text>`;
    }).join("");
    return `<div class="technical-chart-block"><div class="technical-chart-head"><div><strong>نمودار تکنیکال چندبخشی</strong><small>${nf.format(count)} مشاهده اخیر · قیمت، میانگین‌ها، RSI، MACD و ADX</small></div><span>هر پنل مقیاس جداگانه دارد</span></div><div class="technical-chart-wrap"><svg class="technical-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="نمودار قیمت و اندیکاتورهای RSI، MACD و ADX">${panelGrid("price", "قیمت", priceTicks)}${band ? `<path class="bb-band" d="${band}"/>` : ""}<path class="chart-line bb-edge" d="${path("bb_upper", "price")}"/><path class="chart-line bb-edge" d="${path("bb_lower", "price")}"/><path class="chart-line ema50" d="${path("ema50", "price")}"/><path class="chart-line ema20" d="${path("ema20", "price")}"/><path class="chart-line price-line" d="${path("close", "price")}"/>${panelGrid("rsi", "RSI", [100, 70, 50, 30, 0])}<rect class="rsi-zone" x="${left}" y="${y("rsi", 70)}" width="${plotW}" height="${y("rsi", 30) - y("rsi", 70)}"/><line class="chart-threshold" x1="${left}" x2="${W-right}" y1="${y("rsi",70)}" y2="${y("rsi",70)}"/><line class="chart-threshold" x1="${left}" x2="${W-right}" y1="${y("rsi",30)}" y2="${y("rsi",30)}"/><path class="chart-line rsi-line" d="${path("rsi", "rsi")}"/>${panelGrid("macd", "MACD", macdTicks)}<line class="chart-zero" x1="${left}" x2="${W-right}" y1="${y("macd",0)}" y2="${y("macd",0)}"/>${macdBars}<path class="chart-line macd-signal" d="${path("macd_signal", "macd")}"/><path class="chart-line macd-line" d="${path("macd", "macd")}"/>${panelGrid("adx", "ADX", [100, 50, 25, 0])}<line class="chart-threshold" x1="${left}" x2="${W-right}" y1="${y("adx",25)}" y2="${y("adx",25)}"/><path class="chart-line adx-line" d="${path("adx", "adx")}"/>${datesHtml}</svg></div><div class="chart-legend"><span><i class="legend-price"></i>قیمت</span><span><i class="legend-ema20"></i>EMA 20</span><span><i class="legend-ema50"></i>EMA 50</span><span><i class="legend-bb"></i>باند بولینگر</span><span><i class="legend-rsi"></i>RSI · محدوده ۳۰ تا ۷۰</span><span><i class="legend-macd"></i>MACD / خط سیگنال</span><span><i class="legend-adx"></i>ADX · خط ۲۵ = روند قوی‌تر</span></div></div>`;
  }

  function indicatorValueText(key, value) {
    if (value?.value == null) return "—";
    if (key === "Ichimoku(9,26,52,26)") return num(value.tenkan ?? value.value, 2);
    if (key === "BB(20)" || key === "KELTNER(16)") return num(value.middle ?? value.value, 2);
    return num(value.value, 3);
  }

  function indicatorRangeGuide(name) {
    const key = String(name || "").toLowerCase().replace(/[^a-z]/g, "");
    if (key.startsWith("stochrsi")) return "معمولاً ۰ تا ۱: زیر ۰٫۲۰ ناحیهٔ پایین و بالای ۰٫۸۰ ناحیهٔ بالا است؛ اگر مقیاس ۰ تا ۱۰۰ باشد، معادل ۲۰ و ۸۰. با روند اصلی بسنج.";
    if (key.startsWith("rsi")) return "مقیاس ۰ تا ۱۰۰؛ زیر ۳۰ فروش‌زدگی، ۳۰ تا ۷۰ میانه و بالای ۷۰ خریدزدگیِ احتمالی است. حدی‌شدن به‌تنهایی برگشت را ثابت نمی‌کند.";
    if (key.startsWith("mfi")) return "مقیاس ۰ تا ۱۰۰؛ زیر ۲۰ ناحیهٔ پایین و بالای ۸۰ ناحیهٔ بالاست. چون حجم را هم می‌سنجد، با جهت قیمت و روند بررسی شود.";
    if (key.startsWith("cci")) return "حدود ۱۰۰+ و ۱۰۰− مرزهای متداول‌اند؛ بینشان ناحیهٔ میانی است. در روند قوی یا نماد پرنوسان، CCI می‌تواند مدت زیادی بیرون این محدوده بماند.";
    if (key.startsWith("wr") || key.startsWith("williams")) return "مقیاس ۰ تا ۱۰۰−؛ از ۸۰− تا ۱۰۰− ناحیهٔ پایین، و از ۲۰− تا صفر ناحیهٔ بالا است. ماندن در ناحیهٔ حدی لزوماً برگشت نیست.";
    if (key.startsWith("so") || key.startsWith("stoch")) return "مقیاس ۰ تا ۱۰۰؛ زیر ۲۰ ناحیهٔ پایین و بالای ۸۰ ناحیهٔ بالاست. تقاطع K و D و جهت روند را هم ببین.";
    if (key.startsWith("aroon") || key.startsWith("arron")) return "خطوط Up و Down بین ۰ تا ۱۰۰ هستند؛ خط غالبِ بالای ۵۰ و نزدیک ۱۰۰ روند تازه‌تر را نشان می‌دهد. هر دو زیر ۵۰ می‌تواند بازار کم‌روند باشد.";
    if (key.startsWith("adx")) return "مقیاس ۰ تا ۱۰۰؛ زیر ۲۰ معمولاً روند ضعیف و بالای ۲۵ روند قوی‌تر است. ADX جهت را نمی‌گوید؛ جهت را از قیمت و شاخص‌های دیگر بگیر.";
    if (key.startsWith("ao")) return "حد ثابت ندارد و حول صفر می‌چرخد؛ بالای صفر یعنی شتاب کوتاه‌مدت قوی‌تر از بلندمدت و زیر صفر برعکس. عبور از صفر و تغییر میله‌ها را ببین.";
    if (key.startsWith("vmacd")) return "بازهٔ عددی ثابت ندارد؛ خط VMACD را با خط سیگنال و صفر مقایسه کن. بالاتر/روبه‌افزایش بودن، بهبود شتاب حجم را نشان می‌دهد، نه جهت قطعی قیمت.";
    if (key.startsWith("macd")) return "بازهٔ عددی ثابت ندارد؛ خط MACD بالای خط سیگنال و صفر، زمینهٔ شتاب مثبت‌تری دارد؛ زیر آن‌ها زمینه ضعیف‌تر است. فاصله‌ها را با تاریخچهٔ همان نماد بسنج.";
    if (key.startsWith("mtm") || key.startsWith("momentum")) return "خط صفر مرجع است: بالای صفر یعنی قیمت از دورهٔ مبنا بالاتر و زیر صفر پایین‌تر است. برای شدت حرکت، مقدار را با تاریخچهٔ همان نماد مقایسه کن.";
    if (key.startsWith("trend")) return "این مورد برچسب متنی ره‌آورد است، نه عددِ دارای محدوده؛ صعودی، نزولی یا خنثی بودن را همراه سیگنال و روند قیمت بخوان.";
    if (key.startsWith("ichimoku")) return "برای خود خطوط عدد خوبِ ثابتی نداریم؛ قیمت بالای ابر زمینهٔ صعودی، زیر ابر زمینهٔ نزولی و داخل ابر حالت گذار/خنثی است.";
    if (key.startsWith("keltner")) return "مقدارها قیمتِ باند بالا، میانی و پایین‌اند و محدودهٔ ثابتی ندارند؛ جای قیمت نسبت به باندها و باز یا بسته‌شدن کانال را بسنج.";
    if (key.startsWith("bb") || key.startsWith("bollinger")) return "مقدارها باند بالا، میانی و پایین‌اند؛ عدد ثابتِ خوب/بد ندارند. پهن‌شدن یعنی نوسان بیشتر و تماس با باند را همراه روند بخوان.";
    if (key.startsWith("ema") || key.startsWith("sma")) return "محدودهٔ عددی ثابت ندارد؛ قیمت بالای میانگین معمولاً زمینهٔ مثبت‌تر و زیر آن زمینهٔ ضعیف‌تر است. دوره‌های کوتاه و بلند را با هم مقایسه کن.";
    if (key.startsWith("pivotpoint") || key.startsWith("pivot")) return "این‌ها سطح قیمت‌اند، نه نمره؛ P نقطهٔ میانی، Rها مقاومت‌های احتمالی و Sها حمایت‌های احتمالی‌اند. نزدیکی به سطح به‌تنهایی واکنش را تضمین نمی‌کند.";
    if (key.startsWith("rv")) return "برای نسبت حجم، ۱ خط مبناست: بالای ۱ حجم بیشتر از مرجع و زیر ۱ کمتر از مرجع است. افزایش حجم به‌تنهایی صعودی یا نزولی نیست.";
    if (key.startsWith("sm")) return "برای این شاخص ره‌آورد محدودهٔ عددی عمومیِ قابل اتکایی در دست نیست؛ مقدار و سیگنال رسمی را با روند حجم و قیمت مقایسه کن.";
    if (key.startsWith("vrsi")) return "در این نسخه آستانهٔ ثابتِ تأییدشده‌ای نداریم؛ تغییرات و سیگنال VRSI را در کنار حجم و روند قیمت بخوان، نه به‌تنهایی.";
    if (key.startsWith("obv")) return "عدد مطلق محدودهٔ خوب/بد ندارد و انباشته است؛ مهم‌تر از عدد، جهت خط و واگرایی آن با قیمت است.";
    return "برای این شاخص محدودهٔ عددی ثابتی اعلام نشده؛ مقدار را با خط مبنا، روند یا بازه‌های همان شاخص مقایسه کن.";
  }

  function rahavardRecommendationHtml(a) {
    const gauge = a.site_gauges?.main || {};
    const rawSignal = gauge.signal?.value;
    const signalValue = rawSignal == null || String(rawSignal).trim() === "" ? null : Number(rawSignal);
    const footer = gauge.footer || {};
    const readCount = (key) => {
      const raw = footer[key]?.value;
      if (raw == null || String(raw).trim() === "") return null;
      const value = Number(raw);
      return Number.isFinite(value) ? value : null;
    };
    const buy = readCount("Buy");
    const neutral = readCount("Neutral");
    const sell = readCount("Sell");
    const countsAvailable = [buy, neutral, sell].some((value) => value != null);
    const direction = Number.isFinite(signalValue)
      ? Math.sign(signalValue)
      : buy != null && sell != null ? Math.sign(buy - sell) : null;
    const verdict = direction == null ? "اطلاعات کافی نیست" : direction > 0 ? "خرید" : direction < 0 ? "فروش" : "صبر / خنثی";
    const tone = direction == null ? "unknown" : direction > 0 ? "positive" : direction < 0 ? "negative" : "neutral";
    const trendItem = Object.values(a.indicators || {}).flatMap((items) => Array.isArray(items) ? items : [])
      .find((item) => String(item?.short_name_en || item?.name_en || "").trim().toLowerCase() === "trend");
    const trendSignal = String(trendItem?.signal || "").trim().toLowerCase().replace(/[^a-z]/g, "");
    const trendDirection = ["buy", "bullish", "strongbuy"].includes(trendSignal) ? 1
      : ["sell", "bearish", "strongsell"].includes(trendSignal) ? -1
        : ["neutral", "hold"].includes(trendSignal) ? 0 : null;
    const trendLabel = trendDirection == null ? "نامشخص" : trendDirection > 0 ? "صعودی" : trendDirection < 0 ? "نزولی" : "خنثی";
    const trendTone = trendDirection == null ? "unknown" : trendDirection > 0 ? "positive" : trendDirection < 0 ? "negative" : "neutral";
    const scenarios = Array.isArray(a.scenarios) ? a.scenarios : [];
    const selectedScenario = direction > 0 ? scenarios.find((item) => item.direction === "bullish")
      : direction < 0 ? scenarios.find((item) => item.direction === "bearish") : null;
    const rationale = selectedScenario?.reason
      ? `به علت ${selectedScenario.reason}، سناریوی ${selectedScenario.name} فعلاً محتمل‌تر است.`
      : direction == null
        ? "از روی دادهٔ فعلی دلیل عددی کافی برای نتیجه‌گیری وجود ندارد."
        : "مقادیر عددی منتشرشده برای نتیجه‌گیری هم‌جهت کافی نیستند؛ حمایت و مقاومت را زیر نظر بگیر.";
    const trendContext = !trendItem
      ? "شاخص Trend در دادهٔ منتشرشدهٔ این نماد موجود نیست؛ جمع‌بندی فقط از سیگنال تجمیعی استفاده می‌کند."
      : direction == null
        ? `شاخص روند ${trendLabel} است، اما سیگنال تجمیعی قابل‌خواندن نیست.`
        : direction === trendDirection && direction !== 0
          ? `روند و برآیند سیگنال‌ها همسو و ${trendLabel} هستند.`
          : direction === 0
            ? `سیگنال تجمیعی خنثی است؛ شاخص روند ${trendLabel} را نشان می‌دهد.`
            : trendDirection === 0
              ? `برآیند به ${direction > 0 ? "خرید" : "فروش"} متمایل است، اما شاخص روند خنثی است.`
              : `سیگنال تجمیعی به ${direction > 0 ? "خرید" : "فروش"} متمایل است، ولی شاخص روند ${trendLabel} را نشان می‌دهد؛ این ناهمسویی را در جمع‌بندی لحاظ کن.`;
    const oscillatorItems = Array.isArray(a.indicators?.oscillators) ? a.indicators.oscillators : [];
    const overboughtCount = oscillatorItems.filter((item) =>
      String(item?.signal || "").trim().toLowerCase().replace(/[^a-z]/g, "") === "overbought").length;
    const hasOscillatorSignals = oscillatorItems.some((item) => item?.signal != null && String(item.signal).trim() !== "");
    const pivotFooter = a.site_gauges?.pivot?.footer || {};
    const readPivotCount = (key) => {
      const raw = pivotFooter[key]?.value;
      if (raw == null || String(raw).trim() === "") return null;
      const value = Number(raw);
      return Number.isFinite(value) ? value : null;
    };
    const pivotItems = Array.isArray(a.indicators?.pivots) ? a.indicators.pivots : [];
    const pivotSignalCount = (key) => pivotItems.filter((item) =>
      String(item?.signal || "").trim().toLowerCase().replace(/[^a-z]/g, "") === key).length;
    const resistanceCount = readPivotCount("Resistance") ?? (pivotItems.length ? pivotSignalCount("resistance") : null);
    const supportCount = readPivotCount("Support") ?? (pivotItems.length ? pivotSignalCount("support") : null);
    const resistanceWarning = resistanceCount != null && supportCount != null && resistanceCount > supportCount;
    const overboughtWarning = overboughtCount > 0;
    const multipleOverboughtWarning = overboughtCount >= 2;
    const bearishConfluence = direction < 0 && trendDirection < 0;
    const strongerCorrectionRisk = bearishConfluence || (trendDirection < 0 && (resistanceWarning || multipleOverboughtWarning)) || (resistanceWarning && multipleOverboughtWarning);
    const correctionRisk = strongerCorrectionRisk ? "بالا"
      : direction < 0 || trendDirection < 0 || resistanceWarning || overboughtWarning ? "افزایش‌یافته"
        : direction > 0 && trendDirection > 0 && hasOscillatorSignals ? "نشانهٔ پررنگی دیده نمی‌شود" : "نامشخص";
    const entryTone = strongerCorrectionRisk ? "negative"
      : direction > 0 && trendDirection > 0 && !resistanceWarning && !overboughtWarning ? "positive" : "neutral";
    const entryAction = direction == null || trendDirection == null ? "اطلاعات کافی برای ارزیابی ورود نیست"
      : strongerCorrectionRisk ? "خرید جدید فعلاً پرریسک است؛ برای ورود صبر کن"
        : direction > 0 && trendDirection > 0 && (resistanceWarning || multipleOverboughtWarning)
          ? "برای اصلاح یا تأیید بهتر صبر کن"
          : direction > 0 && trendDirection > 0 && overboughtWarning
            ? "ورود پله‌ای؛ از خرید یک‌جا پرهیز کن"
          : direction > 0 && trendDirection > 0 ? "ورود پله‌ای قابل بررسی است"
            : "فعلاً صبر؛ نشانه‌ها تأیید همسو نمی‌دهند";
    const entryReason = selectedScenario?.reason
      ? selectedScenario.reason
      : strongerCorrectionRisk
      ? "روند و مومنتوم نزولی هم‌جهت‌اند؛ احتمال ادامهٔ فشار و اصلاح بیشتر است."
      : direction > 0 && trendDirection > 0 && (resistanceWarning || overboughtWarning)
        ? `${overboughtWarning ? `خریدزدگی در ${num(overboughtCount, 0)} اندیکاتور` : ""}${overboughtWarning && resistanceWarning ? " و " : ""}${resistanceWarning ? "سیگنال‌های مقاومتی بیشتر از حمایتی" : ""}؛ برای خرید یک‌جا احتیاط کن و احتمال اصلاح را در نظر بگیر.`
        : direction > 0 && trendDirection > 0
          ? "سیگنال کلی و روند هر دو صعودی‌اند؛ نشانهٔ اصلاح پررنگی در داده‌های فعلی دیده نمی‌شود، اما ورود پله‌ای ریسک زمان‌بندی را کمتر می‌کند."
          : direction < 0 || trendDirection < 0
            ? "حداقل یکی از سیگنال کلی یا روند نزولی است؛ خرید تازه را تا روشن‌شدن جهت بازار به تعویق بینداز."
            : "سیگنال کلی خنثی یا ترکیبی است؛ فعلاً جهت روشنی برای ورود دیده نمی‌شود.";
    const stats = [];
    if (countsAvailable) {
      if (buy != null) stats.push(`<span class="recommendation-count buy">خرید <b>${num(buy, 0)}</b></span>`);
      if (neutral != null) stats.push(`<span class="recommendation-count neutral">خنثی <b>${num(neutral, 0)}</b></span>`);
      if (sell != null) stats.push(`<span class="recommendation-count sell">فروش <b>${num(sell, 0)}</b></span>`);
    }
    if (a.technical_score != null && Number.isFinite(Number(a.technical_score))) {
      stats.push(`<span class="recommendation-count score">امتیاز تکنیکال <b>${num(a.technical_score, 0)} از ۱۰۰</b></span>`);
    }
    return `<section class="fund-recommendation ${tone}"><div class="fund-recommendation-main"><div><span class="recommendation-kicker">جمع‌بندی تکنیکال ره‌آورد · ${esc(a.symbol || "این صندوق")}</span><h3>سیگنال کلی: <strong>${verdict}</strong></h3></div><div class="recommendation-context"><p>${rationale}</p><div class="recommendation-trend ${trendTone}"><span>روند طبق شاخص ره‌آورد</span><b>${trendLabel}</b></div><small>${trendContext}</small></div></div><div class="entry-outlook ${entryTone}"><div class="entry-outlook-verdict"><span>اگر الان بخری</span><b>${entryAction}</b></div><div class="entry-outlook-risk"><span>ریسک اصلاح / افت</span><b>${correctionRisk}</b></div><p>${entryReason}</p></div>${stats.length ? `<div class="recommendation-stats">${stats.join("")}</div>` : ""}<small>این جمع‌بندی فقط بر پایهٔ سیگنال‌های تکنیکال منتشرشده است؛ نتیجهٔ قطعی یا شخصی‌سازی‌شده نیست. آن را با قیمت سر‌به‌سر، افق نگهداری و ریسک خودت بسنج.</small></section>`;
  }

  function scenarioHtml(a) {
    const scenarios = Array.isArray(a?.scenarios) ? a.scenarios : [];
    if (!scenarios.length) return "";
    const cards = scenarios.map((scenario) => {
      const direction = scenario.direction === "bullish" ? "bullish" : "bearish";
      const probability = Math.max(0, Math.min(100, Number(scenario.probability) || 0));
      return `<article class="scenario-card ${direction}"><div class="scenario-card-head"><div><span class="scenario-kicker">سناریوی محتمل</span><h4>${esc(scenario.name)}</h4></div><strong>${num(probability, 0)}٪</strong></div><div class="scenario-bar"><i style="width:${probability}%"></i></div><p>${esc(scenario.reason || "دلیل مشخصی ثبت نشده است.")}</p><div class="scenario-condition"><b>شرط تأیید:</b> ${esc(scenario.condition || "—")}</div><small>${esc(scenario.risk || "")}</small></article>`;
    }).join("");
    return `<section class="scenario-section"><div class="indicator-section-title"><div><h3>سناریوهای احتمالی</h3><p>احتمال‌ها از شمارنده‌های رسمی و جهت روند همین نماد برآورد شده‌اند.</p></div></div><div class="scenario-grid">${cards}</div><div class="scenario-note">${esc(a.scenario_note || "این احتمال‌ها برآورد تحلیلی هستند و پیش‌بینی قطعی نیستند.")}</div></section>`;
  }

  function tradePlanHtml(a) {
    const price = Number(a?.price ?? a?.indicators?.latest);
    if (!Number.isFinite(price) || price <= 0) return "";
    const levelValue = (raw) => {
      if (typeof raw === "number" && Number.isFinite(raw)) return raw;
      if (!raw || typeof raw !== "object") return null;
      const direct = [raw.midpoint, raw.price, raw.value, raw.level].map(Number).find(Number.isFinite);
      if (direct != null) return direct;
      const low = Number(raw.low), high = Number(raw.high);
      return Number.isFinite(low) && Number.isFinite(high) ? (low + high) / 2 : null;
    };
    const collectLevels = (kind) => {
      const directKey = kind === "support" ? "support_levels" : "resistance_levels";
      const direct = Array.isArray(a?.[directKey]) ? a[directKey] : [];
      const generic = Array.isArray(a?.support_resistance) ? a.support_resistance.filter((item) => item?.kind === kind) : [];
      return [...new Set([...direct, ...generic].map(levelValue).filter((value) => Number.isFinite(value) && value > 0))];
    };
    const supports = collectLevels("support");
    const resistances = collectLevels("resistance");
    const below = supports.filter((value) => value < price).sort((left, right) => right - left);
    const above = resistances.filter((value) => value > price).sort((left, right) => left - right);
    const genericAtr = a?.indicators?.indicators?.["ATR(14)"];
    const rahavardItems = Object.values(a?.indicators || {}).flatMap((items) => Array.isArray(items) ? items : []);
    const rahavardAtr = rahavardItems.find((item) => String(item?.short_name_en || item?.name_en || "").toUpperCase().startsWith("ATR"));
    const rahavardAtrValue = rahavardAtr?.value?.find?.((part) => String(part?.name || "").toLowerCase() === "value")?.value ?? rahavardAtr?.value?.[0]?.value;
    const atr = Number(genericAtr?.value ?? rahavardAtrValue);
    const step = Number.isFinite(atr) && atr > 0 ? Math.min(.1, Math.max(.01, atr / price)) : .02;
    const entry1 = below[0] ?? price * (1 - step * .45);
    const entry2 = below[1] ?? Math.min(entry1 * (1 - step * .45), price * (1 - step * .9));
    const entry3 = below[2] ?? Math.min(entry2 * (1 - step * .45), price * (1 - step * 1.35));
    const target1 = above[0] ?? price * (1 + step * 1.4);
    const target2 = above[1] ?? Math.max(target1 * (1 + step * .35), price * (1 + step * 2.4));
    const stopBase = below[0] ?? price * (1 - step * 1.25);
    const stop = Math.max(0, stopBase - Math.max(price * .005, Number.isFinite(atr) ? atr * .35 : price * step * .35));
    const signal = String(a?.signal || "").toLowerCase();
    const tone = signal.includes("sell") || a?.trend === "bearish" ? "bearish" : signal.includes("buy") || a?.trend === "bullish" ? "bullish" : "neutral";
    const advice = tone === "bullish" ? "ورود فقط به‌صورت پله‌ای و نزدیک حمایت‌ها بررسی شود؛ خرید یک‌جا ریسک زمان‌بندی دارد." : tone === "bearish" ? "تا تثبیت بالای مقاومت یا برگشت روند، خرید تازه با احتیاط و حجم کم بررسی شود." : "سطوح برای سناریوی میان‌مدت هستند؛ ابتدا واکنش قیمت در پله اول را بررسی کن.";
    const card = (className, label, value, note) => `<article class="trade-level ${className}"><span>${label}</span><b>${money(value)}</b><small>${note}</small></article>`;
    return `<section class="trade-plan ${tone}"><div class="trade-plan-head"><div><span class="panel-kicker">برنامه معاملاتی میان‌مدت</span><h3>پله‌های خرید، حد سود و حد ضرر</h3></div><span class="trade-plan-badge">سطوح محاسباتی</span></div><div class="trade-plan-grid">${card("entry", "پله خرید 1", entry1, below[0] ? "نزدیک‌ترین حمایت معتبر" : "حدود 0.45 ATR پایین‌تر از قیمت")} ${card("entry", "پله خرید 2", entry2, below[1] ? "حمایت بعدی" : "در صورت اصلاح بیشتر")} ${card("entry", "پله خرید 3", entry3, below[2] ? "حمایت عمیق‌تر" : "پله ریسک بالاتر")} ${card("target", "حد سود میان‌مدت 1", target1, above[0] ? "نزدیک‌ترین مقاومت" : "هدف نوسانی اول")} ${card("target", "حد سود میان‌مدت 2", target2, above[1] ? "مقاومت بعدی" : "هدف نوسانی دوم")} ${card("stop", "حد ضرر میان‌مدتی", stop, "پایین‌تر از حمایت و با فاصله نوسان")}</div><p class="trade-plan-note">${advice} این اعداد توصیه قطعی نیستند و با تغییر قیمت و داده‌های ره‌آورد به‌روزرسانی می‌شوند.</p></section>`;
  }

  function rahavardAnalysisHtml(a) {
    const signalFa = { buy: "خرید · مثبت", sell: "فروش · منفی", hold: "خنثی", strong_buy: "خرید قوی", strong_sell: "فروش قوی" };
    const siteSignals = {
      buy: ["خرید / مثبت", "positive"], strongbuy: ["خرید قوی", "positive"], bullish: ["صعودی", "positive"],
      sell: ["فروش / منفی", "caution"], strongsell: ["فروش قوی", "caution"], bearish: ["نزولی", "caution"],
      neutral: ["خنثی", "neutral"], overbought: ["خریدزدگی · احتیاط", "caution"],
      oversold: ["فروش‌زدگی · احتمال برگشت", "neutral"], resistance: ["مقاومت", "caution"],
      support: ["حمایت", "neutral"], highvolume: ["حجم بالا · بدون جهت", "neutral"],
      lowvolume: ["حجم پایین · تأیید ضعیف‌تر", "neutral"]
    };
    const groups = a.indicators || {};
    const notes = new Map((a.indicator_notes || []).map((x) => [x.name, x]));
    const groupNames = { oscillators: "نوسانگرها و روند", moving_averages: "میانگین‌ها و باندها", bands: "باندهای نوسان", pivots: "پیوت‌ها و سطوح", volumes: "شاخص‌های حجم" };
    const valueNames = {
      rsi: "RSI", mfi: "جریان پول", cci: "CCI", wr: "Williams %R", k: "خط K", d: "خط D",
      up: "Aroon صعودی", down: "Aroon نزولی", adx: "قدرت روند", awesome: "AO", stochrsi: "StochRSI",
      macd: "خط MACD", signal: "خط سیگنال", MTM: "مومنتوم", value: "مقدار",
      tenken_sen_formula: "تنکن‌سن", kijun_sen_formula: "کیجون‌سن", senkou_span_a_formula: "ابر A",
      senkou_span_b_formula: "ابر B", upper: "باند بالا", lower: "باند پایین", distance: "فاصله از باند بالا",
      dl: "فاصله از باند پایین", pivot: "نقطه پیوت", r1: "مقاومت ۱", r2: "مقاومت ۲", r3: "مقاومت ۳",
      r4: "مقاومت ۴", s1: "حمایت ۱", s2: "حمایت ۲", s3: "حمایت ۳", s4: "حمایت ۴",
      rv: "حجم نسبی", sm: "جریان پول هوشمند", vrsi: "VRSI", vmacd: "VMACD", obv: "OBV"
    };
    const cards = Object.entries(groups).flatMap(([group, items]) => (items || []).map((item) => {
      const name = item.short_name_en || item.name_en || "شاخص ره‌آورد";
      const note = notes.get(name) || {};
      const rawSignal = String(item.signal || "Neutral");
      const signalKey = rawSignal.toLowerCase().replace(/[^a-z]/g, "");
      const [signalLabel, state] = siteSignals[signalKey] || [rawSignal, "neutral"];
      const values = (item.value || []).map((part) => {
        const val = Number(part.value);
        if (!Number.isFinite(val)) return "";
        const key = String(part.name || "");
        const percentValue = /distance/i.test(key) || key === "dl";
        const priceIndicator = /^(EMA|SMA|BB|KELTNER|Ichimoku|PivotPoint)/i.test(name) && !percentValue;
        const rendered = percentValue ? pct(val * 100) : num(val, priceIndicator ? 0 : 2);
        return `<div class="rahavard-indicator-value"><span>${esc(valueNames[key] || part.long_name_en || key)}</span><b>${rendered}</b></div>`;
      }).join("");
      return `<article class="indicator-card rahavard-indicator-card"><div class="indicator-card-head"><div><b>${esc(name)}</b><small>${esc(groupNames[group] || group)}</small></div><span class="indicator-status ${state}">${esc(signalLabel)}</span></div><div class="rahavard-indicator-values">${values || `<span class="factor-foot">مقداری در پاسخ ره‌آورد نبود.</span>`}</div><p>${esc(indicatorNumericSummary(name, item))}</p><div class="indicator-range-guide"><b>راهنمای محدوده</b><span>${esc(indicatorRangeGuide(name))}</span></div></article>`;
    }));
    const gaugeCards = ["main", "pivot", "volume"].map((key) => {
      const gauge = a.site_gauges?.[key];
      if (!gauge) return "";
      const title = key === "main" ? "جمع‌بندی تکنیکال" : key === "pivot" ? "پیوت" : "حجم";
      const counts = gauge.footer || {};
      const countText = Object.entries(counts).map(([label, value]) => `${label}: ${value?.value ?? "—"}`).join(" · ");
      return `<div class="readout-card"><span>${title} · سیگنال ره‌آورد</span><strong>${num(gauge.signal?.value, 0)}</strong><em class="indicator-status neutral">${esc(countText)}</em></div>`;
    }).join("");
    const score = a.technical_score == null ? "—" : num(a.technical_score, 0);
    const cls = a.signal === "buy" ? "bullish" : a.signal === "sell" ? "bearish" : "";
    const missing = (a.missing_indicators || []).map((name) => `<article class="indicator-card"><div class="indicator-card-head"><div><b>${esc(name)}</b><small>در پاسخ نماد منتشر نشده</small></div><span class="indicator-status unknown">موجود نیست</span></div><p>برای این مقدار عدد جایگزین ساخته نشده است.</p><div class="indicator-range-guide"><b>راهنمای محدوده</b><span>${esc(indicatorRangeGuide(name))}</span></div></article>`).join("");
    return `<div class="score-card"><div class="score-ring" style="--score:${Number(a.technical_score) || 0}%"><b>${score}</b></div><div class="score-copy"><strong>امتیاز تجمیعی ره‌آورد</strong><small>سیگنال‌های اندیکاتور همان‌هایی هستند که در صفحهٔ نماد ره‌آورد نمایش داده می‌شوند.</small></div><span class="signal-pill ${cls}">${signalFa[a.signal] || "خنثی"}</span></div><div class="factor-foot">${esc(a.explanation || "")} · داده تا ${esc(formatDate(a.data_timestamp))}</div>${tradePlanHtml(a)}<section class="indicator-workbench"><div class="indicator-section-title"><div><h3>جمع‌بندی ره‌آورد</h3><p>عدد هر اندیکاتور و فاصله‌اش از محدوده مرجع در کارت همان شاخص توضیح داده شده است.</p></div></div><div class="indicator-readouts">${gaugeCards}</div><div class="indicator-section-title all-indicators-title"><div><h3>اندیکاتورهای هر نماد</h3><p>${nf.format(a.indicator_count || cards.length)} شاخص با مقدار فعلی، تفسیر عددی و سیگنال رسمی</p></div></div><div class="indicator-card-grid">${cards.join("")}${missing}</div>${rahavardRecommendationHtml(a)}${scenarioHtml(a)}<div class="indicator-key-note"><b>روش خواندن:</b> هر عدد با محدوده رایج همان شاخص مقایسه شده است؛ خریدزدگی و فروش‌زدگی هشدار افراط‌اند و به‌تنهایی سیگنال قطعی خرید یا فروش نیستند.</div></section>`;
  }

  function analysisHtml(a) {
    if (a?.source === "Rahavard365") return rahavardAnalysisHtml(a);
    if (!a || a.technical_score == null) return `<div class="empty-state compact"><b>داده کافی برای محاسبه امتیاز موجود نیست</b><small>مدل فقط داده ذخیره‌شده از منبع را تحلیل می‌کند.</small></div>`;
    const score = Number(a.technical_score);
    const factors = (a.factors || []).map((f) => `<div class="factor-item"><span>${factorFa[f.name] || esc(f.name)} · وزن ${num(f.weight * 100, 0)}٪</span><b>${esc(f.evidence)}</b></div>`).join("");
    const signalClass = a.signal.includes("buy") ? "bullish" : a.signal.includes("sell") ? "bearish" : "";
    const all = a.indicators?.indicators || {};
    const seen = new Set();
    const entries = Object.entries(all).filter(([key]) => {
      const normalized = key === "ARRON(25)" ? "Aroon(25)" : key;
      if (seen.has(normalized)) return false;
      seen.add(normalized);
      return true;
    });
    const cards = entries.map(([key, value]) => {
      const assessment = indicatorAssessment(key, value);
      const name = indicatorFa[key] || (/^(EMA|SMA)\(/.test(key) ? (key.startsWith("EMA") ? "میانگین نمایی" : "میانگین ساده") : key);
      const displayKey = key === "Aroon(25)" ? "ARRON(25)" : key;
      const extra = indicatorExtra(key, value);
      return `<article class="indicator-card" title="فرمول: ${esc(value.formula || "ثبت نشده")}"><div class="indicator-card-head"><div><b>${esc(name)}</b><small>${esc(displayKey)}</small></div><span class="indicator-status ${assessment.state}">${assessment.label}</span></div><div class="indicator-card-value"><strong>${indicatorValueText(key, value)}</strong><span>${key.startsWith("EMA(") || key.startsWith("SMA(") ? "مقدار میانگین" : key === "BB(20)" || key === "KELTNER(16)" ? "خط میانی کانال" : key === "Ichimoku(9,26,52,26)" ? "خط تنکان" : "مقدار فعلی"}</span></div><p>${esc(indicatorNumericSummary(key, value))}</p><div class="indicator-range-guide"><b>راهنمای محدوده</b><span>${esc(indicatorRangeGuide(key))}</span></div>${extra ? `<div class="indicator-extra">${esc(extra)}</div>` : ""}<div class="indicator-previous">مقدار قبلی <b>${value.previous_value == null ? "—" : num(value.previous_value, 3)}</b></div></article>`;
    }).join("");
    const levels = a.support_resistance || [];
    const levelHtml = levels.length ? levels.map((l) => `<div class="level-chip ${l.kind}"><span>${l.kind === "support" ? "حمایت" : "مقاومت"} · ${esc(l.strength)}</span><b>${money(l.low)} – ${money(l.high)}</b><small>${esc((l.methods || []).join("، "))}</small></div>`).join("") : `<span class="factor-foot">سطح قابل محاسبه‌ای وجود ندارد.</span>`;
    const pivots = a.indicators?.pivots || {};
    const pivotHtml = Object.entries(pivots).map(([method, vals]) => {
      const current = Number(a.indicators?.latest), pivot = Number(vals.pivot);
      const above = Number.isFinite(current) && Number.isFinite(pivot) && current >= pivot;
      return `<div class="pivot-row"><b>${esc(method)}</b><span>R3 ${money(vals.R3)} · R2 ${money(vals.R2)} · R1 ${money(vals.R1)}</span><span>PP ${money(vals.pivot)} · ${above ? "قیمت بالای نقطه تعادل" : "قیمت زیر نقطه تعادل"}</span><span>S1 ${money(vals.S1)} · S2 ${money(vals.S2)} · S3 ${money(vals.S3)}</span></div>`;
    }).join("");
    const ind = all;
    const rsi = ind["RSI(14)"];
    const macd = ind["MACD(12,26,9)"];
    const adx = ind["ADX(14)"];
    const ma = a.indicators?.moving_average_analysis || {};
    const maAlignment = [ma.price_above_ema20, ma.price_above_ema50, ma.price_above_ema200].filter((v) => v != null);
    const maState = maAlignment.length && maAlignment.every(Boolean) ? "positive" : maAlignment.length && maAlignment.every((v) => !v) ? "caution" : "neutral";
    const maLabel = maState === "positive" ? "بالای هر سه میانگین" : maState === "caution" ? "زیر هر سه میانگین" : "ترکیبی / ناقص";
    const summary = (label, value, state, meaning) => `<div class="readout-card"><span>${label}</span><strong>${value}</strong><em class="indicator-status ${state}">${meaning}</em></div>`;
    const summaryCards = [
      summary("RSI · قدرت حرکت", rsi?.value == null ? "—" : num(rsi.value, 1), rsi ? indicatorAssessment("RSI(14)", rsi).state : "unknown", rsi ? `${indicatorAssessment("RSI(14)", rsi).label} · بالای ۷۰ خریدزدگی، زیر ۳۰ فروش‌زدگی` : "داده ناکافی"),
      summary("MACD · شتاب روند", macd?.value == null ? "—" : `خط ${num(macd.value, 2)} / هیستوگرام ${num(macd.histogram, 2)}`, macd ? indicatorAssessment("MACD(12,26,9)", macd).state : "unknown", macd ? (Number(macd.histogram) > 0 ? "خط MACD بالای سیگنال؛ شتاب بهتر شده" : Number(macd.histogram) < 0 ? "خط MACD زیر سیگنال؛ شتاب ضعیف‌تر است" : "خط و سیگنال نزدیک هم") : "داده ناکافی"),
      summary("ADX · قدرت و جهت روند", adx?.value == null ? "—" : num(adx.value, 1), adx ? indicatorAssessment("ADX(14)", adx).state : "unknown", adx ? `${indicatorAssessment("ADX(14)", adx).label} · ADX جهت را به‌تنهایی نمی‌گوید` : "داده ناکافی"),
      summary("میانگین‌های EMA", maAlignment.length ? `${maAlignment.filter(Boolean).length} از ${maAlignment.length}` : "—", maState, `${maLabel} · نسبت قیمت به EMA20/50/200`)
    ].join("");
    return `<div class="score-card"><div class="score-ring" style="--score:${score}%"><b>${num(score, 0)}</b></div><div class="score-copy"><strong>امتیاز فنی · پوشش عوامل ${num(a.confidence, 0)}٪</strong><small>روند کوتاه ${trendText(a.short_term_trend)} · میان‌مدت ${trendText(a.medium_term_trend)} · بلندمدت ${trendText(a.long_term_trend)}</small></div><span class="signal-pill ${signalClass}">${signalFa[a.signal] || a.signal}</span></div><div class="factor-list">${factors}</div><div class="factor-foot">${esc(a.decision_support)}. ریسک نوسان: ${esc(a.risk)}. پوشش عوامل مدل معیار موفقیت نیست (${esc(a.confidence_basis || "")} ). داده تا ${esc(formatDate(a.data_timestamp))}. خروجی توصیه قطعی نیست.</div>${tradePlanHtml(a)}<section class="indicator-workbench"><div class="indicator-section-title"><div><h3>خوانش سریع شاخص‌ها</h3><p>سبز = همسو با حرکت صعودی · کهربایی = هشدار یا فشار نزولی · خاکستری = خنثی یا سنجش ریسک</p></div></div><div class="indicator-readouts">${summaryCards}</div><div class="indicator-section-title all-indicators-title"><div><h3>همه اندیکاتورها</h3><p>${nf.format(entries.length)} شاخص با مقدار فعلی، مقدار قبلی، معنی و وضعیت</p></div></div><div class="indicator-card-grid">${cards}</div><div class="indicator-key-note"><b>راهنمای خواندن:</b> خریدزدگی یا فروش‌زدگی به‌تنهایی «خوب» یا «بد» نیست؛ یعنی حرکت به محدوده افراطی رسیده و باید همراه روند و حجم بررسی شود. نوسان بیشتر هم فقط ریسک حرکت بزرگ‌تر را نشان می‌دهد.</div>${scenarioHtml(a)}</section><div class="levels-block"><h4>حمایت و مقاومت · محدوده‌های نزدیک</h4><div class="levels-grid">${levelHtml}</div></div><section class="pivot-section"><h4>پیوت‌ها و سطوح روز قبل</h4><p>PP نقطه تعادل است؛ R سطح مقاومت و S سطح حمایت است. بالای PP تمایل صعودی و زیر PP فشار نزولی را نشان می‌دهد، اما این سطح‌ها تضمین برگشت قیمت نیستند.</p><div class="pivot-list">${pivotHtml || "داده کافی نیست"}</div></section>`;
  }

  function sourceCard(status) {
    const cls = status.status === "connected" ? "" : status.status === "failed" ? "bad" : "unknown";
    return `<div class="source-row"><i class="status-dot ${cls}"></i><span>${esc(status.label || status.name)}</span><b>${esc(statusText(status.status))}</b></div>`;
  }

  async function loadOverview() {
    try {
      const summary = await api("/api/market/summary");
      state.summary = summary;
      state.gold = summary.gold; state.dollar = summary.dollar; state.tepix = summary.tepix;
      marketQuote(state.gold, "gold"); marketQuote(state.dollar, "dollar"); marketQuote(state.tepix, "tepix");
      renderMetrics("gold", state.gold); renderMetrics("dollar", state.dollar);
      $("#gold-detail-price").textContent = state.gold?.price == null ? "داده در دسترس نیست" : `$ ${money(state.gold.price)}`;
      $("#dollar-detail-price").textContent = state.dollar?.price == null ? "داده در دسترس نیست" : `تومان ${money(state.dollar.price)}`;
      freshness($("#gold-detail-status"), state.gold?.status, state.gold?.data_timestamp);
      freshness($("#dollar-detail-status"), state.dollar?.status, state.dollar?.data_timestamp);
      freshness($("#tepix-analysis-status"), state.tepix?.status, state.tepix?.data_timestamp);
      $("#gold-source-line").textContent = `منبع: ${text(state.gold?.source)} · دریافت: ${formatDate(state.gold?.fetched_at)} · مشاهده بازار: ${formatDate(state.gold?.data_timestamp)}`;
      $("#dollar-source-line").textContent = `منبع: ${text(state.dollar?.source)} · دریافت: ${formatDate(state.dollar?.fetched_at)} · مشاهده بازار: ${formatDate(state.dollar?.data_timestamp)}`;
      $("#gold-analysis").innerHTML = analysisHtml(state.gold?.analysis);
      $("#dollar-analysis").innerHTML = analysisHtml(state.dollar?.analysis);
      $("#tepix-analysis").innerHTML = analysisHtml(state.tepix?.analysis);
      const sourceList = summary.sources || [];
      const connected = sourceList.filter((s) => s.status === "connected").length;
      $("#source-count").textContent = `${nf.format(connected)}/${nf.format(sourceList.length)}`;
      $("#sidebar-status").className = `status-dot ${connected ? "" : "bad"}`;
      $("#source-summary").innerHTML = sourceList.slice(0, 5).map(sourceCard).join("") || `<div class="source-row">منبع ثبت‌شده‌ای نیست</div>`;
      $("#last-updated").textContent = `آخرین بررسی ${formatDate(summary.as_of)}`;
      await loadFunds({ quiet: true, existing: summary.top_funds });
    } catch (err) {
      toast(`خواندن داشبورد انجام نشد: ${err.message}`, true);
    }
  }

  function renderNews(items) {
    const teaser = $("#news-teasers"), list = $("#news-list");
    if (!items.length) {
      const empty = `<div class="empty-state compact"><span>▧</span><b>خبر واقعی در دسترس نیست</b><small>اتصال RSS بازار را در وضعیت سامانه بررسی کنید.</small></div>`;
      if (teaser) teaser.innerHTML = empty;
      if (list) list.innerHTML = `<div class="empty-state"><span>▧</span><b>خبری در پایگاه داده نیست</b><small>پس از دریافت موفق RSS، خبرهای بازار اینجا نمایش داده می‌شوند.</small></div>`;
      return;
    }
    if (teaser) teaser.innerHTML = items.slice(0, 4).map((n) => `<div class="news-teaser"><span class="news-date">${esc(formatDate(n.published_at))}</span><div><strong>${esc(n.title)}</strong><small>${esc(n.source || "منبع نامشخص")}</small></div><span class="news-tag">${esc(n.category || "تحلیل‌نشده")}</span></div>`).join("");
    if (list) list.innerHTML = items.map((n) => `<div class="news-row"><div><strong>${esc(n.title)}</strong><small>${esc(n.source || "")} ${n.url ? `· <a href="${esc(n.url)}" target="_blank" rel="noopener">مشاهده منبع ↗</a>` : ""}</small></div><span class="news-state">${esc(n.category || "تحلیل‌نشده")}</span><span class="news-state">${esc(n.sentiment || "تحلیل نشده")} / ${esc(n.impact || "نامشخص")}</span><span>${esc(formatDate(n.published_at))}</span></div>`).join("");
  }

  async function loadFunds(options = {}) {
    try {
      const url = new URL("/api/funds", location.origin);
      const search = options.search ?? $("#fund-search")?.value ?? "";
      const category = options.category ?? $("#fund-category")?.value ?? "";
      const sort = options.sort ?? $("#fund-sort")?.value ?? "data_timestamp";
      url.searchParams.set("search", search); url.searchParams.set("category", category); url.searchParams.set("sort", sort);
      const data = await api(url.pathname + url.search);
      state.funds = sortedFundItems(data.items);
      $("#fund-result-count").textContent = `${nf.format(data.count)} صندوق`;
      renderFundTable(state.funds);
      renderMarketWatchlist(options.existing?.length ? options.existing : state.funds.slice(0, 5));
      $("#fund-count").textContent = nf.format(data.count);
      const fs = _sourceByName("rahavard_funds"); freshness($("#funds-freshness"), fs?.status || "unavailable", fs?.last_data_timestamp);
      const categories = Object.groupBy ? Object.groupBy(state.funds, (x) => x.category || "نامشخص") : state.funds.reduce((a, x) => ((a[x.category || "نامشخص"] ||= []).push(x), a), {});
      const cats = Object.entries(categories).sort((a, b) => b[1].length - a[1].length).slice(0, 3);
      const maximum = Math.max(1, ...cats.map((x) => x[1].length));
      $("#category-bars").innerHTML = cats.length ? cats.map(([name, rows]) => `<div class="cat-row"><span>${esc(name)}</span><div><i style="width:${rows.length / maximum * 100}%"></i></div><b>${nf.format(rows.length)}</b></div>`).join("") : `<div class="empty-state compact"><b>دسته صندوق در دسترس نیست</b></div>`;
      const best = state.funds.find((f) => f.technical_score != null);
      $("#best-fund").textContent = best ? (best.display_symbol || `شناسه ${best.rahavard_asset_id}`) : state.funds.length ? "برای امتیاز، نمایهٔ نماد را باز کنید" : "هنوز داده‌ای نیست";
    } catch (err) {
      if (!options.quiet) toast(`فهرست صندوق‌ها در دسترس نیست: ${err.message}`, true);
      $("#funds-freshness") && freshness($("#funds-freshness"), "unavailable", null);
    }
  }

  function _sourceByName(name) { return (state.summary?.sources || []).find((s) => s.name === name) || null; }

  const fundSortTextKeys = new Set(["name"]);
  function sortedFundItems(items) {
    const rows = [...(items || [])];
    const key = fundSortState.key;
    rows.sort((a, b) => {
      const left = a?.[key], right = b?.[key];
      if (fundSortTextKeys.has(key)) {
        return String(left ?? "").localeCompare(String(right ?? ""), "fa") * fundSortState.direction;
      }
      const leftNumber = Number(left), rightNumber = Number(right);
      const leftMissing = left == null || !Number.isFinite(leftNumber);
      const rightMissing = right == null || !Number.isFinite(rightNumber);
      if (leftMissing || rightMissing) return leftMissing === rightMissing ? 0 : leftMissing ? 1 : -1;
      return (leftNumber - rightNumber) * fundSortState.direction;
    });
    return rows;
  }

  function updateFundSortIndicators() {
    $$('[data-fund-sort]').forEach((header) => {
      const active = header.dataset.fundSort === fundSortState.key;
      header.classList.toggle("is-sorted", active);
      header.setAttribute("aria-sort", active ? (fundSortState.direction === 1 ? "ascending" : "descending") : "none");
      const indicator = $(".sort-indicator", header);
      if (indicator) indicator.textContent = active ? (fundSortState.direction === 1 ? "▲" : "▼") : "⇅";
    });
  }

  function sortFundTable(key) {
    if (!key) return;
    if (fundSortState.key === key) fundSortState.direction *= -1;
    else {
      fundSortState.key = key;
      fundSortState.direction = fundSortTextKeys.has(key) ? 1 : -1;
    }
    state.funds = sortedFundItems(state.funds);
    renderFundTable(state.funds);
  }

  // ETF directory rows expose a Rahavard asset ID, not necessarily an exchange ticker.
  function renderFundTable(items) {
    const target = $("#fund-table");
    if (!items.length) {
      target.innerHTML = `<tr><td colspan="9"><div class="empty-state"><span>&#9632;</span><b>صندوقی از ره‌آورد۳۶۵ دریافت نشده</b><small>وضعیت اتصال ره‌آورد را در صفحه وضعیت سامانه ببینید.</small></div></td></tr>`;
      return;
    }
    const amount = (value) => value == null ? "—" : money(value);
    target.innerHTML = items.map((f) => {
      const id = f.rahavard_asset_id || f.symbol;
      const price = f.market_price ?? f.real_close_price;
      return `<tr><td><button class="row-open" data-fund="${esc(f.fund_key || f.symbol)}"><span class="fund-table-name"><strong>${esc(f.name)}</strong><small class="fund-symbol">شناسه ره‌آورد: ${esc(id)}</small></span></button></td><td>${amount(price)}</td><td><span class="${changeClass(f.daily_return)}">${pct(f.daily_return)}</span></td><td>${pct(f.monthly_return)}</td><td>${pct(f.three_month_return)}</td><td>${pct(f.six_month_return)}</td><td>${pct(f.one_year_return)}</td><td>${amount(f.volume)}</td><td>${amount(f.value)}</td></tr>`;
    }).join("");
    updateFundSortIndicators();
  }

  function renderMarketWatchlist(items) {
    const target = $("#watchlist");
    if (!items?.length) {
      target.innerHTML = `<div class="empty-state compact"><span>▤</span><b>هنوز صندوقی دریافت نشده</b><small>اتصال فهرست ETF ره‌آورد را در وضعیت سامانه بررسی کنید.</small></div>`;
      return;
    }
    target.innerHTML = items.slice(0, 5).map((f) => {
      const id = f.rahavard_asset_id || f.symbol;
      return `<div class="fund-row"><div class="fund-name"><span class="fund-symbol-box">ETF</span><div><strong>${esc(f.name || id)}</strong><small>شناسه ره‌آورد ${esc(id)}</small></div></div><span class="num ${changeClass(f.daily_return)}">${pct(f.daily_return)}</span><span class="num">${f.value == null ? "—" : money(f.value)}</span></div>`;
    }).join("");
  }

  async function showFund(symbol) {
    try {
      const data = await api(`/api/funds/${encodeURIComponent(symbol)}`);
      const section = $("#fund-detail");
      section.classList.remove("hidden");
      const f = data.fund || {}, a = data.analysis;
      const id = f.rahavard_asset_id || f.symbol;
      const displaySymbol = f.display_symbol || `شناسه ره‌آورد ${id}`;
      const props = [
        ["شناسه ره‌آورد", id], ["نماد معاملاتی", f.display_symbol],
        ["نوع صندوق", f.category], ["مدیر", f.manager], ["متولی", f.custodian],
        ["قیمت پایانی (ریال)", f.market_price], ["NAV آماری (ریال)", f.nav],
        ["فاصله قیمت از NAV", f.nav_premium_pct == null ? null : `${num(f.nav_premium_pct)}٪`],
        ["ارزش معامله (ریال)", f.value], ["حجم معامله", f.volume],
        ["زمان داده", f.data_timestamp]
      ];
      const propsHtml = props.map(([label, value]) => {
        const rendered = typeof value === "number" ? money(value) : text(value);
        return `<div class="property"><span>${label}</span><b>${esc(rendered)}</b></div>`;
      }).join("");
      const portfolioNote = data.portfolio_note || "ترکیب تفصیلی دارایی در نمایه عمومی ره‌آورد برنگشت.";
      section.innerHTML = `<div class="fund-detail-head"><div><span class="panel-kicker">نمایه صندوق · ${esc(displaySymbol)}</span><h2>${esc(f.name || displaySymbol)}</h2><p>فهرست، قیمت، NAV و اندیکاتورهای رسمی ره‌آورد۳۶۵ · داده تا ${esc(formatDate(f.data_timestamp))}</p></div><button class="icon-button" data-close-fund aria-label="بستن">×</button></div><div class="fund-detail-body"><div><div class="fund-properties">${propsHtml}</div><h3 style="margin:16px 0 8px">ترکیب دارایی</h3>${data.portfolio?.length ? data.portfolio.map((p) => `<div class="source-row"><span>${esc(p.asset_type)}</span><b>${p.percentage == null ? "—" : `${num(p.percentage)}٪`}</b></div>`).join("") : `<div class="factor-foot">${esc(portfolioNote)}</div>`}</div><div><h3>داده‌های تکمیلی</h3><p class="fund-chart-caption">تاریخچه و NAV از ره‌آورد دریافت شده‌اند و برای تحلیل شاخص‌ها استفاده می‌شوند.</p><div class="source-line">منبع: ره‌آورد۳۶۵ · ${nf.format(data.history?.length || 0)} مشاهده قیمت · ${nf.format(data.nav_history?.length || 0)} مشاهدهٔ NAV</div><a class="button button-quiet" href="/api/funds/${encodeURIComponent(symbol)}/history" target="_blank" rel="noopener">مشاهدهٔ دادهٔ خام قیمت و NAV</a></div></div><div class="fund-analysis-full"><h3>تحلیل تکنیکال ره‌آورد</h3>${analysisHtml(a)}</div>`;
      section.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      toast(`نمایه صندوق باز نشد: ${err.message}`, true);
    }
  }

  const numericInputValue = (value) => value == null || !Number.isFinite(Number(value)) ? "" : String(Number(value));
  function watchlistLevelsHtml(levels) {
    return levels?.length ? `<div class="watch-level-list">${levels.map((level) => `<span class="watch-level"><b>${money(level.price)}</b><small>${esc(level.label)}</small></span>`).join("")}</div>` : `<span class="watch-muted">سطحی نزدیک قیمت پیدا نشد</span>`;
  }
  function renderPersonalWatchlist(items, totals = {}) {
    const body = $("#watchlist-table-body");
    $("#watchlist-count").textContent = `${nf.format(items.length)} صندوق`;
    const totalNode = $("#watchlist-totals");
    if (totalNode) {
      const pnlClass = Number(totals.pnl) > 0 ? "positive" : Number(totals.pnl) < 0 ? "negative" : "";
      totalNode.innerHTML = [
        ["مجموع واحدها", num(totals.units, 2), ""],
        ["ارزش خرید", money(totals.cost_basis), ""],
        ["ارزش فعلی", money(totals.market_value), ""],
        ["سود / زیان کل", `${money(totals.pnl)} · ${pct(totals.pnl_pct)}`, pnlClass],
      ].map(([label, value, cls]) => `<div class="watch-total-card ${cls}"><span>${label}</span><b>${value}</b></div>`).join("");
    }
    if (!items.length) {
      body.innerHTML = `<tr><td colspan="6"><div class="empty-state"><span>◎</span><b>هنوز نمادی در دیده‌بان نیست</b><small>از کادر بالا یک صندوق ره‌آورد را با نام یا شناسه‌اش اضافه کن.</small></div></td></tr>`;
      return;
    }
    body.innerHTML = items.map((item) => {
      const tone = item.outlook_tone || "unknown";
      return `<tr data-watch-row="${esc(item.fund_key)}">
        <td class="watch-fund-cell" data-label="صندوق / نماد"><button class="watch-fund-open" type="button" data-watch-open="${esc(item.fund_key)}" aria-label="مشاهده تحلیل ${esc(item.name)}"><span class="watch-fund-mark">ETF</span><span><strong>${esc(item.name)}</strong><small>${esc(item.symbol || `شناسه ${item.rahavard_asset_id || "—"}`)} · ره‌آورد۳۶۵</small></span><span class="watch-open-arrow">←</span></button></td>
        <td class="watch-price" data-label="قیمت فعلی (ریال)"><b>${money(item.price)}</b>${item.daily_return == null ? "" : `<small class="${Number(item.daily_return) >= 0 ? "positive" : "negative"}">${pct(item.daily_return)}</small>`}</td>
        <td data-label="قیمت سر به سر (ریال)"><input class="watch-input" type="number" min="0" step="any" inputmode="decimal" aria-label="قیمت سر به سر ${esc(item.name)} به ریال" placeholder="قیمت خرید" data-watch-field="break_even_price" value="${numericInputValue(item.break_even_price)}"></td>
        <td data-label="تعداد واحد من"><input class="watch-input watch-units" type="number" min="0" step="any" inputmode="decimal" aria-label="تعداد واحد ${esc(item.name)}" placeholder="تعداد" data-watch-field="units" value="${numericInputValue(item.units)}"></td>
        <td data-label="برداشت میان‌مدت"><span class="watch-outlook ${tone}">${esc(item.midterm_outlook || "داده کافی نیست")}</span><small class="watch-source-note">برای تحلیل کامل روی نام نماد کلیک کن</small></td>
        <td data-label="مدیریت"><button class="watch-remove" type="button" data-watch-remove="${esc(item.fund_key)}" aria-label="حذف ${esc(item.name)} از دیده‌بان">حذف</button></td>
      </tr>`;
    }).join("");
  }
  async function loadWatchlist() {
    const body = $("#watchlist-table-body");
    body.innerHTML = `<tr><td colspan="6"><div class="empty-state compact"><b>در حال دریافت قیمت و تحلیل ره‌آورد…</b></div></td></tr>`;
    try {
      const [data, fundsData] = await Promise.all([
        api("/api/watchlist"),
        state.funds.length ? Promise.resolve({ items: state.funds }) : api("/api/funds")
      ]);
      state.watchlist = data.items || [];
      state.funds = fundsData.items || [];
      const seenAssetIds = new Set();
      $("#watchlist-symbol-options").innerHTML = state.funds.map((fund) => {
        const raw = fund.raw || {};
        const id = fund.rahavard_asset_id || raw.rahavard_asset_id || fund.fund_key || fund.symbol;
        if (seenAssetIds.has(String(id))) return "";
        seenAssetIds.add(String(id));
        const label = `${fund.name || "صندوق"} · ${fund.display_symbol || `شناسه ${id}`}`;
        return `<option value="${esc(id)}" label="${esc(label)}"></option>`;
      }).join("");
      renderPersonalWatchlist(state.watchlist, data.totals || {});
    } catch (err) {
      body.innerHTML = `<tr><td colspan="6"><div class="empty-state"><b>دیده‌بان بارگیری نشد</b><small>${esc(err.message)}</small></div></td></tr>`;
      toast(`دیده‌بان بارگیری نشد: ${err.message}`, true);
    }
  }

  function toggleMarketAnalysis(key) {
    const panel = $("[data-analysis-panel=\"" + key + "\"]");
    if (!panel) return;
    const shouldOpen = panel.classList.contains("hidden");
    $$("[data-analysis-panel]").forEach((node) => node.classList.add("hidden"));
    $$("[data-analysis-toggle]").forEach((node) => {
      node.classList.remove("is-open");
      const hint = $(".analysis-toggle-hint", node);
      if (hint) hint.textContent = "\u0628\u0631\u0627\u06cc \u0645\u0634\u0627\u0647\u062f\u0647 \u062a\u062d\u0644\u06cc\u0644 \u0639\u062f\u062f\u06cc \u06a9\u0644\u06cc\u06a9 \u06a9\u0646\u06cc\u062f \u2190";
    });
    if (shouldOpen) {
      panel.classList.remove("hidden");
      const trigger = $("[data-analysis-toggle=\"" + key + "\"]");
      trigger?.classList.add("is-open");
      const hint = trigger ? $(".analysis-toggle-hint", trigger) : null;
      if (hint) hint.textContent = "\u0628\u0633\u062a\u0646 \u062a\u062d\u0644\u06cc\u0644 \u2191";
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  async function loadAdmin() {
    try {
      const data = await api("/api/admin");
      const count = data.health.counts || {};
      $("#admin-stats").innerHTML = [["نقاط قیمت", count.prices], ["صندوق‌ها", count.funds], ["هشدارها", count.alerts]].map(([label, value]) => `<div class="admin-stat"><span>${label}</span><b>${nf.format(value || 0)}</b></div>`).join("");
      $("#admin-sources").innerHTML = data.sources.map((s) => `<div class="source-table-row"><strong>${esc(s.label)}</strong><span>${esc(statusText(s.status))}</span><small title="${esc(s.error || s.source_url || "")}">${esc(s.error || (s.last_data_timestamp ? `داده: ${formatDate(s.last_data_timestamp)}` : s.source_url || "بدون همگام‌سازی"))}</small></div>`).join("");
      $("#admin-logs").innerHTML = data.recent_logs.length ? data.recent_logs.map((l) => `<div class="log-row"><time>${esc(formatDate(l.started_at))}</time><div><strong>${esc(l.source)} · ${esc(l.status === "success" ? "موفق" : "ناموفق")} · ${nf.format(l.records)} ردیف</strong><small>${esc(l.message || "")}</small></div></div>`).join("") : `<div class="empty-state compact"><b>گزارشی ثبت نشده</b><small>پس از همگام‌سازی، فعالیت منابع ثبت می‌شود.</small></div>`;
    } catch (err) { toast(`وضعیت سامانه خوانده نشد: ${err.message}`, true); }
  }

  async function loadSettings() {
    try {
      const s = await api("/api/settings");
      $("#settings-theme").value = s.theme || "dark";
      const intervalSelect = $("#settings-refresh-interval");
      const intervalValue = String(s.data_update_interval);
      if (![...intervalSelect.options].some((option) => option.value === intervalValue)) intervalSelect.add(new Option(`${nf.format(s.data_update_interval)} سانیه`, intervalValue));
      intervalSelect.value = intervalValue;
      $("#refresh-interval-label").textContent = `${nf.format(s.data_update_interval / 60)} دقیقه`;
      $("#stale-threshold-label").textContent = `${nf.format(s.max_stale_hours)} ساعت`;
      const src = await api("/api/market/sources");
      $("#settings-sources").innerHTML = src.sources.map((x) => `<div class="settings-source"><i class="status-dot ${x.status === "connected" ? "" : x.status === "failed" ? "bad" : "unknown"}"></i><span>${esc(x.label)}</span><b>${esc(statusText(x.status))}</b></div>`).join("");
      await loadAlerts();
    } catch (err) { toast(`تنظیمات بارگیری نشد: ${err.message}`, true); }
  }

  async function loadAlerts() {
    const data = await api("/api/alerts");
    const target = $("#alerts-list");
    target.innerHTML = data.items.length ? data.items.map((a) => `<div class="alert-row"><div><strong>${esc(a.symbol)} · ${esc(a.condition)}</strong><small>${a.fund_name ? `${esc(a.fund_name)} ? ` : ""}${a.threshold == null ? "بدون آستانه قیمتی" : `آستانه ${money(a.threshold)}`}</small></div><span class="news-state">${a.triggered_at ? `فعال شد · ${esc(formatDate(a.triggered_at))}` : "در انتظار شرط"}</span><span>${esc(a.message || "فعال")}</span></div>`).join("") : `<div class="empty-state compact"><b>هشداری ثبت نشده</b><small>نماد و شرط دلخواه را اضافه کن.</small></div>`;
  }

  async function openView(name) {
    if (!$("#view-" + name)) return;
    state.currentView = name;
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    const title = ({ overview: "داشبورد", markets: "طلا و دلار", funds: "صندوق‌ها", watchlist: "دیده‌بان", settings: "تنظیمات", admin: "وضعیت سامانه" })[name] || "داشبورد";
    $("#crumb-current").textContent = title;
    if (name === "funds") await loadFunds();
    if (name === "watchlist") await loadWatchlist();
    if (name === "admin") await loadAdmin();
    if (name === "settings") await loadSettings();
    if (name === "markets") await loadOverview();
    if (name === "overview") await loadOverview();
  }

  async function doRefresh() {
    const buttons = $$('[data-refresh], #refresh-button, #refresh-primary');
    buttons.forEach((b) => { b.disabled = true; b.classList.add("spinning"); });
    toast("دریافت داده از منابع آغاز شد…");
    try {
      const result = await api("/api/refresh", { method: "POST" });
      const ok = (result.sources || []).filter((x) => x.status === "connected").length;
      toast(`بررسی منابع پایان یافت · ${nf.format(ok)} منبع متصل`);
      await loadOverview();
      if (state.currentView === "admin") await loadAdmin();
      if (state.currentView === "funds") await loadFunds();
      if (state.currentView === "watchlist") await loadWatchlist();
    } catch (err) { toast(`همگام‌سازی کامل نشد: ${err.message}`, true); }
    finally { buttons.forEach((b) => { b.disabled = false; b.classList.remove("spinning"); }); }
  }

  $$(".nav-item").forEach((button) => button.addEventListener("click", () => openView(button.dataset.view)));
  $$('[data-open-view]').forEach((button) => button.addEventListener("click", () => openView(button.dataset.openView)));
  $$('[data-refresh], #refresh-button, #refresh-primary').forEach((button) => button.addEventListener("click", doRefresh));
  $("#theme-toggle").addEventListener("click", async () => {
    const next = document.body.classList.contains("light-mode") ? "dark" : "light";
    document.body.classList.toggle("light-mode", next === "light");
    try { await api("/api/settings", { method: "PUT", body: JSON.stringify({ key: "theme", value: next }) }); } catch {}
  });
  $("#settings-theme").addEventListener("change", (event) => {
    const next = event.target.value;
    document.body.classList.toggle("light-mode", next === "light");
    api("/api/settings", { method: "PUT", body: JSON.stringify({ key: "theme", value: next }) }).then(() => toast("تنظیم تم ذخیره شد"));
  });
  $("#save-refresh-interval").addEventListener("click", async () => {
    const value = $("#settings-refresh-interval").value;
    try {
      await api("/api/settings", { method: "PUT", body: JSON.stringify({ key: "refresh_interval_seconds", value }) });
      $("#refresh-interval-label").textContent = `${nf.format(Number(value) / 60)} دقیقه`;
      toast("فاصله تازه‌سازی ذخیره شد");
    } catch (err) { toast(`ذخیره فاصله انجام نشد: ${err.message}`, true); }
  });
  $("#alert-condition").addEventListener("change", (event) => {
    const priceCondition = ["price_above", "price_below"].includes(event.target.value);
    $("#alert-threshold").required = priceCondition;
    $("#alert-threshold").disabled = !priceCondition;
  });
  $("#alert-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const condition = $("#alert-condition").value;
    const thresholdText = $("#alert-threshold").value;
    try {
      await api("/api/alerts", { method: "POST", body: JSON.stringify({
        symbol: $("#alert-symbol").value.trim(), condition,
        threshold: thresholdText === "" ? null : Number(thresholdText)
      }) });
      $("#alert-form").reset();
      $("#alert-threshold").disabled = false;
      toast("هشدار محلی ثبت شد");
      await loadAlerts();
    } catch (err) { toast(`هشدار ثبت نشد: ${err.message}`, true); }
  });
  ["#fund-search", "#fund-category"].forEach((id) => {
    const control = $(id);
    if (!control) return;
    control.addEventListener(id === "#fund-search" ? "input" : "change", () => {
      clearTimeout(loadFunds.timer); loadFunds.timer = setTimeout(() => loadFunds(), id === "#fund-search" ? 250 : 0);
    });
  });
  $("#watchlist-add-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const symbol = $("#watchlist-symbol").value.trim();
    if (!symbol) return;
    try {
      const result = await api("/api/watchlist", { method: "POST", body: JSON.stringify({ symbol }) });
      $("#watchlist-symbol").value = "";
      toast(result.created ? "صندوق به دیده‌بان اضافه شد" : "این صندوق از قبل در دیده‌بان است");
      await loadWatchlist();
    } catch (err) { toast(`افزودن صندوق انجام نشد: ${err.message}`, true); }
  });
  $("#watchlist-table-body").addEventListener("change", async (event) => {
    const input = event.target.closest("[data-watch-field]");
    if (!input) return;
    const row = input.closest("[data-watch-row]");
    const raw = input.value.trim();
    const value = raw === "" ? null : Number(raw);
    if (value !== null && (!Number.isFinite(value) || value < 0)) {
      toast("مقدار باید عددی و صفر یا بزرگ‌تر باشد", true);
      return;
    }
    try {
      await api(`/api/watchlist/${encodeURIComponent(row.dataset.watchRow)}`, {
        method: "PUT", body: JSON.stringify({ [input.dataset.watchField]: value })
      });
      toast("اطلاعات دیده‌بان ذخیره شد");
    } catch (err) { toast(`ذخیره مقدار انجام نشد: ${err.message}`, true); }
  });
 $("#watchlist-table-body").addEventListener("click", async (event) => {
    const open = event.target.closest("[data-watch-open]");
    if (open) {
      await openView("funds");
      await showFund(open.dataset.watchOpen);
      return;
    }
   const button = event.target.closest("[data-watch-remove]");
   if (!button) return;
    try {
      await api(`/api/watchlist/${encodeURIComponent(button.dataset.watchRemove)}`, { method: "DELETE" });
      toast("صندوق از دیده‌بان حذف شد");
      await loadWatchlist();
    } catch (err) { toast(`حذف صندوق انجام نشد: ${err.message}`, true); }
  });
  $("#watchlist-refresh").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.classList.add("spinning");
    try { await loadWatchlist(); }
    finally { button.disabled = false; button.classList.remove("spinning"); }
  });
  $("#fund-table").addEventListener("click", (event) => { const button = event.target.closest("[data-fund]"); if (button) showFund(button.dataset.fund); });
  $("#fund-table-grid").addEventListener("click", (event) => {
    const header = event.target.closest("th[data-fund-sort]");
    if (header) sortFundTable(header.dataset.fundSort);
  });
  $("#fund-table-grid").addEventListener("keydown", (event) => {
    const header = event.target.closest("th[data-fund-sort]");
    if (!header || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    sortFundTable(header.dataset.fundSort);
  });
  $("#fund-detail").addEventListener("click", (event) => { if (event.target.closest("[data-close-fund]")) $("#fund-detail").classList.add("hidden"); });
  $(".market-detail-grid").addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-analysis-toggle]");
    if (trigger) toggleMarketAnalysis(trigger.dataset.analysisToggle);
  });
  $(".market-detail-grid").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const trigger = event.target.closest("[data-analysis-toggle]");
    if (!trigger) return;
    event.preventDefault();
    toggleMarketAnalysis(trigger.dataset.analysisToggle);
  });
  $("#global-search").addEventListener("input", (event) => {
    const value = event.target.value.trim();
    if (value.length >= 2) { openView("funds"); $("#fund-search").value = value; loadFunds({ search: value }); }
  });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#global-search").focus(); }
    if (event.key === "Escape") { $("#global-search").value = ""; }
  });
  $("#global-search").addEventListener("search", () => { if (!$("#global-search").value) openView("overview"); });
 localDateClock(); setInterval(localDateClock, 30_000);
  installEnglishDigits();
 api("/api/settings").then((s) => document.body.classList.toggle("light-mode", s.theme === "light")).catch(() => {});
  loadOverview();
})();
