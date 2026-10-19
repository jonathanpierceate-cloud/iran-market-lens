(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const horizonStorageKey = "alivest.investmentHorizon";
  let savedHorizon = "long";
  try { savedHorizon = localStorage.getItem(horizonStorageKey) === "short" ? "short" : "long"; } catch {}
  const state = { summary: null, gold: null, gold18k: null, dollar: null, tepix: null, funds: [], watchlist: [], watchlistSortMode: "default", watchlistTotals: {}, currentView: "overview", investmentHorizon: savedHorizon, watchlistRefreshTimer: null, watchlistRefreshSeconds: 900 };
  const fundSortState = { key: "data_timestamp", direction: -1 };
  let fundScoreFillRunning = false;
  let fundScoreGeneration = 0;
  const fundScoreAttemptedKeys = new Set();
  let fundNavFillRunning = false;
  let fundNavGeneration = 0;
  const fundNavAttemptedKeys = new Set();
  const fundNavValueCache = new Map();
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
  const compactText = (value, max = 150) => {
    const clean = String(value ?? "").replace(/\s+/g, " ").trim();
    if (!clean || clean.length <= max) return clean;
    const slice = clean.slice(0, max);
    const boundary = Math.max(slice.lastIndexOf("؛"), slice.lastIndexOf("،"), slice.lastIndexOf(". "));
    return `${(boundary > max * .55 ? slice.slice(0, boundary) : slice).trim()}…`;
  };
  const trendText = (value) => ({ bullish: "صعودی", bearish: "نزولی", neutral: "خنثی", unavailable: "داده ناکافی" }[value] || "داده ناکافی");
  const statusText = (status) => ({ available: "تازه", connected: "متصل", stale: "کهنه", cached_after_source_error: "آخرین داده", failed: "خطا", not_tested: "بررسی‌نشده", unavailable: "در دسترس نیست", disabled: "غیرفعال" }[status] || status || "نامشخص");

  async function api(path, options = {}) {
    const requestUrl = new URL(path, location.origin);
    if (requestUrl.origin === location.origin && requestUrl.pathname.startsWith("/api/")) {
      requestUrl.searchParams.set("horizon", state.investmentHorizon);
    }
    const response = await fetch(requestUrl.pathname + requestUrl.search + requestUrl.hash, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
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
    node.classList.add(status === "available" || status === "connected" ? "good" : status === "failed" || status === "stale" || status === "cached_after_source_error" ? "stale" : "bad");
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
    const selectedTrend = quote.analysis?.score_band || quote.analysis?.trend || quote.analysis?.medium_term_trend;
    trend.textContent = trendText(selectedTrend);
    trend.className = `trend ${selectedTrend || "neutral"}`;
    const trendHeading = trend.parentElement?.querySelector("span");
    if (trendHeading) trendHeading.textContent = `جمع‌بندی ${quote.analysis?.investment_horizon_label || horizonLabel(state.investmentHorizon)}`;
    const scoreEl = $(`#${prefix}-score`);
    if (scoreEl) scoreEl.textContent = quote.analysis?.technical_score == null ? "—" : `${num(quote.analysis.technical_score, 0)} / ۱۰۰`;
  }

  function renderGold18kValuation(valuation) {
    const price = $("#gold18k-price");
    const theoreticalEl = $("#gold18k-theoretical-price");
    const bubble = $("#gold18k-bubble-value");
    const bubblePercent = $("#gold18k-bubble-percent");
    if (!price || !theoreticalEl || !bubble || !bubblePercent) return;

    const theoretical = valuation?.theoretical_price;
    const observed = valuation?.observed_price ?? valuation?.rahavard_price;
    const difference = valuation?.bubble;
    const percent = valuation?.bubble_percent;
    price.classList.remove("unavailable-text");
    price.textContent = observed == null ? "\u2014" : money(observed);
    theoreticalEl.textContent = theoretical == null ? "\u2014" : money(theoretical);
    bubble.textContent = difference == null ? "\u2014" : `${Number(difference) > 0 ? "+" : ""}${money(difference)}`;
    bubble.className = `valuation-value ${difference == null ? "" : changeClass(Number(difference))}`;
    bubblePercent.textContent = percent == null ? "\u2014" : `${Number(percent) > 0 ? "+" : ""}${num(percent, 2)}%`;
    bubblePercent.className = difference == null ? "" : changeClass(Number(difference));
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

  const indicatorFa = { "RSI(14)": "شاخص قدرت نسبی", "MFI(14)": "شاخص جریان پول", "CCI(14)": "شاخص کانال کالا", "WR(14)": "Williams %R", "SO(14)": "نوسان‌گر تصادفی", "Aroon(25)": "آرون", "ARRON(25)": "آرون", "ADX(14)": "قدرت روند", "AO(5,34)": "شتاب Awesome", "StochRSI(14)": "استوکاستیک RSI", "MACD(12,26,9)": "مکدی", "MTM(6)": "شتاب قیمت", "Ichimoku(9,26,52,26)": "ایچیموکو", "ATR(14)": "دامنه واقعی میانگین", "KELTNER(16)": "کانال کلتنر", "BB(20)": "باند بولینگر", "VRSI(14)": "RSI حجم", "VMACD(12,26)": "مکدی حجم", "OBV(20)": "حجم تعادلی", "RV(15)": "\u0646\u0633\u0628\u062a \u062d\u062c\u0645 \u06f1\u06f5\u0631\u0648\u0632\u0647", "RV(30)": "\u0646\u0633\u0628\u062a \u062d\u062c\u0645 \u06f3\u06f0\u0631\u0648\u0632\u0647", "RV(90)": "\u0646\u0633\u0628\u062a \u062d\u062c\u0645 \u06f9\u06f0\u0631\u0648\u0632\u0647", "HV(15)": "\u0646\u0648\u0633\u0627\u0646 \u062a\u0627\u0631\u06cc\u062e\u06cc \u06f1\u06f5\u0631\u0648\u0632\u0647", "HV(30)": "\u0646\u0648\u0633\u0627\u0646 \u062a\u0627\u0631\u06cc\u062e\u06cc \u06f3\u06f0\u0631\u0648\u0632\u0647", "HV(90)": "\u0646\u0648\u0633\u0627\u0646 \u062a\u0627\u0631\u06cc\u062e\u06cc \u06f9\u06f0\u0631\u0648\u0632\u0647" };
  const hasNumericValue = (value) => value != null && value !== "" && Number.isFinite(Number(value));
  const hasIndicatorValue = (item) => {
    const value = item?.value;
    if (Array.isArray(value)) return value.some((part) => hasNumericValue(part?.value));
    if (value && typeof value === "object") return Object.values(value).some(hasNumericValue);
    return hasNumericValue(value);
  };
  const factorFa = { trend: "روند", momentum: "شتاب", moving_averages: "میانگین‌ها", volume: "حجم", volatility: "نوسان", oscillators: "نوسان‌گرها", support_resistance: "حمایت و مقاومت" };
  const signalFa = { strong_buy: "بررسی خرید · قوی", buy: "بررسی خرید", hold: "انتظار / نگهداری", sell: "احتیاط", strong_sell: "ریسک بالا", unavailable: "داده ناکافی" };

  function indicatorMeaning(key, value) {
    if (/^(EMA|SMA)\(/.test(key)) return `میانگین قیمت در دوره ${key.match(/\d+/)?.[0] || "مشخص"}؛ قیمت بالاتر از آن معمولاً به نفع روند صعودی است.`;
    const meanings = {
      "RSI(14)": "در مدل: RSI تا ۳۵ ناحیه خرید (امتیاز ۷۰ تا ۱۰۰)، ۳۵ تا ۶۰ خنثی و از ۶۰ به بالا ناحیه فروش (امتیاز ۴۰ و کمتر) است.",
      "MFI(14)": "فشار خرید و فروش با درنظرگرفتن حجم؛ زیر ۲۰ فروش‌زدگی و بالای ۸۰ خریدزدگی را نشان می‌دهد.",
      "CCI(14)": "فاصله قیمت از میانگین؛ بالای ۱۰۰ حرکت قوی و زیر منفی ۱۰۰ ضعف یا فروش‌زدگی را نشان می‌دهد.",
      "WR(14)": "جایگاه قیمت در دامنه ۱۴ دوره؛ بالای منفی ۲۰ خریدزدگی و زیر منفی ۸۰ فروش‌زدگی است.",
      "SO(14)": "جایگاه قیمت در دامنه اخیر؛ بالای ۸۰ خریدزدگی و زیر ۲۰ فروش‌زدگی است.",
      "Aroon(25)": "تازگی ثبت سقف و کف ۲۵ دوره را می‌سنجد؛ خط بالاتر جهت غالب را نشان می‌دهد.",
      "ARRON(25)": "تازگی ثبت سقف و کف ۲۵ دوره را می‌سنجد؛ خط بالاتر جهت غالب را نشان می‌دهد.",
      "ADX(14)": "قدرت روند را می‌سنجد، نه جهت آن؛ بالای ۲۵ معمولاً روند قوی‌تر است. جهت از +DI و −DI خوانده می‌شود.",
      "AO(5,34)": "شتاب کوتاه‌مدت در برابر بلندمدت؛ مثبت به نفع شتاب صعودی و منفی نشانه شتاب نزولی است.",
      "StochRSI(14)": "مقیاس ۰ تا ۱۰۰؛ زیر ۳۰ ناحیه خرید، بالای ۶۰ ناحیه فروش و بین آن‌ها خنثی است.",
      "MACD(12,26,9)": "اختلاف میانگین‌های نمایی؛ هیستوگرام مثبت یعنی خط MACD بالای خط سیگنال و منفی یعنی پایین آن است.",
      "MTM(6)": "تغییر قیمت نسبت به ۶ دوره قبل؛ مثبت یعنی شتاب رو به بالا و منفی یعنی شتاب رو به پایین.",
      "Ichimoku(9,26,52,26)": "خط عددی مقدار تنکان است؛ وضعیت روند را با جای قیمت نسبت به ابر و تقاطع تنکان/کیجون بسنجید.",
      "ATR(14)": "میانگین دامنه نوسان قیمت؛ عدد بزرگ‌تر یعنی حرکت روزانه بیشتر، نه جهت صعود یا نزول.",
      "KELTNER(16)": "داخل باند خنثی است؛ نزدیک سقف در روند صعودی نشانه منفی و برگشت از کف باند نشانه مثبت است.",
      "BB(20)": "داخل باند خنثی است؛ نزدیک سقف در روند صعودی نشانه منفی و برگشت از کف باند نشانه مثبت است.",
      "VRSI(14)": "RSI محاسبه‌شده روی حجم معاملات؛ تغییر فشار حجم را نشان می‌دهد، نه جهت مستقیم قیمت.",
      "VMACD(12,26)": "شتاب تغییر حجم؛ مثبت یعنی میانگین کوتاه حجم بالاتر از بلندمدت است.",
      "OBV(20)": "حجم تجمعی با جهت حرکت قیمت؛ مقایسه با میانگین ۲۰روزه به تأیید یا تضعیف روند کمک می‌کند.",
      "RV(15)": "نوسان تاریخی سالانه‌شده بر پایه بازده ۱۵روزه؛ مقدار بیشتر یعنی ریسک نوسان بیشتر، نه جهت خاص.",
      "RV(30)": "نوسان تاریخی سالانه‌شده بر پایه بازده ۳۰روزه؛ مقدار بیشتر یعنی ریسک نوسان بیشتر، نه جهت خاص.",
      "RV(90)": "نوسان تاریخی سالانه‌شده بر پایه بازده ۹۰روزه؛ مقدار بیشتر یعنی ریسک نوسان بیشتر، نه جهت خاص.",
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
    const first = value("value", "rsi", "mfi", "cci", "wr", "awesome", "mtm", "rv", "vrsi", "obv");
    if (/^hv/i.test(name) && Number.isFinite(first)) return "\u0646\u0648\u0633\u0627\u0646 \u062a\u0627\u0631\u06cc\u062e\u06cc \u0633\u0627\u0644\u0627\u0646\u0647\u200c\u0634\u062f\u0647 \u0628\u0631\u0627\u0628\u0631 " + num(first, 2) + "% \u0627\u0633\u062a\u061b \u0645\u0642\u062f\u0627\u0631 \u0628\u0627\u0644\u0627\u062a\u0631 \u0628\u0647\u200c\u0645\u0639\u0646\u06cc \u0631\u06cc\u0633\u06a9 \u0646\u0648\u0633\u0627\u0646 \u0628\u06cc\u0634\u062a\u0631 \u0627\u0633\u062a.";
    if (/^rsi/i.test(name) && Number.isFinite(first)) return `عدد ${num(first, 2)} است؛ ${first <= 35 ? "در محدوده خرید مدل (امتیاز ۷۰ تا ۱۰۰) است." : first >= 60 ? "در محدوده فروش مدل (امتیاز ۴۰ و کمتر) است." : "در محدوده خنثی مدل قرار دارد."}`;
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
    if (/stochrsi/i.test(name) && Number.isFinite(first)) {
      const scaled = first <= 1 ? first * 100 : first;
      return `عدد ${num(scaled, 1)} از ۱۰۰ است؛ ${scaled >= 60 ? "در ناحیه فروش مدل است." : scaled < 30 ? "در ناحیه خرید مدل است." : "در محدوده خنثی مدل است."}`;
    }
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
      const scenarioText = signal === "bouncefromlower" ? "برگشت مثبت از کف باند" : signal === "nearupperuptrend" ? "نزدیک سقف در روند صعودی؛ وضعیت منفی" : signal === "neutral" ? "قیمت داخل باند؛ وضعیت خنثی" : signal === "breakoutdown" ? "قیمت پایین‌تر از کف باند است" : signal === "breakoutup" ? "قیمت بالاتر از سقف باند است" : `سیگنال ${signalText}`;
      return `سقف ${num(upper, 2)} (${Number.isFinite(distance) ? `فاصله ${pct(distance * 100)}` : "فاصله —"}) و کف ${num(lower, 2)} (${Number.isFinite(dl) ? `فاصله ${pct(dl * 100)}` : "فاصله —"})؛ ${scenarioText}.`;
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

  function indicatorScoreMap(analysis) {
    const scores = new Map();
    const normalize = (key) => String(key || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const add = (key, score) => {
      if (key && Number.isFinite(Number(score))) scores.set(normalize(key), Number(score));
    };
    for (const family of Object.values(analysis?.family_scores || {})) {
      for (const item of family?.indicators || []) {
        const key = String(item?.key || "");
        const score = item?.score;
        if (score == null || !Number.isFinite(Number(score))) continue;
        add(key, score);
        const ma = key.match(/^EMA\/SMA\((\d+)\)$/i);
        if (ma) {
          add(`EMA(${ma[1]})`, score);
          add(`SMA(${ma[1]})`, score);
        }
        if (/^MACD/i.test(key)) add("MACD(26)", score);
        if (/^SO\(14\)/i.test(key)) add("WR(14)", score);
        if (/^SO\(14\)/i.test(key)) add("SO(14)", score);
        if (/^StochRSI\(14\)/i.test(key)) add("StochRSI(14)", score);
        if (/^Ichimoku Cloud/i.test(key)) {
          add("Ichimoku Cloud", score);
          add("Ichimoku(9,26,52,26)", score);
        }
      }
    }
    return scores;
  }

  function lookupIndicatorScore(scoreMap, key) {
    const normalize = (value) => String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const direct = scoreMap.get(normalize(key));
    if (direct != null) return direct;
    const period = String(key || "").match(/^(?:EMA|SMA)\((\d+)\)$/i);
    if (period) return scoreMap.get(normalize(`EMA(${period[1]})`)) ?? scoreMap.get(normalize(`SMA(${period[1]})`));
    return undefined;
  }

  function indicatorAssessment(key, value, modelScore, preferModelScore = false) {
    const signal = value?.signal || "neutral";
    const rawScore = value?.score ?? value?.indicator_score ?? value?.technical_score;
    const explicitScore = preferModelScore ? (modelScore ?? NaN) : (modelScore ?? (rawScore == null ? NaN : Number(rawScore)));
    if (Number.isFinite(explicitScore)) return scoreBandAssessment(explicitScore);
    if (value?.value == null || signal === "unavailable") return { state: "neutral", label: "خنثی" };
    if (key === "ADX(14)") {
      const plus = Number(value.plus_di), minus = Number(value.minus_di);
      if (signal !== "strong") return { state: "neutral", label: "خنثی" };
      if (Number.isFinite(plus) && Number.isFinite(minus) && plus !== minus)
        return plus > minus ? { state: "positive", label: "صعودی" } : { state: "negative", label: "نزولی" };
      return { state: "neutral", label: "خنثی" };
    }
    if (["ATR(14)", "HV(15)", "HV(30)", "HV(90)", "VRSI(14)"].includes(key)) return { state: "neutral", label: "خنثی" };
    if (["buy", "bullish", "strongbuy", "strong_buy", "oversold", "bounce_from_lower", "breakout_up"].includes(String(signal).toLowerCase())) return { state: "positive", label: "صعودی" };
    if (["sell", "bearish", "strongsell", "strong_sell", "overbought", "near_upper_uptrend", "breakout_down"].includes(String(signal).toLowerCase())) return { state: "negative", label: "نزولی" };
    return { state: "neutral", label: "خنثی" };
  }

  function scoreBandAssessment(score) {
    const numericScore = Number(score);
    const label = numericScore >= 70 ? "\u0635\u0639\u0648\u062f\u06cc"
      : numericScore <= 40 ? "\u0646\u0632\u0648\u0644\u06cc" : "\u062e\u0646\u062b\u06cc";
    const state = numericScore >= 70 ? "positive" : numericScore <= 40 ? "negative" : "neutral";
    return { state, label: `${label} · ${num(numericScore, 1)}/100` };
  }

  function indicatorModelNote(key) {
    if (/^WR\(14\)/i.test(key) || /williams/i.test(key)) return "ادغام‌شده در SO(14)";
    if (/^(EMA|SMA)\(200\)$/i.test(key) || /^Trend(?:\b|\s)/i.test(key)) return "صرفاً نمایشی · بدون وزن در مدل";
    return "";
  }

  function indicatorAdjustedNote(key, modelScore, familyScores) {
    if (!Number.isFinite(Number(modelScore))) return "";
    for (const family of Object.values(familyScores || {})) {
      const row = (family?.indicators || []).find((item) => {
        const k = String(item?.key || "");
        return k.toLowerCase() === String(key).toLowerCase()
          || (/^MACD/i.test(key) && /^MACD/i.test(k))
          || (/^SO\(14\)/i.test(key) && /^SO\(14\)/i.test(k));
      });
      if (!row?.regime_adjusted) continue;
      const raw = row.raw_score ?? row.score_before_adjustment;
      return raw == null ? "تعدیل‌شده بر اساس قدرت روند" : `تعدیل روند · امتیاز خام ${num(raw, 1)} ← نهایی ${num(modelScore, 1)}`;
    }
    return "";
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
    if (key === "StochRSI(14)") {
      const raw = Number(value.value);
      return num(raw > 1 ? raw : raw * 100, 1);
    }
    if (/^RV\(/.test(key)) return num(value.value, 2) + "\u00d7";
    if (/^HV\(/.test(key)) return num(value.value, 2) + "%";
    return num(value.value, 3);
  }

  function indicatorPlainMeaning(name) {
    const key = String(name || "").toLowerCase().replace(/[^a-z]/g, "");
    if (key.startsWith("rv")) return "\u0646\u0633\u0628\u062a \u062d\u062c\u0645 \u0622\u062e\u0631\u06cc\u0646 \u06a9\u0646\u062f\u0644 \u0628\u0647 \u0645\u06cc\u0627\u0646\u06af\u06cc\u0646 \u062d\u062c\u0645 \u062f\u0648\u0631\u0647 \u0627\u0633\u062a\u061b \u062c\u0647\u062a \u0631\u0627 \u0628\u0627 \u0633\u0627\u06cc\u0631 \u0634\u0627\u062e\u0635\u200c\u0647\u0627 \u0628\u0633\u0646\u062c.";
    if (key.startsWith("hv")) return "\u0646\u0648\u0633\u0627\u0646 \u062a\u0627\u0631\u06cc\u062e\u06cc \u0633\u0627\u0644\u0627\u0646\u0647\u200c\u0634\u062f\u0647 \u0642\u06cc\u0645\u062a \u0631\u0627 \u0645\u06cc\u200c\u0633\u0646\u062c\u062f\u061b \u0645\u0642\u062f\u0627\u0631 \u0628\u0627\u0644\u0627\u062a\u0631 \u06cc\u0639\u0646\u06cc \u0631\u06cc\u0633\u06a9 \u0646\u0648\u0633\u0627\u0646 \u0628\u06cc\u0634\u062a\u0631.";
    if (key.startsWith("stochrsi")) return "مقیاس ۰ تا ۱۰۰؛ زیر ۳۰ ناحیه خرید، بالای ۶۰ ناحیه فروش و بین آن‌ها خنثی.";
    if (key.startsWith("rsi")) return "در این مدل: ۳۵ و کمتر ناحیه خرید (امتیاز ۷۰ تا ۱۰۰)، بین ۳۵ تا ۶۰ خنثی، و ۶۰ به بالا ناحیه فروش (امتیاز ۴۰ و کمتر) است.";
    if (key.startsWith("mfi")) return "فشار خرید و فروش را با ترکیب تغییر قیمت و حجم معاملات نشان می‌دهد.";
    if (key.startsWith("cci")) return "نشان می‌دهد قیمت چقدر از میانگین معمولش فاصله گرفته و حرکت چقدر قوی شده است.";
    if (key.startsWith("wr") || key.startsWith("williams")) return "جای قیمت را نسبت به سقف و کف اخیر نشان می‌دهد؛ برای سنجش مومنتوم کوتاه‌مدت است.";
    if (key.startsWith("so") || key.startsWith("stoch")) return "جای قیمت را در دامنهٔ اخیر و تغییر مومنتوم را با دو خط K و D نشان می‌دهد.";
    if (key.startsWith("aroon") || key.startsWith("arron")) return "تازگی سقف‌ها و کف‌های اخیر را می‌سنجد تا جهت غالب روند را نشان دهد.";
    if (key.startsWith("adx")) return "قدرت روند را می‌سنجد، نه جهت آن؛ جهت را باید از قیمت یا شاخص‌های +DI و −DI خواند.";
    if (key.startsWith("ao")) return "شتاب کوتاه‌مدت بازار را با شتاب بلندمدت مقایسه می‌کند.";
    if (key.startsWith("vmacd")) return "تغییر شتاب حجم معاملات را نشان می‌دهد؛ جهت قیمت را به‌تنهایی مشخص نمی‌کند.";
    if (key.startsWith("macd")) return "روند و شتاب قیمت را از مقایسهٔ میانگین‌ها می‌سنجد؛ تقاطع خط‌ها تغییر مومنتوم را نشان می‌دهد.";
    if (key.startsWith("mtm") || key.startsWith("momentum")) return "میزان و جهت تغییر قیمت را نسبت به چند دورهٔ قبل نشان می‌دهد.";
    if (key.startsWith("trend")) return "خلاصهٔ جهت روند است: صعودی، نزولی یا خنثی.";
    if (key.startsWith("ichimoku")) return "روند و محدوده‌های احتمالی حمایت و مقاومت را با خطوط و ابر نشان می‌دهد.";
    if (key.startsWith("keltner")) return "کانالی پیرامون میانگین قیمت است که دامنهٔ نوسان و جایگاه قیمت را نشان می‌دهد.";
    if (key.startsWith("bb") || key.startsWith("bollinger")) return "باندهای اطراف میانگین قیمت را نشان می‌دهد؛ باز و بسته‌شدنشان از تغییر نوسان خبر می‌دهد.";
    if (key.startsWith("ema") || key.startsWith("sma")) return "میانگین قیمت در یک بازه است و برای تشخیص جهت روند و حمایت یا مقاومت پویا استفاده می‌شود.";
    if (key.startsWith("pivotpoint") || key.startsWith("pivot")) return "سطوح محاسباتی حمایت و مقاومت احتمالی را برای مقایسه با قیمت نشان می‌دهد.";
    if (key.startsWith("atr")) return "اندازهٔ نوسان قیمت را نشان می‌دهد، نه جهت صعود یا نزول را.";
    if (key.startsWith("rv")) return "حجم امروز را با حجم معمول مقایسه می‌کند تا میزان مشارکت معامله‌گران مشخص شود.";
    if (key.startsWith("vrsi")) return "قدرت و شتاب تغییرات حجم معاملات را به شکل یک نوسان‌گر نشان می‌دهد.";
    if (key.startsWith("obv")) return "حجم را با جهت حرکت قیمت جمع می‌کند تا همراهی یا واگرایی حجم با روند دیده شود.";
    return "بخشی از روند، مومنتوم، حجم یا نوسان را می‌سنجد؛ آن را همراه قیمت و بقیهٔ شاخص‌ها بخوان.";
  }

  function fundModelRecommendationHtml(a) {
    const labels = {
      moving_averages: ["\u0645\u06cc\u0627\u0646\u06af\u06cc\u0646 \u0645\u062a\u062d\u0631\u06a9", "\u062c\u0627\u06cc\u06af\u0627\u0647 \u0642\u06cc\u0645\u062a \u0646\u0633\u0628\u062a \u0628\u0647 \u0645\u06cc\u0627\u0646\u06af\u06cc\u0646\u200c\u0647\u0627 \u0648 \u0628\u0627\u0646\u062f\u0647\u0627"],
      trend_momentum: ["\u0631\u0648\u0646\u062f \u0648 \u0634\u062a\u0627\u0628", "MACD\u060c ADX\u060c AROON \u0648 AO"],
      support_resistance: ["\u062d\u0645\u0627\u06cc\u062a \u0648 \u0645\u0642\u0627\u0648\u0645\u062a", "\u067e\u06cc\u0648\u062a\u200c\u0647\u0627 \u0648 \u0641\u0627\u0635\u0644\u0647\u0654 \u0642\u06cc\u0645\u062a \u062a\u0627 \u0633\u0637\u0648\u062d"],
      oscillators: ["\u0627\u0633\u06cc\u0644\u0627\u062a\u0648\u0631\u0647\u0627", "RSI\u060c MFI\u060c CCI\u060c SO\u060c StochRSI\u060c WR \u0648 MTM"]
    };
    const indicatorLabels = {
      ema50: "EMA(50)", ema20: "EMA(20)", ichimoku: "Ichimoku Cloud",
      ema100: "EMA(100)", bb20: "BB(20)", sma50: "SMA(50)", sma20: "SMA(20)",
      ema200: "EMA(200)", sma200: "SMA(200)", sm15: "SM(15)",
      "Ichimoku Cloud(9,26,52,26)": "Ichimoku Cloud (9, 26, 52, 26)",
      ema10: "EMA(10)", sma100: "SMA(100)", keltner16: "KELTNER(16)", ema30: "EMA(30)",
      sma10: "SMA(10)", sma30: "SMA(30)", ema5: "EMA(5)", sma5: "SMA(5)",
      macd26: "MACD(26)", rsi14: "RSI(14)", mfi14: "MFI(14)", adx14: "ADX(14)",
      stochrsi14: "StochRSI(14)", trend: "Trend", ao534: "AO(5,34)", so14: "SO(14)",
      aroon25: "AROON(25)", cci14: "CCI(14)", mtm6: "MTM(6)", wr14: "WR(14)",
      obv20: "OBV(20)", rv30: "RV(30)", rv90: "RV(90)",
      vmacd26: "VMACD(26)", vrsi14: "VRSI(14)", rv15: "RV(15)",
      fibonacci: "PivotPointFibonacci(30)", classic: "PivotPointClassic(30)",
      camarilla: "PivotPointCamarilla(30)", woodie: "PivotPointWoodie(30)",
      demark: "PivotPointDeMark(30)"
    };
    const bandLabels = {
      very_strong: "بسیار قوی", strong: "قوی", relatively_positive: "نسبتاً مثبت",
      bullish: "صعودی", bearish: "نزولی", neutral: "خنثی", weak: "ضعیف",
      very_weak: "بسیار ضعیف", unavailable: "داده کافی نیست"
    };
    const familyNames = Object.fromEntries(Object.entries(labels).map(([key, [label]]) => [key, label]));
    const riskLabels = { low: "پایین", medium: "متوسط", elevated: "بالا", high: "بسیار بالا" };
    const score = a.technical_score == null ? NaN : Number(a.technical_score);
    const validScore = Number.isFinite(score);
    const tone = !validScore ? "unknown" : a.score_band === "bullish" ? "positive" : a.score_band === "bearish" ? "negative" : "neutral";
    const scoreWeights = a.score_weights || {};
    const horizonName = a.investment_horizon_label || horizonLabel();
    const scoreWeightText = `\u0645\u062f\u0644 ${horizonName} \u00b7 \u0645\u06cc\u0627\u0646\u06af\u06cc\u0646\u200c\u0647\u0627\u06cc \u0645\u062a\u062d\u0631\u06a9 ${num(scoreWeights.moving_averages ?? 0, 0)}\u066a \u00b7 \u0631\u0648\u0646\u062f \u0648 \u0634\u062a\u0627\u0628 ${num(scoreWeights.trend_momentum ?? 0, 0)}\u066a \u00b7 \u062d\u0645\u0627\u06cc\u062a \u0648 \u0645\u0642\u0627\u0648\u0645\u062a ${num(scoreWeights.support_resistance ?? 0, 0)}\u066a \u00b7 \u0627\u0633\u06cc\u0644\u0627\u062a\u0648\u0631\u0647\u0627 ${num(scoreWeights.oscillators ?? 0, 0)}\u066a`;
    const effectiveScoreWeights = a.effective_score_weights || {};
    const familyScores = a.family_scores || {};
    const familyCards = Object.entries(labels).filter(([key]) => {
      const value = familyScores[key]?.score;
      return value != null && Number.isFinite(Number(value));
    }).map(([key, [label, description]]) => {
      const family = familyScores[key] || {};
      const value = family.score == null ? NaN : Number(family.score);
      const available = Number.isFinite(value);
      const coverage = family.coverage_pct == null ? NaN : Number(family.coverage_pct);
      const weight = Number(scoreWeights[key]);
      const effectiveWeight = Number(effectiveScoreWeights[key]);
      const familyTone = !available ? "unavailable" : Math.floor(value + 0.5) >= 70 ? "positive" : Math.floor(value + 0.5) <= 40 ? "negative" : "neutral";
      const validCount = Array.isArray(family.indicators) ? family.indicators.filter((item) => item?.score != null).length : 0;
      const missingCount = Array.isArray(family.missing_indicators) ? family.missing_indicators.length : 0;
      const countText = validCount || missingCount ? `${num(validCount, 0)} شاخص در محاسبه · ${num(missingCount, 0)} ناموجود` : "دادهٔ معتبر در دسترس نیست";
      const extras = [];
      if (key === "support_resistance") {
        if (family.nearest_support != null) extras.push(`حمایت نزدیک: ${money(family.nearest_support)}${family.support_distance_pct != null ? ` · ${num(family.support_distance_pct, 2)}٪ فاصله` : ""}`);
        if (family.nearest_resistance != null) extras.push(`مقاومت نزدیک: ${money(family.nearest_resistance)}${family.resistance_distance_pct != null ? ` · ${num(family.resistance_distance_pct, 2)}٪ فاصله` : ""}`);
      }
      const details = Array.isArray(family.indicators) ? family.indicators : [];
      const detailRows = details.map((item) => {
        const hasScore = item.score != null && Number.isFinite(Number(item.score));
        const itemScore = hasScore ? Number(item.score) : NaN;
        const itemTone = !hasScore ? "unavailable" : Math.floor(itemScore + 0.5) >= 70 ? "positive" : Math.floor(itemScore + 0.5) <= 40 ? "negative" : "neutral";
        const itemName = indicatorLabels[item.key] || indicatorLabels[item.name] || item.name || item.key || "شاخص";
        const raw = item.value == null ? "" : typeof item.value === "object"
          ? Object.entries(item.value).filter(([, value]) => value != null && Number.isFinite(Number(value))).map(([key, value]) => `${key} ${num(value, 1)}`).join(" · ")
          : Number.isFinite(Number(item.value)) ? `مقدار ${num(item.value, 1)}` : "";
        return `<div class="dashboard-score-detail-row ${itemTone}" title="${esc(item.note || "")}"><span>${esc(itemName)} <small>وزن در گروه ${num(item.weight_pct, 1)}٪${raw ? ` · ${esc(raw)}` : ""}</small></span><b>${hasScore ? num(itemScore, 0) : "—"}</b></div>`;
      }).join("");
      return `<article class="fund-family-score-card ${familyTone}">
        <div class="fund-family-score-head"><span>${label}</span><b>وزن ${num(weight, 0)}٪${Number.isFinite(effectiveWeight) && Math.abs(effectiveWeight - weight) >= 0.1 ? ` · مؤثر ${num(effectiveWeight, 1)}٪` : ""}</b></div>
        <strong>${available ? `${num(value, 0)} از ۱۰۰` : "—"}</strong>
        <small>${description}</small>
        ${extras.length ? `<div class="fund-family-extra">${extras.map((item) => `<span>${item}</span>`).join("")}</div>` : ""}
        <div class="fund-family-coverage"><span>پوشش ${Number.isFinite(coverage) ? `${num(coverage, 0)}٪` : "—"}</span><span>${countText}</span></div>
        <details class="dashboard-score-details"><summary>جزئیات وزن و امتیاز شاخص‌ها (${details.length})</summary><div>${detailRows}</div></details>
        <i style="width:${available ? Math.max(0, Math.min(100, value)) : 0}%"></i>
      </article>`;
    }).join("");
    const risk = a.risk_rank || {};
    const riskScore = risk.score == null ? NaN : Number(risk.score);
    const coverage = a.data_coverage_pct == null ? NaN : Number(a.data_coverage_pct);
    const familyWeight = a.available_family_weight_pct == null ? NaN : Number(a.available_family_weight_pct);
    const confidence = a.confidence == null ? NaN : Number(a.confidence);
    const damping = a.damping_factor == null ? NaN : Number(a.damping_factor) * 100;
    const nav = a.nav_assessment || {};
    const navText = nav.premium_pct != null && Number.isFinite(Number(nav.premium_pct))
      ? `حباب/تخفیف بازار نسبت به NAV: ${num(nav.premium_pct, 2)}٪`
      : "مقایسه با NAV تازه در این محاسبه موجود نیست";
    const factors = a.top_factors || {};
    const positiveFactor = factors.positive;
    const negativeFactor = factors.negative;
    const factorSummary = `<div class="fund-model-factors"><span class="positive">نقطه قوت: ${positiveFactor ? `${familyNames[positiveFactor.family] || "عامل تکنیکال"} · ${num(positiveFactor.score, 0)}/100` : "عامل مثبت برجسته‌ای از داده‌های موجود به دست نیامد"}</span><span class="negative">نیازمند توجه: ${negativeFactor ? `${familyNames[negativeFactor.family] || "عامل تکنیکال"} · ${num(negativeFactor.score, 0)}/100` : "عامل منفی برجسته‌ای از داده‌های موجود به دست نیامد"}</span></div>`;
return `<section class="fund-recommendation ${tone} fund-model-recommendation">
      <div class="fund-model-score-head">
        <div><span class="recommendation-kicker">مدل ${horizonName} AliVest · محاسبه بر پایه داده‌های ره‌آورد</span>
          <h3>امتیاز تکنیکال ${a.dashboard_asset ? "دارایی" : "صندوق"}: <strong>${validScore ? `${num(score, 0)} از ۱۰۰` : "داده کافی نیست"}</strong></h3>
          <p>${scoreWeightText}. ارزیابی مدل: <b>${bandLabels[a.score_band] || "نامشخص"}</b> · امتیاز اندیکاتورها طبق منحنی‌های آپدیت ۴.۲ محاسبه می‌شود؛ در روند قوی، اثر سیگنال خلاف روندِ اسیلاتورها و باندها نصف می‌شود. ورود همچنان با امتیاز میانگین‌ها و امتیاز کل سنجیده می‌شود؛ ADX قدرت روند را می‌سنجد و جهتش از DI یا میانگین‌ها می‌آید.</p>
        </div>
        <div class="fund-model-meta">
          <span>پوشش کل داده‌ها <b>${Number.isFinite(coverage) ? `${num(coverage, 0)}٪` : "—"}</b></span>
          <span title="درصد وزن پایه‌ای که دادهٔ قابل‌محاسبه دارد؛ وزن مؤثر گروه‌های باقی‌مانده جداگانه نشان داده می‌شود">پوشش وزن پایهٔ گروه‌ها <b>${Number.isFinite(familyWeight) ? `${num(familyWeight, 0)}٪` : "—"}</b></span>
          <span title="بر پایهٔ پوشش داده و هم‌سویی گروه‌ها؛ احتمال سود نیست">اعتماد سیگنال <b>${Number.isFinite(confidence) ? `${num(confidence, 1)}٪` : "—"}</b></span>
          <span title="تصمیم بر پایهٔ امتیاز نهایی، پوشش داده و هم‌جهتی اندیکاتورها">تصمیم مدل <b>${esc(a.decision_label || "نامشخص")}</b></span>
          <span title="سهم وزنی اندیکاتورهای جهت‌دار که با امتیاز نهایی هم‌جهت هستند">هم‌جهتی <b>${Number.isFinite(Number(a.confluence_pct)) ? `${num(a.confluence_pct, 1)}٪` : "—"}</b></span>
          <span title="نمایش فاصلهٔ امتیاز گروه‌ها از یکدیگر">پراکندگی گروه‌ها <b>${Number.isFinite(a.inter_group_dispersion) ? num(a.inter_group_dispersion, 1) : "—"}</b></span>
          <span>ریسک نوسان (بالاتر = ریسک بیشتر) <b>${riskLabels[risk.level] || "نامشخص"}${Number.isFinite(riskScore) ? ` · ${num(riskScore, 0)}/100` : ""}</b></span>
        </div>
      </div>
      <div class="fund-family-score-grid">${familyCards}</div>
      ${factorSummary}
      <div class="fund-model-context"><span>${navText}</span></div>
    </section>`;
  }

  function dashboardModelRecommendationHtml(a) {
    const finite = (value) => value != null && Number.isFinite(Number(value));
    const scoreValue = finite(a.technical_score) ? Number(a.technical_score) : null;
    const scoreTone = scoreValue == null ? "unknown" : a.score_band === "bullish" ? "positive" : a.score_band === "bearish" ? "negative" : "neutral";
    const weights = a.score_weights || {};
    const horizonName = a.investment_horizon_label || horizonLabel();
    const effectiveWeights = a.effective_score_weights || {};
    const scores = a.family_scores || {};
    const trendLabels = { bullish: "صعودی", bearish: "نزولی", neutral: "خنثی", unavailable: "داده کافی نیست" };
    const strengthLabels = { strong: "قوی", medium: "متوسط", weak: "ضعیف", unavailable: "نامشخص" };
    const riskLabels = { low: "کم", medium: "متوسط", elevated: "نسبتاً بالا", high: "بالا", very_high: "بسیار بالا", unavailable: "نامشخص" };
    const entryLabels = { suitable: "مناسب", confirmation: "نیازمند تأیید", unsuitable: "نامناسب", unavailable: "داده کافی نیست" };
    const bandLabels = { bullish: "صعودی", bearish: "نزولی", neutral: "خنثی", unavailable: "داده کافی نیست", very_strong: "بسیار قوی", strong: "قوی", relatively_positive: "نسبتاً مثبت", weak: "نسبتاً منفی", very_weak: "بسیار ضعیف" };
    const trend = trendLabels[a.score_band || a.trend || a.medium_term_trend] || "داده کافی نیست";
    const strength = strengthLabels[a.trend_strength] || "نامشخص";
    const risk = riskLabels[a.risk] || "نامشخص";
    const entry = a.entry_quality?.label || entryLabels[a.entry_quality?.status] || "داده کافی نیست";
    const entryReason = [a.entry_quality?.score_method, a.entry_quality?.reason].filter(Boolean).join(" · ");
    const scoreWeightText = "مدل " + horizonName + " · میانگین متحرک " + num(weights.moving_averages ?? 0, 0) + "٪ · روند و شتاب " + num(weights.trend_momentum ?? 0, 0) + "٪ · حمایت و مقاومت " + num(weights.support_resistance ?? 0, 0) + "٪ · نوسان‌گرها " + num(weights.oscillators ?? 0, 0) + "٪";
    const familyDefinitions = [
      { key: "moving_averages", label: "\u0645\u06cc\u0627\u0646\u06af\u06cc\u0646\u200c\u0647\u0627\u06cc \u0645\u062a\u062d\u0631\u06a9", description: "EMA\u060c SMA\u060c \u0627\u06cc\u0686\u06cc\u0645\u0648\u06a9\u0648 \u0648 \u0628\u0627\u0646\u062f\u0647\u0627" },
      { key: "trend_momentum", label: "\u0631\u0648\u0646\u062f \u0648 \u0634\u062a\u0627\u0628", description: "MACD\u060c ADX\u060c AROON \u0648 AO" },
      { key: "support_resistance", label: "\u062d\u0645\u0627\u06cc\u062a \u0648 \u0645\u0642\u0627\u0648\u0645\u062a", description: "\u067e\u06cc\u0648\u062a\u200c\u0647\u0627\u06cc \u0641\u06cc\u0628\u0648\u0646\u0627\u0686\u06cc\u060c \u06a9\u0644\u0627\u0633\u06cc\u06a9\u060c \u06a9\u0627\u0645\u0627\u0631\u06cc\u0644\u0627\u060c \u0648\u0648\u062f\u06cc \u0648 \u062f\u06cc\u200c\u0645\u0627\u0631\u06a9" },
      { key: "oscillators", label: "\u0627\u0633\u06cc\u0644\u0627\u062a\u0648\u0631\u0647\u0627", description: "RSI\u060c MFI\u060c CCI\u060c SO (%K\u061b WR \u0627\u062f\u063a\u0627\u0645 \u0634\u062f\u0647)\u060c StochRSI \u0648 MTM" },
    ];
    const familyCards = familyDefinitions.filter((factor) => finite(scores[factor.key]?.score)).map((factor) => {
      const family = scores[factor.key] || {};
      const value = finite(family.score) ? Number(family.score) : null;
      const weight = finite(weights[factor.key]) ? Number(weights[factor.key]) : 0;
      const tone = value == null ? "unavailable" : Math.floor(value + 0.5) >= 70 ? "positive" : Math.floor(value + 0.5) <= 40 ? "negative" : "neutral";
      const coverage = finite(family.coverage_pct) ? num(family.coverage_pct, 0) + "٪" : "—";
      const details = Array.isArray(family.indicators) ? family.indicators : [];
      const detailRows = details.map((item) => {
        const hasScore = finite(item.score);
        const itemTone = !hasScore ? "unavailable" : Math.floor(Number(item.score) + 0.5) >= 70 ? "positive" : Math.floor(Number(item.score) + 0.5) <= 40 ? "negative" : "neutral";
        const raw = item.value == null ? "" : typeof item.value === "object"
          ? Object.entries(item.value).filter(([, value]) => value != null && finite(value)).map(([key, value]) => key + " " + num(value, 1)).join(" · ")
          : finite(item.value) ? "مقدار " + num(item.value, 1) : "";
        return "<div class=\"dashboard-score-detail-row " + itemTone + "\" title=\"" + esc(item.note || "") + "\"><span>" + esc(item.name || item.key || "شاخص") + " <small>وزن در گروه " + num(item.weight_pct, 1) + "٪" + (raw ? " · " + esc(raw) : "") + "</small></span><b>" + (hasScore ? num(item.score, 0) : "—") + "</b></div>";
      }).join("");
      const missing = Array.isArray(family.missing_indicators) ? family.missing_indicators.length : 0;
      const effective = finite(effectiveWeights[factor.key]) ? " · وزن مؤثر " + num(effectiveWeights[factor.key], 1) + "٪" : "";
      return "<article class=\"fund-family-score-card " + tone + "\">" +
        "<div class=\"fund-family-score-head\"><span>" + factor.label + "</span><b>وزن کل " + num(weight, 0) + "٪</b></div>" +
        "<strong>" + (value == null ? "—" : num(value, 0) + " از ۱۰۰") + "</strong>" +
        "<small>" + factor.description + "</small>" +
        "<div class=\"fund-family-coverage\"><span>پوشش " + coverage + "</span><span>" + (missing ? missing + " شاخص بی‌داده" : "همه شاخص‌ها محاسبه شد") + effective + "</span></div>" +
        "<details class=\"dashboard-score-details\"><summary>جزئیات وزن و امتیاز اندیکاتورها (" + details.length + ")</summary><div>" + detailRows + "</div></details>" +
        "<i style=\"width:" + (value == null ? 0 : Math.max(0, Math.min(100, value))) + "%\"></i></article>";
    }).join("");
    const unitLabels = { GOLD: "دلار / اونس", USD_IR_FREE: "تومان", TEPIX: "واحد", GOLD_18K: "ریال / گرم" };
    const price = finite(a.price) ? money(a.price) + " " + (unitLabels[a.symbol] || "") : "قیمت در دسترس نیست";
    const daily = finite(a.daily_return_pct) ? (Number(a.daily_return_pct) > 0 ? "+" : "") + num(a.daily_return_pct, 2) + "٪" : "تغییر روزانه موجود نیست";
    const levelText = (label, level, distance) => finite(level)
      ? "<span>" + label + " <b>" + money(level) + "</b>" + (finite(distance) ? " · " + num(distance, 2) + "٪ فاصله" : "") + "</span>"
      : "<span>" + label + " <b>در داده موجود نیست</b></span>";
    const evidenceText = (rows, fallback) => Array.isArray(rows) && rows.length
      ? rows.map((item) => "<span><b>" + esc(item.name || item.family) + "</b> · " + num(item.score, 0) + "/۱۰۰</span>").join("")
      : "<span>" + fallback + "</span>";
    const limitations = Array.isArray(a.data_limitations) ? a.data_limitations : [];
    return "<section class=\"fund-recommendation " + scoreTone + " fund-model-recommendation dashboard-model-recommendation\">" +
      "<div class=\"fund-model-score-head\"><div><span class=\"recommendation-kicker\">مدل " + horizonName + " · امتیاز اختصاصی AliVest بر پایهٔ داده‌های ره‌آورد</span>" +
      "<h3>امتیاز تکنیکال: <strong>" + (scoreValue == null ? "داده کافی نیست" : num(scoreValue, 0) + " از ۱۰۰") + "</strong> · " + (bandLabels[a.score_band] || "نامشخص") + "</h3>" +
      "<p>" + scoreWeightText + " · امتیاز اندیکاتورها طبق منحنی‌های آپدیت ۴.۲ محاسبه می‌شود؛ در روند قوی، اثر سیگنال خلاف روندِ اسیلاتورها و باندها نصف می‌شود. ورود با امتیاز میانگین‌ها و امتیاز کل سنجیده می‌شود؛ ADX قدرت روند را می‌سنجد و جهتش از DI یا میانگین‌ها می‌آید.</p></div>" +
      "<div class=\"fund-model-meta\"><span>قیمت فعلی <b>" + price + "</b></span><span>تغییر روزانه <b>" + daily + "</b></span>" +
      "<span>جمع‌بندی " + horizonName + " <b>" + trend + "</b></span><span>قدرت حرکت (ADX) <b>" + strength + "</b></span>" +
      "<span>ریسک نوسان <b>" + risk + (finite(a.risk_score) ? " · " + num(a.risk_score, 0) : "") + "</b></span>" +
      "<span title=\"" + esc(entryReason) + "\">ارزیابی خرید <b>" + entry + (finite(a.entry_quality?.score) ? " · کیفیت ورود " + num(a.entry_quality.score, 0) : "") + "</b></span>" +
      "<span title=\"درصد وزن پایه‌ای که دادهٔ قابل‌محاسبه دارد؛ وزن مؤثر گروه‌های باقی‌مانده جداگانه نشان داده می‌شود\">پوشش وزن پایهٔ گروه‌ها <b>" + (finite(a.available_family_weight_pct) ? num(a.available_family_weight_pct, 0) + "٪" : "—") + "</b></span>" +
      "<span title=\"بر پایهٔ پوشش داده و هم‌سویی گروه‌ها؛ احتمال سود نیست\">اعتماد سیگنال <b>" + (finite(a.confidence) ? num(a.confidence, 1) + "٪" : "—") + "</b></span>" +
      "<span title=\"فاصلهٔ امتیاز گروه‌ها از یکدیگر\">پراکندگی گروه‌ها <b>" + (finite(a.inter_group_dispersion) ? num(a.inter_group_dispersion, 1) : "—") + "</b></span>" +
      "<span>به‌روزرسانی <b>" + esc(formatDate(a.data_timestamp)) + "</b></span></div></div>" +
      "<div class=\"fund-family-score-grid\">" + familyCards + "</div>" +
      "<div class=\"fund-model-factors\"><div class=\"positive\"><b>شواهد مثبت</b>" + evidenceText(a.positive_evidence, "عامل مثبت برجسته‌ای از داده‌های موجود به دست نیامد.") + "</div>" +
      "<div class=\"negative\"><b>نیازمند توجه</b>" + evidenceText(a.negative_evidence, "عامل منفی برجسته‌ای از داده‌های موجود به دست نیامد.") + "</div></div>" +
      "<div class=\"fund-model-context dashboard-levels\">" + levelText("حمایت نزدیک", a.nearest_support?.midpoint, a.score_breakdown?.support_distance_pct) +
      levelText("مقاومت پیش‌رو", a.nearest_resistance?.midpoint, a.score_breakdown?.resistance_distance_pct) +
      levelText("سطح ساختاری", a.structural_invalidation_level, null) + "</div>" +
      "<div class=\"fund-model-disclaimer\"><b>روش و محدودیت محاسبه</b><span>امتیاز کل از گروه‌های میانگین‌های متحرک، روند و شتاب، حمایت و مقاومت و اسیلاتورها به‌دست می‌آید. اندیکاتورهای بدون مقدار نمایش داده نمی‌شوند و وزنشان در همان گروه بین اندیکاتورهای موجود تقسیم می‌شود؛ اگر یک گروه کامل داده نداشته باشد، وزن آن بین گروه‌های قابل‌محاسبه بازتوزیع می‌شود. اندیکاتورهای مستقل حجم و کارت حجم حذف شده‌اند؛ MFI طبق اکسل در گروه اسیلاتورها باقی است. " +
      limitations.map(esc).join(" ") + "</span></div></section>";
  }


  function rahavardRecommendationHtml(a) {
    if (a?.dashboard_asset && a.family_scores) {
      return fundModelRecommendationHtml(a);
    }
    if (a?.score_method?.startsWith("dashboard_rahavard_excel_weighted_")) {
      return dashboardModelRecommendationHtml(a);
    }
    if ((a?.score_method?.startsWith("fund_rahavard_excel_weighted_") || a?.score_method?.startsWith("fund_tsetmc_excel_weighted_")) && a.family_scores) {
      return fundModelRecommendationHtml(a);
    }
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
    const modelSignal = String(a.signal || "").trim().toLowerCase().replace(/[^a-z]/g, "");
    const modelDirection = ["buy", "strongbuy"].includes(modelSignal) ? 1
      : ["sell", "strongsell"].includes(modelSignal) ? -1
        : ["hold", "neutral"].includes(modelSignal) ? 0 : null;
    const direction = Number.isFinite(signalValue)
      ? Math.sign(signalValue)
      : buy != null && sell != null ? Math.sign(buy - sell) : modelDirection;
    const verdict = direction == null ? "اطلاعات کافی نیست" : direction > 0 ? "خرید" : direction < 0 ? "فروش" : "صبر / خنثی";
    const tone = direction == null ? "unknown" : direction > 0 ? "positive" : direction < 0 ? "negative" : "neutral";
    const trendItem = Object.values(a.indicators || {}).flatMap((items) => Array.isArray(items) ? items : [])
      .find((item) => String(item?.short_name_en || item?.name_en || "").trim().toLowerCase() === "trend");
    const trendSignal = String(trendItem?.signal || "").trim().toLowerCase().replace(/[^a-z]/g, "");
    const fallbackTrend = String(a.medium_term_trend || "").trim().toLowerCase();
    const trendDirection = ["buy", "bullish", "strongbuy"].includes(trendSignal) ? 1
      : ["sell", "bearish", "strongsell"].includes(trendSignal) ? -1
        : ["neutral", "hold"].includes(trendSignal) ? 0
          : fallbackTrend === "bullish" ? 1 : fallbackTrend === "bearish" ? -1 : fallbackTrend === "neutral" ? 0 : null;
    const trendLabel = trendDirection == null ? "نامشخص" : trendDirection > 0 ? "صعودی" : trendDirection < 0 ? "نزولی" : "خنثی";
    const trendTone = trendDirection == null ? "unknown" : trendDirection > 0 ? "positive" : trendDirection < 0 ? "negative" : "neutral";
    const scores = a.score_breakdown || {};
    const groupScore = (groupName) => {
      const items = (Array.isArray(a.indicators?.[groupName]) ? a.indicators[groupName] : []).filter(hasIndicatorValue);
      const values = items.map((item) => {
        const key = String(item?.signal || "").trim().toLowerCase().replace(/[^a-z]/g, "");
        if (["buy", "strongbuy", "bullish", "support"].includes(key)) return 100;
        if (["sell", "strongsell", "bearish", "resistance"].includes(key)) return 0;
        if (key === "overbought") return 30;
        if (key === "oversold") return 70;
        return ["neutral", "hold", "highvolume", "lowvolume"].includes(key) ? 50 : null;
      }).filter((value) => value != null);
      return values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length) : null;
    };
    const scoreOf = (key, fallback) => scores[key] != null && Number.isFinite(Number(scores[key])) ? Number(scores[key]) : fallback;
    const oscillatorScore = scoreOf("oscillators", groupScore("oscillators"));
    const rsiValue = scores.rsi == null || !Number.isFinite(Number(scores.rsi)) ? null : Number(scores.rsi);
    const oscillatorDetail = rsiValue == null ? "مومنتوم و اشباع" : rsiValue > 70 ? "RSI " + num(rsiValue, 1) + " · ناحیه فروش" : rsiValue < 30 ? "RSI " + num(rsiValue, 1) + " · ناحیه خرید" : "مومنتوم و اشباع";
    const movingAverageScore = scoreOf("moving_averages", groupScore("moving_averages"));
    const trendMomentumScore = scoreOf("trend_momentum", groupScore("trend_momentum"));
    const price = Number(a.price);
    const resistanceLevels = (Array.isArray(a.resistance_levels) ? a.resistance_levels : []).map(Number).filter((value) => Number.isFinite(value) && value > price);
    const nearResistanceCount = Number.isFinite(Number(scores.near_resistance_count)) ? Number(scores.near_resistance_count) : resistanceLevels.filter((value) => (value - price) / price <= .1).length;
    const resistanceScore = scoreOf("resistance", price > 0 ? Math.max(15, 100 - nearResistanceCount * 22) : null);
    const probabilities = a.trend_probabilities || {};
    const bullishProbability = Number.isFinite(Number(probabilities.bullish)) ? Number(probabilities.bullish) : Number(a.scenarios?.find?.((item) => item.direction === "bullish")?.probability ?? 0);
    const bearishProbability = Number.isFinite(Number(probabilities.bearish)) ? Number(probabilities.bearish) : 100 - bullishProbability;
    const correction = a.correction_risk || {};
    const correctionProbability = Number.isFinite(Number(correction.probability)) ? Number(correction.probability) : Math.round(bearishProbability * .65);
    const correctionLabel = correction.label || (correctionProbability >= 55 ? "بالا" : correctionProbability >= 30 ? "متوسط" : "پایین");
    const rationale = direction > 0 ? `سیگنال کلی ${verdict} است و ادامهٔ روند صعودی ${num(bullishProbability, 0)}٪ برآورد شده است.`
      : direction < 0 ? `سیگنال کلی ${verdict} است و احتمال ادامهٔ روند نزولی ${num(bearishProbability, 0)}٪ برآورد شده است.`
        : "سیگنال‌ها هم‌جهت نیستند؛ برای ورود، تثبیت قیمت و کاهش ریسک اصلاح را بررسی کن.";
    const scoreWeights = a.score_weights || {};
    const scoreWeightText = `مدل ${horizonLabel()} · میانگین متحرک ${num(scoreWeights.moving_averages ?? 0, 0)}٪ · روند و شتاب ${num(scoreWeights.trend_momentum ?? 0, 0)}٪ · حمایت و مقاومت ${num(scoreWeights.support_resistance ?? 0, 0)}٪ · اسیلاتورها ${num(scoreWeights.oscillators ?? 0, 0)}٪`;
    const scoreCard = (label, value, detail, tone = "neutral") => value == null ? "" : `<article class="analysis-score-card ${tone}"><span>${label}</span><strong>${num(value, 0)}٪</strong><small>${detail}</small><i style="width:${Math.max(0, Math.min(100, value))}%"></i></article>`;
    const stats = countsAvailable ? `<div class="recommendation-stats">${buy != null ? `<span class="recommendation-count buy">خرید <b>${num(buy, 0)}</b></span>` : ""}${neutral != null ? `<span class="recommendation-count neutral">خنثی <b>${num(neutral, 0)}</b></span>` : ""}${sell != null ? `<span class="recommendation-count sell">فروش <b>${num(sell, 0)}</b></span>` : ""}</div>` : "";
    return `<section class="fund-recommendation ${tone}"><div class="fund-recommendation-main"><div><span class="recommendation-kicker">${a.source === "Rahavard365" ? "شاخص‌های ره‌آورد · امتیاز مدل AliVest" : `مدل ${horizonLabel()} AliVest`} · ${esc(a.symbol || "این دارایی")}</span><h3>${a.source === "Rahavard365" ? "سیگنال ره‌آورد" : "برآورد مدل AliVest"}: <strong>${verdict}</strong></h3></div><div class="recommendation-context"><p>${esc(rationale)}</p><div class="recommendation-trend ${trendTone}"><span>روند فعلی</span><b>${trendLabel}</b></div></div></div><div class="analysis-score-grid"><div class="analysis-score-card primary ${tone}"><span>امتیاز کلی تکنیکال</span><strong>${a.technical_score == null ? "—" : `${num(a.technical_score, 0)}٪`}</strong><small>${scoreWeightText}</small><i style="width:${a.technical_score == null ? 0 : Math.max(0, Math.min(100, Number(a.technical_score)))}%"></i></div>${scoreCard("میانگین‌های متحرک", movingAverageScore, "جایگاه قیمت نسبت به EMA / SMA", Math.floor(movingAverageScore + 0.5) >= 70 ? "positive" : Math.floor(movingAverageScore + 0.5) <= 40 ? "negative" : "neutral")}${scoreCard("روند و شتاب", trendMomentumScore, "MACD · ADX · AROON · AO", Math.floor(trendMomentumScore + 0.5) >= 70 ? "positive" : Math.floor(trendMomentumScore + 0.5) <= 40 ? "negative" : "neutral")}${scoreCard("نوسان‌گرها", oscillatorScore, oscillatorDetail, Math.floor(oscillatorScore + 0.5) >= 70 ? "positive" : Math.floor(oscillatorScore + 0.5) <= 40 ? "negative" : "neutral")}${scoreCard("حمایت و مقاومت", resistanceScore, `${num(nearResistanceCount, 0)} سطح نزدیک · ${num(Number(scores.front_resistance_count ?? resistanceLevels.length), 0)} سطح جلو`, resistanceScore != null && Math.floor(resistanceScore + 0.5) <= 40 ? "negative" : "neutral")}</div><div class="analysis-probability-grid"><article class="analysis-probability bullish"><div><span>ادامهٔ روند صعودی</span><strong>${num(bullishProbability, 0)}٪</strong></div><i style="width:${Math.max(0, Math.min(100, bullishProbability))}%"></i></article><article class="analysis-probability bearish"><div><span>ادامهٔ روند نزولی</span><strong>${num(bearishProbability, 0)}٪</strong></div><i style="width:${Math.max(0, Math.min(100, bearishProbability))}%"></i></article><article class="analysis-probability correction"><div><span>ریسک اصلاح</span><strong>${num(correctionProbability, 0)}٪</strong></div><small>سطح ریسک: ${esc(correctionLabel)}</small><i style="width:${Math.max(0, Math.min(100, correctionProbability))}%"></i></article></div>${stats}</section>`;
  }

  function scenarioHtml(a) {
    const scenarios = Array.isArray(a?.scenarios) ? a.scenarios : [];
    if (!scenarios.length) return "";
    const levelNumber = (raw) => {
      if (typeof raw === "number" && Number.isFinite(raw)) return raw;
      if (!raw || typeof raw !== "object") return null;
      for (const key of ["midpoint", "price", "value", "level"]) {
        const value = Number(raw[key]);
        if (Number.isFinite(value)) return value;
      }
      const low = Number(raw.low), high = Number(raw.high);
      return Number.isFinite(low) && Number.isFinite(high) ? (low + high) / 2 : null;
    };
    const levelText = (raw) => {
      if (raw && typeof raw === "object") {
        const low = Number(raw.low), high = Number(raw.high);
        if (Number.isFinite(low) && Number.isFinite(high) && Math.abs(high - low) > 0.5) return `${money(low)} تا ${money(high)}`;
      }
      const value = levelNumber(raw);
      return value == null ? "" : money(value);
    };
    const nearestLevel = (levels, kind, current) => {
      const rows = (Array.isArray(levels) ? levels : []).filter((level) => levelNumber(level) != null);
      const relevant = rows.filter((level) => current == null || (kind === "support" ? levelNumber(level) < current : levelNumber(level) > current));
      const candidates = relevant.length ? relevant : rows;
      candidates.sort((left, right) => kind === "support"
        ? levelNumber(right) - levelNumber(left)
        : levelNumber(left) - levelNumber(right));
      return candidates[0] || null;
    };
    const parsedPrice = a?.price == null ? NaN : Number(a.price);
    const price = Number.isFinite(parsedPrice) && parsedPrice > 0 ? parsedPrice : null;
    const cards = scenarios.map((scenario) => {
      const direction = scenario.direction === "bullish" ? "bullish" : "bearish";
      const probability = Math.max(0, Math.min(100, Number(scenario.probability) || 0));
      const reasons = String(scenario.reason || "دلیل مشخصی ثبت نشده است.").split(/[؛;\n]+/).map((part) => part.trim()).filter(Boolean);
      const condition = String(scenario.condition || "شرط تأیید در داده‌ها مشخص نشده است.").trim();
      const risk = String(scenario.risk || "ریسک و شرط ابطال مشخص نشده است.").trim();
      const support = scenario.support ?? nearestLevel(a?.support_levels, "support", Number.isFinite(price) ? price : null);
      const resistance = scenario.resistance ?? nearestLevel(a?.resistance_levels, "resistance", Number.isFinite(price) ? price : null);
      const levels = [
        ["حمایت نزدیک", levelText(support), "support"],
        ["مقاومت نزدیک", levelText(resistance), "resistance"],
      ].filter(([, value]) => value);
      return `<article class="scenario-card ${direction}">
        <div class="scenario-card-head"><div><span class="scenario-kicker">برآورد تحلیلی</span><h4>${esc(scenario.name)}</h4></div><div class="scenario-probability"><strong>${num(probability, 0)}٪</strong><small>احتمال برآوردی</small></div></div>
        <div class="scenario-bar" role="img" aria-label="احتمال برآوردی ${num(probability, 0)} درصد"><i style="width:${probability}%"></i></div>
        <div class="scenario-trigger"><span class="scenario-detail-label">شرط تأیید این سناریو</span><p>${esc(condition)}</p></div>
        ${levels.length ? `<div class="scenario-levels">${levels.map(([label, value, kind]) => `<div class="scenario-level ${kind}"><span>${label}</span><b>${value}</b></div>`).join("")}</div>` : ""}
        <div class="scenario-evidence"><h5>دلایل و شواهد</h5><ul>${reasons.map((reason) => `<li>${esc(reason)}</li>`).join("")}</ul></div>
        <div class="scenario-risk"><span class="scenario-detail-label">ریسک و شرط بی‌اعتبارشدن</span><p>${esc(risk)}</p></div>
      </article>`;
    }).join("");
    const note = a?.scenario_note || "احتمال‌ها برآورد تحلیلی‌اند و قطعیت یا تضمین وقوع ندارند.";
    return `<section class="scenario-section"><div class="scenario-section-head"><div><span class="panel-kicker">بررسی چندوجهی بازار</span><h3>سناریوهای پیش‌رو</h3></div><span class="scenario-note">احتمال، شواهد، سطوح و شرط تغییر مسیر</span></div><div class="scenario-grid">${cards}</div><p class="scenario-disclaimer"><span>i</span>${esc(note)}</p></section>`;
  }

  function exitManagementHtml(a) {
    const shortExit = Number(a?.short_term_exit_price) > 0 ? Number(a.short_term_exit_price) : null;
    const mediumExit = Number(a?.medium_term_exit_price) > 0 ? Number(a.medium_term_exit_price) : null;
    const symbol = String(a?.symbol || "").toUpperCase();
    const unit = ({ GOLD: "دلار / اونس", GOLD_18K: "ریال / گرم", USD_IR_FREE: "تومان", TEPIX: "واحد" })[symbol] || "ریال";
    const current = Number(a?.price);
    const currentBadge = Number.isFinite(current) && current > 0 ? `<span class="trade-plan-badge">قیمت مبنا: ${money(current)} ${unit}</span>` : "";
    if (shortExit == null && mediumExit == null) {
      return `<div class="risk-exit-panel unavailable"><b>میانگین EMA(10) و SMA(30) در دادهٔ فعلی موجود نیست</b><small>سطح خروج معتبر پس از دریافت دادهٔ روزانه نمایش داده می‌شود.</small></div>`;
    }
    const exitCard = (kind, label, average, level) => {
      const hasCurrent = Number.isFinite(current) && current > 0;
      const broken = hasCurrent && level != null && current < level;
      const distancePct = hasCurrent && level > 0 ? Math.abs((current - level) / level) * 100 : null;
      const stateText = level == null ? `مقدار ${average} در دادهٔ فعلی موجود نیست.`
          : !hasCurrent ? "برای مقایسه، قیمت فعلی در دسترس نیست."
            : broken ? "حد ضرر شکسته شده (خروج فعال) · قیمت فعلی زیر سطح است؛ مبنای تأیید نهایی کندل روزانه است."
              : `فاصله تا حد ضرر: ${pct(distancePct)} · فعال‌شدن با بسته‌شدن کندل روزانه زیر ${average}`;
      const stateClass = level == null || !hasCurrent ? "unknown" : broken ? "broken" : "safe";
      const stateLabel = level == null ? "داده موجود نیست" : !hasCurrent ? "وضعیت نامشخص" : broken ? "حد ضرر شکسته شده (خروج فعال)" : "حد ضرر فعال نشده";
      return `<article class="risk-exit-card ${kind} ${stateClass}"><span>${label} · ${average}</span><b>${level == null ? "—" : `${money(level)} ${unit}`}</b><small>${stateText}</small><strong class="risk-exit-state ${stateClass}">${stateLabel}</strong></article>`;
    };
    const anyBroken = (current > 0 && shortExit != null && current < shortExit)
      || (current > 0 && mediumExit != null && current < mediumExit);
    const panelState = !Number.isFinite(current) || current <= 0 ? "unavailable" : anyBroken ? "broken" : "safe";
    return `<div class="risk-exit-panel ${panelState}"><div class="risk-exit-head"><div><span class="panel-kicker">قاعدهٔ خروج</span><h4>خروج از موقعیت و حد ضرر</h4><p>وضعیت حد ضرر (مبنای کندل روزانه)</p></div>${currentBadge}</div><div class="risk-exit-grid">${exitCard("short", "کوتاه‌مدت", "EMA(10)", shortExit)}${exitCard("medium", "میان‌مدت", "SMA(30)", mediumExit)}</div></div>`;
  }

  function tradePlanHtml(a) {
    const price = Number(a?.price ?? a?.indicators?.latest);
    if (!Number.isFinite(price) || price <= 0) return "";
    const priceBadge = a?.price_is_cached ? "آخرین قیمت پایانی" : "قیمت فعلی";
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
    const buffer = Math.max(price * .003, Number.isFinite(atr) && atr > 0 ? atr * .15 : price * step * .2);
    const support1 = below[0] ?? price * (1 - step * .45);
    const support2 = below[1] ?? Math.min(support1 * (1 - step * .45), price * (1 - step * .9));
    const support3 = below[2] ?? Math.min(support2 * (1 - step * .45), price * (1 - step * 1.35));
    const r1 = above[0] ?? price * (1 + step * .45);
    const r2 = above[1] ?? Math.max(r1 * (1 + step * .45), price * (1 + step * .9));
    const breakout1 = r1 + buffer;
    const retest1 = r1;
    const breakout2 = r2 + buffer;
    const pullback1 = support1;
    const pullback2 = support2;
    const pullback3 = support3;
    const measuredResistance = above.length > 0;
    const measuredSupport = below.length > 0;
    const mediumTermExitPrice = Number(a?.medium_term_exit_price) > 0 ? Number(a.medium_term_exit_price) : null;
    const priceCard = (kind, label, value, note) => `<article class="trade-level ${kind}"><span>${label}</span><b>${money(value)}</b><small>${note}</small></article>`;
    const pathCard = ({ direction, title, subtitle, condition, entries, invalidation }) => `<article class="trade-path ${direction}">
      <header class="trade-path-head"><div><span>${subtitle}</span><h4>${title}</h4></div><span class="trade-path-mark">${direction === "bullish" ? "↗" : "↘"}</span></header>
      <div class="trade-path-trigger"><b>شرط شروع مسیر</b><p>${condition}</p></div>
      <h5 class="trade-path-section-title">پله‌های خرید پیشنهادی</h5>
      <div class="trade-path-entries">${entries.length ? entries.map((item, index) => priceCard("entry", `پله ${index + 1} · ${item.label}`, item.value, item.note)).join("") : `<div class="trade-path-empty">در قیمت فعلی پلهٔ خرید معتبر بالاتر از حد خروج فوری وجود ندارد؛ خرید انجام نده.</div>`}</div>
      <div class="trade-path-invalidation"><b>لغو سناریو</b><span>${invalidation}</span></div>
    </article>`;
    const bullishPath = pathCard({
      direction: "bullish", subtitle: "مسیر اول · ورود پس از قدرت‌گرفتن قیمت", title: "خرید در صورت صعود",
      condition: `ابتدا قیمت بالای مقاومت نزدیک (${money(r1)}) بسته شود و تثبیت یا حجم، شکست را تأیید کند.`,
      entries: [
        { label: "شکست مقاومت", value: breakout1, note: `${measuredResistance ? "پس از بسته‌شدن بالای مقاومت اول" : "سطح تخمینی؛ مقاومت در داده نیست"} · تخصیص 30٪` },
        { label: "پولبک موفق", value: retest1, note: `${measuredResistance ? "بازگشت به مقاومت شکسته‌شده و حفظ آن" : "بازآزمایی سطح شکست با تأیید برگشت"} · تخصیص 40٪` },
        { label: "ادامه روند", value: breakout2, note: `${above.length > 1 ? "تثبیت بالای مقاومت بعدی" : "سطح تخمینی با دامنه نوسان"} · تخصیص 30٪` },
      ],
      invalidation: `اگر قیمت پس از شکست دوباره زیر ${money(r1)} تثبیت شد، ورودهای باقی‌مانده این مسیر را متوقف کن.`,
    });
    const pullbackEntries = mediumTermExitPrice == null ? [] : [
      { label: "حمایت نزدیک", value: pullback1, note: `${measuredSupport ? "حمایت اول؛ منتظر واکنش مثبت بمان" : "سطح تخمینی؛ حمایت در داده نیست"} · تخصیص 35٪` },
      { label: "اصلاح عمیق‌تر", value: pullback2, note: `${below.length > 1 ? "حمایت بعدی؛ ورود مشروط به حفظ سطح" : "سطح تخمینی با دامنه نوسان"} · تخصیص 35٪` },
      { label: "پله آخر", value: pullback3, note: `${below.length > 2 ? "حمایت پایین‌تر؛ فقط با تأیید برگشت" : "سطح تخمینی؛ از میانگین‌کم‌کردن بی‌شرط پرهیز کن"} · تخصیص 30٪` },
    ].filter((entry) => entry.value > mediumTermExitPrice);
    const lastAllowedPullback = pullbackEntries.length ? pullbackEntries[pullbackEntries.length - 1].value : mediumTermExitPrice;
    const pullbackPath = pathCard({
      direction: "pullback", subtitle: "مسیر دوم · ورود در اصلاح با تأیید برگشت", title: "خرید در صورت نزول و پولبک",
      condition: mediumTermExitPrice == null
        ? "قیمت به حمایت‌ها اصلاح کند؛ اما تا وقتی SMA(30) در دادهٔ معتبر موجود نیست، برای این مسیر پلهٔ خرید تعیین نمی‌شود."
        : `قیمت به حمایت‌ها اصلاح کند؛ هر پله فقط با حفظ سطح و نشانه برگشت بررسی شود و تا وقتی قیمت بالای حد میان‌مدت SMA(30) ${money(mediumTermExitPrice)} است اجرا شود.`,
      entries: pullbackEntries,
      invalidation: mediumTermExitPrice == null
        ? "با دریافت دادهٔ SMA(30)، حد خروج میان‌مدت مشخص می‌شود."
        : `اگر سطح ${money(lastAllowedPullback)} با فشار فروش شکسته شد، پله‌های بعدی را اجرا نکن و قاعدهٔ حد ضرر SMA(30) را رعایت کن.`,
    });
    const scenarios = Array.isArray(a?.scenarios) ? a.scenarios : [];
    const scenarioProbability = (direction) => {
      const scenario = scenarios.find((item) => item?.direction === direction);
      if (scenario?.probability == null) return null;
      const value = Number(scenario?.probability);
      return Number.isFinite(value) ? value : null;
    };
    const bullishProbability = scenarioProbability("bullish");
    const bearishProbability = scenarioProbability("bearish");
    const preferredDirection = bullishProbability != null && bearishProbability != null
      ? (bullishProbability > bearishProbability ? "bullish" : bearishProbability > bullishProbability ? "pullback" : "neutral")
      : a?.trend === "bullish" ? "bullish" : "pullback";
    const chosenPath = preferredDirection === "bullish" ? bullishPath
      : preferredDirection === "pullback" ? pullbackPath
      : `<div class="trade-path-empty">برآورد صعود و نزول برابر است؛ فعلاً هیچ‌یک از دو مسیر خرید برتری ندارد.</div>`;
    const chosenProbability = preferredDirection === "bullish" ? bullishProbability : bearishProbability;
    const chosenScenarioLabel = preferredDirection === "bullish" ? "صعودی"
      : preferredDirection === "pullback" ? "نزولی / پولبک" : "خنثی";
    const fallbackNote = (!measuredResistance || !measuredSupport) ? " هرجا سطح رسمی حمایت یا مقاومت موجود نبوده، سطح جایگزین با دامنه نوسان قیمت برآورد شده است." : "";
    const selectedScenarioText = preferredDirection === "neutral"
      ? `برآورد صعود و نزول برابر است (${num(chosenProbability, 0)}٪)؛ درصدها از شمارش سیگنال‌های Buy/Neutral/Sell ره‌آورد می‌آیند و احتمال آماریِ آزموده‌شده نیستند.`
      : bullishProbability != null && bearishProbability != null
        ? `مسیر ${chosenScenarioLabel} با برآورد بالاتر انتخاب شده (${num(chosenProbability, 0)}٪)؛ درصد از شمارش سیگنال‌های Buy/Neutral/Sell ره‌آورد می‌آید و احتمال آماریِ آزموده‌شده نیست.`
        : `مسیر ${chosenScenarioLabel} بر اساس جهت روند انتخاب شده؛ دادهٔ کافی برای مقایسهٔ برآورد دو سناریو نداریم.`;
    return `<section class="trade-plan"><div class="trade-plan-head"><div><span class="panel-kicker">برنامه ورود و مدیریت ریسک</span><h3>پله‌های خرید پیشنهادی</h3><p>${selectedScenarioText}</p></div><span class="trade-plan-badge">${priceBadge}: ${money(price)}</span></div>${exitManagementHtml(a)}<div class="trade-path-grid trade-path-grid-single">${chosenPath}</div><p class="trade-plan-note">سطوح ورود با قیمت، حمایت/مقاومت و ATR ره‌آورد محاسبه می‌شوند و با تازه‌شدن داده تغییر می‌کنند.${fallbackNote}</p></section>`;
  }

  function pivotTableHtml(pivots, currentPrice = null) {
    const columns = ["R3", "R2", "R1", "P", "S1", "S2", "S3"];
    const price = Number(currentPrice);
    const hasPrice = Number.isFinite(price) && price > 0;
    const nearRange = 0.05;
    const normalize = (key) => String(key || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const entries = Array.isArray(pivots)
      ? pivots.map((item) => ({
        name: item?.short_name_en || item?.name_en || "Pivot",
        values: new Map((item?.value || []).map((part) => [normalize(part?.name), part?.value]))
      }))
      : Object.entries(pivots || {}).map(([method, values]) => ({ name: method, values: new Map(Object.entries(values || {}).map(([key, value]) => [normalize(key), value])) }));
    const rows = entries.map(({ name, values }) => {
      const methodName = /^PivotPoint/i.test(name) ? name : `PivotPoint${name}(30)`;
      const cellFor = (column) => {
        const key = column.toLowerCase();
        let raw = column === "P" ? (values.get("p") ?? values.get("pp") ?? values.get("pivot") ?? values.get("pivotpoint")) : values.get(key);
        if (column === "P" && /camarilla/i.test(methodName)) {
          const support = Number(values.get("s1")), resistance = Number(values.get("r1"));
          if (Number.isFinite(support) && Number.isFinite(resistance)) raw = (support + resistance) / 2;
        }
        if (raw == null || raw === "") return `<td data-label="${column}">—</td>`;
        const value = Number(raw);
        if (!Number.isFinite(value)) return `<td data-label="${column}">—</td>`;
        const distance = hasPrice ? Math.abs(value - price) / price : Infinity;
        const near = distance <= nearRange;
        const side = value < price ? "support" : value > price ? "resistance" : "current";
        const className = near ? ` class="pivot-near-level pivot-near-${side}"` : "";
        const title = near ? `نزدیک قیمت فعلی · ${pct(distance * 100)} فاصله` : "";
        return `<td data-label="${column}"${className}${title ? ` title="${esc(title)}"` : ""}>${num(value, 0)}</td>`;
      };
      return `<tr><th scope="row">${esc(methodName)}</th>${columns.map(cellFor).join("")}</tr>`;
    });
    const body = rows.length
      ? `<div class="rahavard-pivot-scroll"><table dir="rtl"><thead><tr><th scope="col">نام</th>${columns.map((column) => `<th scope="col">${column}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
      : `<div class="rahavard-pivot-empty">سطوح پیوت برای این دارایی در داده‌های موجود نیست.</div>`;
    const currentPriceLabel = hasPrice ? `<span class="pivot-legend-price">قیمت فعلی <b>${num(price, 0)}</b></span>` : "";
    const legend = hasPrice ? `<div class="pivot-level-legend">${currentPriceLabel}<span class="pivot-legend-support">نزدیک حمایت</span><span class="pivot-legend-resistance">نزدیک مقاومت</span><small>فاصله تا قیمت فعلی حداکثر 5%</small></div>` : "";
    return `<section class="rahavard-pivot-table"><div class="rahavard-pivot-table-head"><div><h4>حمایت و مقاومت</h4><p>سطوح پیوت به تفکیک روش محاسبه</p>${legend}</div><span>${nf.format(rows.length)} روش</span></div>${body}</section>`;
  }

  function rahavardAnalysisHtml(a) {
    const computedFromChart = ["Rahavard365Chart", "TabdealChart"].includes(a.indicator_source);
    const signalFa = { buy: "خرید · مثبت", sell: "فروش · منفی", hold: "خنثی", strong_buy: "خرید قوی", strong_sell: "فروش قوی" };
    const siteSignals = {
      buy: ["صعودی", "positive"], strongbuy: ["صعودی", "positive"], bullish: ["صعودی", "positive"],
      sell: ["نزولی", "negative"], strongsell: ["نزولی", "negative"], bearish: ["نزولی", "negative"],
      neutral: ["خنثی", "neutral"], overbought: ["نزولی", "negative"], oversold: ["صعودی", "positive"],
      resistance: ["نزولی", "negative"], support: ["خنثی", "neutral"], highvolume: ["خنثی", "neutral"],
      lowvolume: ["خنثی", "neutral"], unavailable: ["خنثی", "neutral"],
      bouncefromlower: ["صعودی", "positive"], nearupperuptrend: ["نزولی", "negative"]
    };
    const groups = { ...(a.indicators || {}), volumes: [] };
    const scoreMap = indicatorScoreMap(a);
    const hasModelScores = Object.keys(a.family_scores || {}).length > 0;
    const notes = new Map((a.indicator_notes || []).map((x) => [x.name, x]));
    const groupNames = { oscillators: "نوسانگرها و روند", moving_averages: "میانگین‌ها و باندها", bands: "باندهای نوسان", pivots: "پیوت‌ها و سطوح", volumes: "شاخص‌های حجم" };
    const pivotTable = pivotTableHtml(groups.pivots, a.price);
    const valueNames = {
      rsi: "RSI", mfi: "جریان پول", cci: "CCI", wr: "Williams %R", k: "خط K", d: "خط D",
      up: "Aroon صعودی", down: "Aroon نزولی", adx: "قدرت روند", plus_di: "+DI (جهت مثبت)", minus_di: "−DI (جهت منفی)", awesome: "AO", stochrsi: "StochRSI",
      macd: "خط MACD", signal: "خط سیگنال", MTM: "مومنتوم", value: "مقدار",
      tenken_sen_formula: "تنکان‌سن", tenkan_sen_formula: "تنکان‌سن", kijun_sen_formula: "کیجون‌سن", senkou_span_a_formula: "ابر A",
      senkou_span_b_formula: "ابر B", upper: "سقف باند", middle: "خط میانی", lower: "کف باند", distance: "فاصله از باند بالا",
      histogram: "هیستوگرام", mtm: "تغییر ۶ روزه (مومنتوم)", previous_value: "مقدار قبلی",
      dl: "فاصله قیمت تا کف (%)", distance: "فاصله قیمت تا سقف (%)", pivot: "نقطه پیوت", r1: "مقاومت ۱", r2: "مقاومت ۲", r3: "مقاومت ۳",
      r4: "مقاومت ۴", s1: "حمایت ۱", s2: "حمایت ۲", s3: "حمایت ۳", s4: "حمایت ۴",
      rv: "حجم نسبی", vrsi: "VRSI", vmacd: "VMACD", obv: "OBV"
    };
    const volumeIndicator = (item) => /^(OBV|RV|VRSI|VMACD|SM)\s*\(/i.test(String(item?.short_name_en || item?.name_en || ""));
    const cards = Object.entries(groups).flatMap(([group, items]) => group === "pivots" || group === "volumes" ? [] : (items || []).filter((item) => !volumeIndicator(item) && hasIndicatorValue(item)).map((item) => {
      const name = item.short_name_en || item.name_en || "شاخص ره‌آورد";
      const displayName = /^MACD\(/i.test(name) ? "MACD(12,26,9)" : name;
      const note = notes.get(name) || {};
      const rawSignal = String(item.signal || "Neutral");
      const signalKey = rawSignal.toLowerCase().replace(/[^a-z]/g, "");
      const rawScore = item.score ?? item.indicator_score ?? item.technical_score;
      const modelScore = lookupIndicatorScore(scoreMap, name);
      const explicitScore = hasModelScores ? (modelScore ?? NaN) : (rawScore == null ? NaN : Number(rawScore));
      const [signalLabel, state] = Number.isFinite(explicitScore)
        ? (({ label, state }) => [label, state])(scoreBandAssessment(explicitScore))
        : (hasModelScores ? ["خنثی", "neutral"] : (siteSignals[signalKey] || ["خنثی", "neutral"]));
      const parts = Array.isArray(item.value) ? item.value : [];
      const values = (parts.length === 1 && Number.isFinite(Number(modelScore)))
        ? `<div class="rahavard-indicator-value"><span>امتیاز شاخص (از ۱۰۰)</span><b>${num(modelScore, 1)}</b></div>`
        : parts.map((part) => {
        const val = Number(part.value);
        if (!Number.isFinite(val)) return "";
        const key = String(part.name || "");
        const percentValue = /distance/i.test(key) || key === "dl";
        const priceIndicator = /^(EMA|SMA|BB|KELTNER|Ichimoku|PivotPoint)/i.test(name) && !percentValue;
        const normalizedValue = /stochrsi/i.test(name) && /stochrsi/i.test(key) ? (val <= 1 ? val * 100 : val) : val;
        const rendered = percentValue ? pct(val * 100) : num(normalizedValue, priceIndicator ? 0 : 2);
        return `<div class="rahavard-indicator-value"><span>${esc(valueNames[key] || part.long_name_en || key)}</span><b>${rendered}</b></div>`;
      }).join("");
      const noValueNote = computedFromChart ? "دادهٔ کافی برای محاسبهٔ این شاخص موجود نیست." : "مقداری در پاسخ ره‌آورد نبود.";
      const numericSummary = indicatorNumericSummary(name, item);
      const modelNote = indicatorModelNote(name);
      const adjustmentNote = indicatorAdjustedNote(name, modelScore, a.family_scores);
      const guideMeaning = /^RSI\(14\)/i.test(name) ? indicatorPlainMeaning("RSI(14)")
        : /stochrsi/i.test(name) ? indicatorPlainMeaning("StochRSI(14)")
          : note.meaning || indicatorPlainMeaning(name);
      return `<article class="indicator-card rahavard-indicator-card"><div class="indicator-card-head"><div><b>${esc(displayName)}</b><small>${esc(groupNames[group] || group)}</small></div><span class="indicator-status ${state}">${esc(signalLabel)}</span></div>${modelNote || adjustmentNote ? `<small class="indicator-model-note">${esc(modelNote || adjustmentNote)}</small>` : ""}<div class="rahavard-indicator-values">${values || `<span class="factor-foot">${esc(noValueNote)}</span>`}</div><p>${esc(numericSummary)}</p><div class="indicator-range-guide"><b>این شاخص چه می‌گوید؟</b><span>${esc(guideMeaning)}</span></div></article>`;
    }));
    const gaugeCards = (["main", "pivot"]).map((key) => {
      const gauge = a.site_gauges?.[key];
      if (!gauge) return "";
      const title = key === "main" ? "جمع‌بندی تکنیکال" : key === "pivot" ? "پیوت" : "حجم";
      const counts = gauge.footer || {};
      const countText = Object.entries(counts).map(([label, value]) => `${label}: ${value?.value ?? "—"}`).join(" · ");
      return `<div class="readout-card"><span>${title} · ${computedFromChart ? "محاسبه از نمودار" : "سیگنال ره‌آورد"}</span><strong>${num(gauge.signal?.value, 0)}</strong><em class="indicator-status neutral">${esc(countText)}</em></div>`;
    }).join("");
    const score = a.technical_score == null ? "—" : num(a.technical_score, 0);
    const cls = a.signal === "buy" ? "bullish" : a.signal === "sell" ? "bearish" : "";
    const overview = `<section class="analysis-overview rahavard-overview">${rahavardRecommendationHtml(a)}</section>`;
    const dashboardModel = a.score_method?.startsWith("dashboard_rahavard_excel_weighted_");
    const tradePlan = dashboardModel ? exitManagementHtml(a) : tradePlanHtml(a);
    const indicatorSourceName = a.indicator_source === "TabdealChart"
      ? "Tabdeal · محاسبهٔ داخلی"
      : a.indicator_source === "Rahavard365Chart" ? "ره‌آورد۳۶۵ · محاسبهٔ داخلی" : "ره‌آورد۳۶۵";
    const indicatorSource = a.indicator_source_url
      ? ` · <a href="${esc(a.indicator_source_url)}" target="_blank" rel="noopener">منبع اندیکاتورها: ${esc(indicatorSourceName)}</a>` : ` · منبع اندیکاتورها: ${esc(indicatorSourceName)}`;
    const indicatorTime = a.indicator_data_timestamp ? ` · دریافت ${esc(formatDate(a.indicator_data_timestamp))}` : "";
    const volumeDataNote = "";
    const signalDescription = computedFromChart ? "سیگنال محاسبه‌شده از کندل‌های نمودار" : "سیگنال رسمی";
    return `${overview}${tradePlan}${volumeDataNote}<section class="indicator-workbench"><div class="indicator-section-title"><div><h3>اندیکاتورهای هر نماد</h3><p>${nf.format(cards.length)} شاخص با مقدار فعلی، تفسیر عددی و ${signalDescription}${indicatorSource}${indicatorTime}</p></div></div>${pivotTable}<div class="indicator-readouts">${gaugeCards}</div><div class="indicator-card-grid">${cards.join("")}</div><div class="indicator-key-note"><b>راهنما:</b> خریدزدگی و فروش‌زدگی هشدار افراط‌اند؛ همراه روند و حمایت/مقاومت خوانده شوند.</div></section>`;
  }

  function analysisHtml(a) {
    if ((["Rahavard365Chart", "TabdealChart"].includes(a?.indicator_source) && Array.isArray(a.indicators?.oscillators)) || (a?.source === "Rahavard365" && (a?.indicator_source === "Rahavard365" || !a?.score_method?.startsWith("dashboard_rahavard_excel_weighted_")))) return rahavardAnalysisHtml(a);
    if (!a || a.technical_score == null) return `<div class="empty-state compact"><b>داده کافی برای محاسبه امتیاز موجود نیست</b><small>مدل فقط داده ذخیره‌شده از منبع را تحلیل می‌کند.</small></div>`;
    const all = a.indicators?.indicators || {};
    const scoreMap = indicatorScoreMap(a);
    const seen = new Set();
    const entries = Object.entries(all).filter(([key, value]) => {
      if (!hasIndicatorValue(value)) return false;
      const normalized = key === "ARRON(25)" ? "Aroon(25)" : key;
      if (seen.has(normalized)) return false;
      seen.add(normalized);
      return true;
    });
    const cards = entries.map(([key, value]) => {
      const assessment = indicatorAssessment(key, value, lookupIndicatorScore(scoreMap, key), Object.keys(a.family_scores || {}).length > 0);
      const name = indicatorFa[key] || (/^(EMA|SMA)\(/.test(key) ? (key.startsWith("EMA") ? "میانگین نمایی" : "میانگین ساده") : key);
      const displayKey = key === "Aroon(25)" ? "ARRON(25)" : key;
      const extra = indicatorExtra(key, value);
      const modelNote = indicatorModelNote(key);
      const adjustmentNote = indicatorAdjustedNote(key, lookupIndicatorScore(scoreMap, key), a.family_scores);
      return `<article class="indicator-card" title="فرمول: ${esc(value.formula || "ثبت نشده")}"><div class="indicator-card-head"><div><b>${esc(name)}</b><small>${esc(displayKey)}</small></div><span class="indicator-status ${assessment.state}">${assessment.label}</span></div>${modelNote || adjustmentNote ? `<small class="indicator-model-note">${esc(modelNote || adjustmentNote)}</small>` : ""}<div class="indicator-card-value"><strong>${indicatorValueText(key, value)}</strong><span>${key.startsWith("EMA(") || key.startsWith("SMA(") ? "مقدار میانگین" : key === "BB(20)" || key === "KELTNER(16)" ? "خط میانی کانال" : key === "Ichimoku(9,26,52,26)" ? "خط تنکان" : "مقدار فعلی"}</span></div><p>${esc(indicatorNumericSummary(key, value))}</p><div class="indicator-range-guide"><b>این شاخص چه می‌گوید؟</b><span>${esc(indicatorPlainMeaning(key))}</span></div>${extra ? `<div class="indicator-extra">${esc(extra)}</div>` : ""}<div class="indicator-previous">مقدار قبلی <b>${value.previous_value == null ? "—" : num(value.previous_value, 3)}</b></div></article>`;
    }).join("");
    const pivotTable = pivotTableHtml(a.indicators?.pivots || {}, a.price);
    const ind = all;
    const rsi = ind["RSI(14)"];
    const macd = ind["MACD(12,26,9)"];
    const adx = ind["ADX(14)"];
    const rsiAssessment = indicatorAssessment("RSI(14)", rsi, lookupIndicatorScore(scoreMap, "RSI(14)"), Object.keys(a.family_scores || {}).length > 0);
    const macdAssessment = indicatorAssessment("MACD(12,26,9)", macd, lookupIndicatorScore(scoreMap, "MACD(12,26,9)"), Object.keys(a.family_scores || {}).length > 0);
    const adxAssessment = indicatorAssessment("ADX(14)", adx, lookupIndicatorScore(scoreMap, "ADX(14)"), Object.keys(a.family_scores || {}).length > 0);
    const ma = a.indicators?.moving_average_analysis || {};
    const maAlignment = [ma.price_above_ema20, ma.price_above_ema50, ma.price_above_ema200].filter((v) => v != null);
    const maState = maAlignment.length && maAlignment.every(Boolean) ? "positive" : maAlignment.length && maAlignment.every((v) => !v) ? "caution" : "neutral";
    const maLabel = maState === "positive" ? "بالای هر سه میانگین" : maState === "caution" ? "زیر هر سه میانگین" : "ترکیبی / ناقص";
    const summary = (label, value, state, meaning) => `<div class="readout-card"><span>${label}</span><strong>${value}</strong><em class="indicator-status ${state}">${meaning}</em></div>`;
    const summaryCards = [
      hasIndicatorValue(rsi) ? summary("RSI · قدرت حرکت", num(rsi.value, 1), rsiAssessment.state, `${rsiAssessment.label} · مدل: تا ۳۵ خرید، ۳۵ تا ۶۰ خنثی، از ۶۰ فروش`) : "",
      hasIndicatorValue(macd) ? summary("MACD · شتاب روند", `خط ${num(macd.value, 2)} / هیستوگرام ${num(macd.histogram, 2)}`, macdAssessment.state, Number(macd.histogram) > 0 ? "خط MACD بالای سیگنال؛ شتاب بهتر شده" : Number(macd.histogram) < 0 ? "خط MACD زیر سیگنال؛ شتاب ضعیف‌تر است" : "خط و سیگنال نزدیک هم") : "",
      hasIndicatorValue(adx) ? summary("ADX · قدرت و جهت روند", num(adx.value, 1), adxAssessment.state, `${adxAssessment.label} · ADX جهت را به‌تنهایی نمی‌گوید`) : "",
      maAlignment.length ? summary("میانگین‌های EMA", `${maAlignment.filter(Boolean).length} از ${maAlignment.length}`, maState, `${maLabel} · نسبت قیمت به EMA20/50/200`) : ""
    ].filter(Boolean).join("");
    const overview = `<section class="analysis-overview rahavard-overview">${rahavardRecommendationHtml(a)}</section>`;
    const isDashboardModel = a.score_method?.startsWith("dashboard_rahavard_excel_weighted_");
    const tradePlan = isDashboardModel ? exitManagementHtml(a) : tradePlanHtml(a);
    const chartBased = ["Rahavard365Chart", "TabdealChart"].includes(a.indicator_source);
    const chartSourceName = a.indicator_source === "TabdealChart" ? "نمودار Tabdeal" : "نمودار ره‌آورد۳۶۵";
    const chartSourceNote = chartBased
      ? `<div class="indicator-key-note">اندیکاتورها و امتیاز با محاسبهٔ داخلی از کندل‌های <a href="${esc(a.indicator_source_url || (a.indicator_source === "TabdealChart" ? "https://tabdeal.org/buy-usdt" : "https://rahavard365.com"))}" target="_blank" rel="noopener">${chartSourceName}</a> به دست می‌آیند. زمان داده: ${esc(formatDate(a.indicator_data_timestamp || a.data_timestamp))}</div>`
      : "";
    const indicatorDescription = chartBased ? "مقادیر محاسبه‌شده از کندل‌های نمودار" : "سیگنال رسمی";
    return `${overview}${tradePlan}${chartSourceNote}<section class="indicator-workbench"><div class="indicator-section-title"><div><h3>اندیکاتورهای هر نماد</h3><p>${nf.format(entries.length)} شاخص با مقدار فعلی، تفسیر عددی و ${indicatorDescription}</p></div></div>${pivotTable}<div class="indicator-readouts">${summaryCards}</div><div class="indicator-card-grid">${cards}</div><div class="indicator-key-note"><b>راهنما:</b> خریدزدگی و فروش‌زدگی هشدار افراط‌اند؛ همراه روند و حمایت/مقاومت خوانده شوند.</div></section>`;
  }

  function renderOverviewMarketSummary() {
    const node = $("#overview-market-summary");
    if (!node) return;
    const items = [
      ["\u0637\u0644\u0627\u06cc \u062c\u0647\u0627\u0646\u06cc", state.gold],
      ["دلار", state.dollar],
      ["\u0634\u0627\u062e\u0635 \u06a9\u0644", state.tepix],
      ["\u0637\u0644\u0627\u06cc 18 \u0639\u06cc\u0627\u0631", state.gold18k],
    ];
    node.innerHTML = items.map(([label, quote]) => {
      const raw = quote?.returns?.daily;
      const daily = raw == null ? NaN : Number(raw);
      const value = Number.isFinite(daily) ? `${daily > 0 ? "+" : ""}${num(daily, 2)}%` : "\u2014";
      const tone = Number.isFinite(daily) ? changeClass(daily) : "unknown";
      return `<span class="market-change-chip"><span>${label}</span><b class="${tone}">${value}</b></span>`;
    }).join("") + `<small class="market-summary-period">مبنای درصدها: تغییر نسبت به کندل روزانهٔ قبل</small>`;
  }

  function renderOverviewAssetComparison() {
    const target = $("#overview-asset-comparison-body");
    if (!target) return;
    const trendLabels = { bullish: "صعودی", bearish: "نزولی", neutral: "خنثی", unavailable: "نامشخص" };
    const strengthLabels = { strong: "قوی", medium: "متوسط", weak: "ضعیف", unavailable: "نامشخص" };
    const riskLabels = { low: "کم", medium: "متوسط", elevated: "نسبتاً بالا", high: "بالا", very_high: "بسیار بالا", unavailable: "نامشخص" };
    const entryLabels = { suitable: "مساعد", confirmation: "نیازمند اصلاح و تثبیت", unsuitable: "نامساعد", unavailable: "نامشخص" };
    const title = $("#asset-comparison-title");
    if (title) title.textContent = `مقایسه تکنیکال چهار دارایی · ${horizonLabel(state.investmentHorizon)}`;
    const kicker = $("#asset-comparison-kicker");
    if (kicker) kicker.textContent = `نمای مقایسه‌ای · دید ${horizonLabel()}`;
    const trendHeading = $("#asset-comparison-trend-heading");
    if (trendHeading) trendHeading.textContent = `جمع‌بندی ${horizonLabel()}`;
    const assets = [
      ["طلای جهانی · XAU/USD", state.gold],
      ["دلار · USD/IRT", state.dollar],
      ["شاخص کل · TEPIX", state.tepix],
      ["طلای ۱۸ عیار", state.gold18k],
    ];
    const priceUnits = { GOLD: "دلار / اونس", USD_IR_FREE: "تومان", TEPIX: "واحد", GOLD_18K: "ریال / گرم" };
    const rows = assets.map(([name, quote]) => {
      const analysis = quote?.analysis || {};
      const rawPrice = quote?.price ?? analysis.price;
      const price = rawPrice != null && Number.isFinite(Number(rawPrice)) ? `${money(rawPrice)} ${priceUnits[quote?.symbol] || ""}` : "—";
      const score = analysis.technical_score == null ? "—" : `${num(analysis.technical_score, 0)} / ۱۰۰`;
      const direction = trendLabels[analysis.score_band || analysis.trend || analysis.medium_term_trend] || "نامشخص";
      const strength = strengthLabels[analysis.trend_strength] || "نامشخص";
      const risk = riskLabels[analysis.risk] || "نامشخص";
      const entry = entryLabels[analysis.entry_quality?.status] || "نامشخص";
      const coverage = analysis.data_coverage_pct == null ? "—" : `${num(analysis.data_coverage_pct, 0)}٪`;
      const tone = analysis.score_band || analysis.trend || analysis.medium_term_trend || "unavailable";
      return `<tr><th scope="row">${name}</th><td>${price}</td><td>${score}</td><td><span class="asset-comparison-tag ${tone}">${direction}</span></td><td>${strength}</td><td>${risk}</td><td>${entry}</td><td>${coverage}</td></tr>`;
    });
    target.innerHTML = rows.join("");
    const summaryNode = $("#overview-asset-comparison-summary");
    if (summaryNode) {
      const available = assets.map(([name, quote]) => ({ name, analysis: quote?.analysis || {} }))
        .filter((item) => item.analysis.technical_score != null && Number.isFinite(Number(item.analysis.technical_score)));
      if (!available.length) {
        summaryNode.textContent = "با دریافت امتیاز و ریسک نوسان هر چهار دارایی، مقایسهٔ نسبی اینجا نمایش داده می‌شود.";
      } else {
        const topScore = [...available].sort((a, b) => Number(b.analysis.technical_score) - Number(a.analysis.technical_score))[0];
        const entryRated = available.filter((item) => item.analysis.entry_quality?.score != null);
        const bestEntry = [...entryRated].sort((a, b) => Number(b.analysis.entry_quality.score) - Number(a.analysis.entry_quality.score))[0];
        const highestRisk = [...available].filter((item) => item.analysis.risk_score != null)
          .sort((a, b) => Number(b.analysis.risk_score) - Number(a.analysis.risk_score))[0];
        const parts = [`بالاترین امتیاز تکنیکال فعلی مربوط به ${topScore.name} است (${num(topScore.analysis.technical_score, 0)} از ۱۰۰).`];
        if (bestEntry) parts.push(`بهترین کیفیت ورودِ محاسبه‌شده مربوط به ${bestEntry.name} است (${num(bestEntry.analysis.entry_quality.score, 0)} از ۱۰۰).`);
        if (highestRisk) parts.push(`بیشترین ریسک نوسان در دادهٔ فعلی برای ${highestRisk.name} ثبت شده است (${num(highestRisk.analysis.risk_score, 0)} از ۱۰۰).`);
        parts.push("امتیاز روند و کیفیت ورود دو سنجهٔ جدا هستند؛ این مقایسه توصیهٔ خرید یا فروش نیست.");
        summaryNode.textContent = parts.join(" ");
      }
    }
  }

  function horizonLabel(horizon = state.investmentHorizon) {
    return horizon === "short" ? "کوتاه‌مدت" : "میان‌مدت";
  }

  function syncInvestmentHorizonControl() {
    $$(".investment-horizon-select").forEach((select) => { select.value = state.investmentHorizon; });
    const fundNote = $("#fund-score-model-note");
    if (fundNote) fundNote.textContent = `امتیاز تکنیکال با مدل ${horizonLabel()} محاسبه می‌شود؛ وزن خانواده‌ها و شاخص‌ها در نمایهٔ هر صندوق مشخص است.`;
  }

  async function changeInvestmentHorizon(horizon) {
    const next = horizon === "short" ? "short" : "long";
    if (next === state.investmentHorizon) return;
    state.investmentHorizon = next;
    try { localStorage.setItem(horizonStorageKey, next); } catch {}
    fundScoreGeneration += 1;
    fundScoreAttemptedKeys.clear();
    syncInvestmentHorizonControl();
    toast(`امتیازدهی ${horizonLabel()} در حال به‌روزرسانی است…`);
    const reloads = [loadOverview()];
    if (state.currentView === "funds") reloads.push(loadFunds());
    if (state.currentView === "watchlist") reloads.push(loadWatchlist());
    const detail = $("#fund-detail");
    if (state.currentView === "funds" && detail && !detail.classList.contains("hidden") && detail.dataset.fundSymbol) {
      reloads.push(showFund(detail.dataset.fundSymbol));
    }
    await Promise.all(reloads);
    toast(`مدل امتیازدهی ${horizonLabel()} اعمال شد.`);
  }

  async function loadOverview() {
    const requestedHorizon = state.investmentHorizon;
    try {
      const summary = await api("/api/market/summary");
      if (requestedHorizon !== state.investmentHorizon) return;
      state.summary = summary;
      syncInvestmentHorizonControl();
      state.gold = summary.gold; state.gold18k = summary.gold18k; state.dollar = summary.dollar; state.tepix = summary.tepix;
      renderOverviewMarketSummary();
      renderOverviewAssetComparison();
      marketQuote(state.gold, "gold"); marketQuote(state.gold18k, "gold18k"); marketQuote(state.dollar, "dollar"); marketQuote(state.tepix, "tepix");
      renderGold18kValuation(summary.gold18k?.valuation);
      freshness($("#gold-analysis-status"), state.gold?.status, state.gold?.data_timestamp);
      freshness($("#gold18k-analysis-status"), state.gold18k?.status, state.gold18k?.data_timestamp);
      freshness($("#dollar-analysis-status"), "not_tested", null);
      freshness($("#tepix-analysis-status"), state.tepix?.status, state.tepix?.data_timestamp);
      $("#gold-analysis").innerHTML = analysisHtml(state.gold?.analysis);
      $("#gold18k-analysis").innerHTML = analysisHtml(state.gold18k?.analysis);
      $("#dollar-analysis").innerHTML = `<div class="empty-state compact"><b>در حال دریافت کندل‌های دلار از Tabdeal…</b></div>`;
      $("#tepix-analysis").innerHTML = analysisHtml(state.tepix?.analysis);
      let dollarIndicatorFeed;
      try { dollarIndicatorFeed = await api("/api/dollar/indicators"); }
      catch (indicatorError) { dollarIndicatorFeed = { status: "failed", error: indicatorError.message }; }
      if (requestedHorizon !== state.investmentHorizon) return;
      if (dollarIndicatorFeed?.analysis) {
        const baseAnalysis = state.dollar?.analysis || {};
        const sourceAnalysis = dollarIndicatorFeed.analysis;
        const mergedAnalysis = {
          ...baseAnalysis,
          ...sourceAnalysis,
          indicator_source: dollarIndicatorFeed.source,
          indicator_source_url: dollarIndicatorFeed.source_url,
          indicator_data_timestamp: dollarIndicatorFeed.data_timestamp,
        };
        state.dollar = { ...state.dollar, analysis: mergedAnalysis };
        state.summary.dollar = state.dollar;
        $("#dollar-analysis").innerHTML = analysisHtml(mergedAnalysis);
        freshness($("#dollar-analysis-status"), dollarIndicatorFeed.status, dollarIndicatorFeed.data_timestamp);
      } else {
        const message = dollarIndicatorFeed?.error || "پاسخ معتبر از منبع دریافت نشد.";
        const sourceUrl = dollarIndicatorFeed?.source_url || "https://tabdeal.org/buy-usdt";
        $("#dollar-analysis").innerHTML = `<div class="empty-state compact"><b>اندیکاتورهای دلار در دسترس نیستند</b><small>${esc(message)} · <a href="${esc(sourceUrl)}" target="_blank" rel="noopener">منبع Tabdeal</a></small></div>`;
        freshness($("#dollar-analysis-status"), dollarIndicatorFeed?.status || "failed", dollarIndicatorFeed?.data_timestamp);
      }
      const sourceList = summary.sources || [];
      const connected = sourceList.filter((s) => s.status === "connected").length;
      $("#source-count").textContent = `${nf.format(connected)}/${nf.format(sourceList.length)}`;
      $("#sidebar-status").className = `status-dot ${connected ? "" : "bad"}`;
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
    if (options.forceNav) fundNavAttemptedKeys.clear();
    const requestedNavGeneration = ++fundNavGeneration;
    const requestedHorizon = state.investmentHorizon;
    try {
      const url = new URL("/api/funds", location.origin);
      const search = options.search ?? $("#fund-search")?.value ?? "";
      const category = options.category ?? $("#fund-category")?.value ?? "";
      const sort = options.sort ?? $("#fund-sort")?.value ?? "data_timestamp";
      url.searchParams.set("search", search); url.searchParams.set("category", category); url.searchParams.set("sort", sort);
      const data = await api(url.pathname + url.search);
      if (requestedHorizon !== state.investmentHorizon) return;
      state.funds = sortedFundItems(data.items);
      state.funds.forEach((fund) => {
        const cachedNav = fundNavValueCache.get(String(fund.fund_key || fund.symbol || ""));
        if (cachedNav) {
          Object.assign(fund, cachedNav);
          const price = Number(fund.market_price ?? fund.real_close_price);
          const nav = Number(cachedNav.nav);
          fund.nav_premium_pct = Number.isFinite(price) && price > 0 && Number.isFinite(nav) && nav > 0
            ? (price / nav - 1) * 100 : null;
        }
      });
      const resultCount = $("#fund-result-count");
      if (resultCount) resultCount.textContent = `${nf.format(data.count)} صندوق`;
      renderFundTable(state.funds);
      renderMarketWatchlist(options.existing?.length ? options.existing : state.funds.slice(0, 5));
      const fundCount = $("#fund-count");
      if (fundCount) fundCount.textContent = nf.format(data.count);
      const fs = _sourceByName("rahavard_funds"); freshness($("#funds-freshness"), fs?.status || "unavailable", fs?.last_data_timestamp);
      const categories = Object.groupBy ? Object.groupBy(state.funds, (x) => x.category || "نامشخص") : state.funds.reduce((a, x) => ((a[x.category || "نامشخص"] ||= []).push(x), a), {});
      const cats = Object.entries(categories).sort((a, b) => b[1].length - a[1].length).slice(0, 3);
      const maximum = Math.max(1, ...cats.map((x) => x[1].length));
      const categoryBars = $("#category-bars");
      if (categoryBars) categoryBars.innerHTML = cats.length ? cats.map(([name, rows]) => `<div class="cat-row"><span>${esc(name)}</span><div><i style="width:${rows.length / maximum * 100}%"></i></div><b>${nf.format(rows.length)}</b></div>`).join("") : `<div class="empty-state compact"><b>دسته صندوق در دسترس نیست</b></div>`;
      const best = state.funds.find((f) => f.technical_score != null);
      const bestFund = $("#best-fund");
      if (bestFund) bestFund.textContent = best ? (best.display_symbol || `شناسه ${best.rahavard_asset_id}`) : state.funds.length ? "برای امتیاز، نمایهٔ نماد را باز کنید" : "هنوز داده‌ای نیست";
      if (state.currentView === "funds") {
        void fillVisibleFundScores();
        void fillVisibleFundNavs(requestedNavGeneration);
      }
    } catch (err) {
      if (!options.quiet) toast(`فهرست صندوق‌ها در دسترس نیست: ${err.message}`, true);
      $("#funds-freshness") && freshness($("#funds-freshness"), "unavailable", null);
    }
  }

  function _sourceByName(name) { return (state.summary?.sources || []).find((s) => s.name === name) || null; }

  const fundSortTextKeys = new Set(["name", "updated_at", "data_timestamp", "fund_type_label"]);
  function sortedFundItems(items) {
    const rows = [...(items || [])];
    const key = fundSortState.key;
    rows.sort((a, b) => {
      const left = key === "name" ? (a?.name || a?.display_symbol || a?.symbol) : a?.[key];
      const right = key === "name" ? (b?.name || b?.display_symbol || b?.symbol) : b?.[key];
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
      fundSortState.direction = fundSortTextKeys.has(key) || key === "risk_score" ? 1 : -1;
    }
    state.funds = sortedFundItems(state.funds);
    renderFundTable(state.funds);
    const mobileScoreSort = $("#fund-mobile-score-sort");
    if (mobileScoreSort) {
      const values = {
        technical_score: fundSortState.direction === 1 ? "score_asc" : "score_desc",
        buy_suitability_rank: "buy_suitability_rank",
        fund_type_label: fundSortState.direction === 1 ? "type_asc" : "type_desc",
        monthly_return: "monthly_return",
        three_month_return: "three_month_return",
        six_month_return: "six_month_return",
        one_year_return: "one_year_return",
        nav_premium_pct: "nav_premium_pct",
        market_price: "market_price",
        data_timestamp: "data_timestamp",
      };
      mobileScoreSort.value = values[key] || "";
    }
  }

  // ETF directory rows expose a Rahavard asset ID, not necessarily an exchange ticker.
  function renderFundTable(items) {
    const target = $("#fund-table");
    if (!items.length) {
      const search = $("#fund-search")?.value.trim() || "";
      const category = $("#fund-category")?.value.trim() || "";
      const filtered = search || category;
      const filterLabel = search || $("#fund-category")?.selectedOptions?.[0]?.textContent?.trim() || "";
      target.innerHTML = `<tr><td colspan="11"><div class="empty-state fund-empty-state"><span>&#9632;</span><b>${filtered ? "نتیجه‌ای برای فیلتر فعلی پیدا نشد" : "صندوقی از ره‌آورد۳۶۵ دریافت نشده"}</b><small>${filtered ? `فیلتر فعال: ${esc(filterLabel)} · برای نمایش همه صندوق‌ها فیلتر را پاک کنید.` : "وضعیت اتصال ره‌آورد را در صفحه وضعیت سامانه ببینید."}</small>${filtered ? `<button class="button button-quiet fund-clear-filter" type="button" data-clear-fund-filters>پاک کردن فیلترها</button>` : ""}</div></td></tr>`;
      return;
    }
    const amount = (value) => value == null ? "—" : money(value);
    target.innerHTML = items.map((f) => {
      const price = f.market_price ?? f.real_close_price;
      const scoreValue = f.technical_score == null ? null : Number(f.technical_score);
      const scoreCoverage = f.data_coverage_pct == null ? null : Number(f.data_coverage_pct);
      const scoreTone = scoreValue == null || !Number.isFinite(scoreValue) ? "unknown" : Math.floor(scoreValue + 0.5) >= 70 ? "positive" : Math.floor(scoreValue + 0.5) <= 40 ? "negative" : "neutral";
      const scoreTitle = `امتیاز ${horizonLabel()} AliVest · پوشش داده: ${scoreCoverage != null && Number.isFinite(scoreCoverage) ? `${num(scoreCoverage, 0)}٪` : "نامشخص"}`;
      const scoreCell = scoreValue == null || !Number.isFinite(scoreValue) ? `<span class="technical-score-chip unknown" title="${esc(f.technical_error || "امتیاز هنوز محاسبه نشده")}">—</span>` : `<span class="technical-score-chip ${scoreTone}" title="${esc(scoreTitle)}">${num(scoreValue, 0)} / 100</span>`;
      const typeLabel = f.fund_type_label || f.category || "نامشخص";
      const assessment = f.purchase_assessment || {};
      const assessmentStatus = ["suitable", "wait", "unsuitable"].includes(assessment.status) ? assessment.status : "unknown";
      const assessmentCell = `<div class="fund-purchase-assessment"><span class="fund-purchase-chip ${assessmentStatus}">${esc(assessment.label || "داده کافی نیست")}</span><small>${esc(assessment.reason || f.technical_error || "ارزیابی پس از دریافت دادهٔ تکنیکال نمایش داده می‌شود.")}</small></div>`;
      const fundName = f.name || f.display_symbol || f.symbol || "—";
      const priceFresh = price != null && f.price_is_cached === false;
      const freshnessLabel = priceFresh ? "داده تازه" : "داده کهنه یا ناموجود";
      const priceCell = `<span class="fund-latest-price">${amount(price)}</span><small class="fund-latest-change ${changeClass(f.daily_return)}">${pct(f.daily_return)}</small>`;
      const hasNav = Number(f.nav) > 0 && f.nav_premium_pct != null;
      const premiumTitle = !hasNav ? "NAV معتبر برای محاسبه در دسترس نیست" : `${f.nav_is_cached ? "بر پایهٔ آخرین NAV ذخیره‌شده" : "بر پایهٔ NAV تازه"} · فاصلهٔ قیمت بازار از NAV ${money(f.nav)} ریال`;
      const premiumCell = `<span class="watch-cell-primary ${hasNav ? changeClass(f.nav_premium_pct) : ""}" title="${esc(premiumTitle)}">${hasNav ? pct(f.nav_premium_pct) : "—"}</span>`;
      const timestamp = f.data_timestamp || f.updated_at;
      return `<tr><td data-label="نام نماد"><button class="row-open fund-symbol-open" data-fund="${esc(f.fund_key || f.symbol)}"><span class="fund-table-name"><i class="fund-freshness-dot ${priceFresh ? "fresh" : "stale"}" role="img" aria-label="${freshnessLabel}" title="${freshnessLabel}"></i><strong>${esc(fundName)}</strong></span></button></td><td data-label="نوع صندوق"><span class="fund-type-chip">${esc(typeLabel)}</span></td><td data-label="امتیاز" class="fund-technical-score">${scoreCell}</td><td data-label="وضعیت خرید" class="fund-buy-cell">${assessmentCell}</td><td data-label="بازده ماهانه"><span class="watch-cell-primary ${changeClass(f.monthly_return)}">${pct(f.monthly_return)}</span></td><td data-label="بازده ۳ماهه"><span class="watch-cell-primary ${changeClass(f.three_month_return)}">${pct(f.three_month_return)}</span></td><td data-label="بازده ۶ماهه"><span class="watch-cell-primary ${changeClass(f.six_month_return)}">${pct(f.six_month_return)}</span></td><td data-label="بازده یک‌ساله"><span class="watch-cell-primary ${changeClass(f.one_year_return)}">${pct(f.one_year_return)}</span></td><td data-label="حباب">${premiumCell}</td><td data-label="آخرین قیمت">${priceCell}</td><td data-label="زمان داده" class="fund-update-time">${esc(formatDate(timestamp))}</td></tr>`;
    }).join("");
    updateFundSortIndicators();
  }

  async function fillVisibleFundScores() {
    if (fundScoreFillRunning) return;
    const generation = fundScoreGeneration;
    const requestedHorizon = state.investmentHorizon;
    const pending = [...new Set(state.funds
      .filter((fund) => fund.technical_score == null)
      .map((fund) => fund.fund_key || fund.symbol)
      .filter((key) => key && !fundScoreAttemptedKeys.has(String(key)))
      .map(String))];
    if (!pending.length) return;

    fundScoreFillRunning = true;
    const progress = $("#fund-score-progress");
    let processed = 0;
    let scored = 0;
    let unavailable = 0;
    try {
      for (let offset = 0; offset < pending.length; offset += 4) {
        const batch = pending.slice(offset, offset + 4);
        let response;
        try {
          response = await api("/api/funds/scores/batch", {
            method: "POST",
            body: JSON.stringify({ fund_keys: batch, category_id: $("#fund-category")?.value || "" })
          });
        } catch (error) {
          if (generation !== fundScoreGeneration || requestedHorizon !== state.investmentHorizon) return;
          batch.forEach((key) => fundScoreAttemptedKeys.add(key));
          unavailable += batch.length;
          if (progress) progress.textContent = "دریافت امتیازهای نمودار ره‌آورد موقتاً متوقف شد؛ دوباره فهرست را به‌روز کنید.";
          break;
        }
        if (generation !== fundScoreGeneration || requestedHorizon !== state.investmentHorizon) return;

        const returned = new Set();
        for (const result of response.items || []) {
          const key = String(result.fund_key || "");
          if (!key) continue;
          returned.add(key);
          fundScoreAttemptedKeys.add(key);
          const listed = state.funds.find((fund) => String(fund.fund_key || fund.symbol) === key);
          if (listed) {
            listed.fund_type_key = result.fund_type_key || listed.fund_type_key;
            listed.fund_type_label = result.fund_type_label || listed.fund_type_label;
          }
          if (result.technical_score != null) {
            scored += 1;
            if (listed) {
              listed.technical_error = "";
              listed.technical_score = Number(result.technical_score);
              listed.data_coverage_pct = result.data_coverage_pct;
              listed.medium_term_exit_price = result.medium_term_exit_price;
              listed.purchase_assessment = result.purchase_assessment;
              listed.buy_suitability_rank = result.buy_suitability_rank;
              listed.risk_score = result.risk_score;
              listed.score_change_5d = result.score_change_5d;
              listed.score_change_20d = result.score_change_20d;
            }
          } else {
            unavailable += 1;
            if (listed) {
              listed.technical_error = result.error || "دادهٔ کافی از نمودار ره‌آورد برای محاسبهٔ امتیاز موجود نیست.";
              if (listed.purchase_assessment) listed.purchase_assessment = { ...listed.purchase_assessment, reason: listed.technical_error };
            }
          }
        }
        for (const key of batch) {
          if (!returned.has(key)) {
            fundScoreAttemptedKeys.add(key);
            unavailable += 1;
            const listed = state.funds.find((fund) => String(fund.fund_key || fund.symbol) === key);
            if (listed) {
              listed.technical_error = "پاسخی برای محاسبهٔ تکنیکال نمودار ره‌آورد از سرور دریافت نشد.";
              if (listed.purchase_assessment) listed.purchase_assessment = { ...listed.purchase_assessment, reason: listed.technical_error };
            }
          }
        }
        processed += batch.length;
        state.funds = sortedFundItems(state.funds);
        renderFundTable(state.funds);
        if (progress) progress.textContent = `محاسبهٔ امتیازها: ${nf.format(processed)} از ${nf.format(pending.length)}`;
      }
      if (progress && processed >= pending.length) {
        progress.textContent = unavailable
          ? `${nf.format(scored)} امتیاز آماده شد · ${nf.format(unavailable)} نماد دادهٔ کافی نداشت`
          : `${nf.format(scored)} امتیاز تکنیکال آماده شد`;
      }
    } finally {
      fundScoreFillRunning = false;
      if (generation !== fundScoreGeneration && state.currentView === "funds") {
        queueMicrotask(() => void fillVisibleFundScores());
      }
    }
  }

  function renderMarketWatchlist(items) {
    const target = $("#watchlist");
    // The dashboard watchlist summary was removed; fund loading should still
    // work when that optional surface is not present in the current layout.
    if (!target) return;
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
    const requestedHorizon = state.investmentHorizon;
    try {
      const data = await api(`/api/funds/${encodeURIComponent(symbol)}?skip_technical=true`);
      if (requestedHorizon !== state.investmentHorizon) return;
      const section = $("#fund-detail");
      section.dataset.fundSymbol = symbol;
      section.classList.remove("hidden");
      const f = data.fund || {};
      let a = data.analysis;
      let technicalError = data.technical_source_error || "";
      if (!a) {
        try {
          a = await api(`/api/funds/${encodeURIComponent(symbol)}/technical?horizon=${encodeURIComponent(requestedHorizon)}`);
          data.analysis = a;
          data.purchase_assessment = a.purchase_assessment;
          technicalError = "";
        } catch (error) {
          technicalError = error?.message || "دریافت دادهٔ نمودار تکنیکال ره‌آورد ناموفق بود.";
        }
      }
      const id = f.rahavard_asset_id || f.symbol;
      if (a?.technical_score != null) {
        const listedFund = state.funds.find((item) => item.fund_key === symbol || item.symbol === symbol || String(item.rahavard_asset_id || "") === String(id));
        if (listedFund) {
          listedFund.technical_score = Number(a.technical_score);
          listedFund.data_coverage_pct = a.data_coverage_pct;
          listedFund.risk_score = a.risk_rank?.score;
          listedFund.score_change_5d = a.score_change_5d;
          listedFund.score_change_20d = a.score_change_20d;
          listedFund.medium_term_exit_price = a.medium_term_exit_price;
          listedFund.purchase_assessment = data.purchase_assessment;
          listedFund.buy_suitability_rank = data.purchase_assessment?.rank ?? null;
          state.funds = sortedFundItems(state.funds);
          renderFundTable(state.funds);
        }
      }
      const displaySymbol = f.display_symbol || `شناسه ره‌آورد ${id}`;
      const props = [
        ["شناسه ره‌آورد", id], ["نماد معاملاتی", f.display_symbol],
        ["نوع صندوق", a?.fund_type_label || f.category], ["مدیر", f.manager], ["متولی", f.custodian],
        ["قیمت پایانی (ریال)", f.market_price], ["NAV آماری (ریال)", f.nav],
        ["فاصله قیمت از NAV", f.nav_premium_pct == null ? null : `${num(f.nav_premium_pct)}٪`],
        ["ارزش معامله (ریال)", f.value], ["حجم معامله", f.volume],
        ["زمان داده", f.data_timestamp]
      ];
      const propsHtml = props.map(([label, value]) => {
        const rendered = typeof value === "number" ? money(value) : text(value);
        return `<div class="property"><span>${label}</span><b>${esc(rendered)}</b></div>`;
      }).join("");
      const technicalHtml = a ? analysisHtml(a) : `<div class="empty-state compact"><b>دادهٔ تحلیل نمودار ره‌آورد دریافت نشد</b><small>${esc(technicalError || "دریافت کندل‌های نمودار ناموفق بود. لطفاً کمی بعد دوباره تلاش کنید.")}</small></div>`;
      section.innerHTML = `<div class="fund-detail-head"><div><span class="panel-kicker">نمایه صندوق · ${esc(displaySymbol)}</span><h2>${esc(f.name || displaySymbol)}</h2><p>فهرست، قیمت و NAV از ره‌آورد۳۶۵ · داده تا ${esc(formatDate(f.data_timestamp))}</p></div><button class="icon-button" data-close-fund aria-label="بستن">×</button></div><div class="fund-detail-body"><div><div class="fund-properties">${propsHtml}</div></div><div><h3>داده‌های تکمیلی</h3><p class="fund-chart-caption">کندل‌های نمودار ره‌آورد دریافت می‌شوند و مقدار اندیکاتورها داخل سامانه از روی آن‌ها محاسبه می‌شود.</p><div class="source-line">قیمت، NAV و کندل‌های تکنیکال: ره‌آورد۳۶۵ · ${nf.format(data.history?.length || 0)} مشاهده قیمت · ${nf.format(data.nav_history?.length || 0)} مشاهدهٔ NAV · محاسبهٔ اندیکاتورها: داخلی</div><a class="button button-quiet" href="/api/funds/${encodeURIComponent(symbol)}/history" target="_blank" rel="noopener">مشاهدهٔ دادهٔ خام قیمت و NAV</a></div></div><div class="fund-analysis-full"><h3>تحلیل تکنیکال از روی نمودار ره‌آورد</h3>${technicalHtml}</div>`;
      section.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      toast(`نمایه صندوق باز نشد: ${err.message}`, true);
    }
  }

  function renderPersonalWatchlist(items, totals = {}) {
    const body = $("#watchlist-items");
    state.watchlistTotals = totals;
    const sortMode = state.watchlistSortMode || "default";
    const sortedItems = [...items];
    if (sortMode === "exit") sortedItems.sort((a, b) => {
      const gap = (item) => item.near_exit_price != null && Number(item.price) > 0
        ? (Number(item.price) - Number(item.near_exit_price)) / Number(item.price) * 100
        : Number(item.distance_to_exit?.pct);
      const av = gap(a), bv = gap(b);
      return (Number.isFinite(av) ? av : Infinity) - (Number.isFinite(bv) ? bv : Infinity);
    });    if (sortMode === "score") sortedItems.sort((a, b) => {
      const av = Number(a.score_change_1d), bv = Number(b.score_change_1d);
      return (Number.isFinite(av) && av < 0 ? av : Infinity) - (Number.isFinite(bv) && bv < 0 ? bv : Infinity);
    });
    if (sortMode === "profit") sortedItems.sort((a, b) => {
      const av = Number(a.profit?.total), bv = Number(b.profit?.total);
      return (Number.isFinite(bv) ? bv : -Infinity) - (Number.isFinite(av) ? av : -Infinity);
    });
    const primaryExitLabel = state.investmentHorizon === "short" ? "EMA(10)" : "SMA(30)";
    const summary = $("#watchlist-summary-values");
    const pnlTone = totals.pnl == null ? "" : Number(totals.pnl) > 0 ? "positive" : Number(totals.pnl) < 0 ? "negative" : "neutral";
    const summaryValues = [
      ["ارزش پرتفوی", money(totals.market_value), ""],
      ["ارزش خرید", money(totals.cost_basis), ""],
      ["سود/زیان کل", money(totals.pnl), pnlTone],
      ["درصد سود/زیان کل", pct(totals.pnl_pct), pnlTone],
    ];
    if (summary) {
      summary.innerHTML = summaryValues.map(([label, value, tone]) => `<article class="watchlist-summary-card ${tone}"><span>${label}</span><b>${value}</b></article>`).join("");
    }
    if (!items.length) {
      body.innerHTML = `<div class="empty-state watchlist-empty"><span>◎</span><b>هنوز نمادی در دیده‌بان نیست</b></div>`;
      return;
    }
    const rows = sortedItems.map((item) => {
      const custom = Boolean(item.is_custom_symbol);
      const openAttrs = custom ? "disabled aria-disabled=\"true\"" : `data-watch-open="${esc(item.fund_key)}"`;
      const profit = item.profit || {};
      const profitTone = Number(profit.total) > 0 ? "positive" : Number(profit.total) < 0 ? "negative" : "";
      const priceTone = Number(item.daily_return) > 0 ? "positive" : Number(item.daily_return) < 0 ? "negative" : "";
      const scoreValue = item.technical_score == null ? null : Number(item.technical_score);
      const scoreTone = !Number.isFinite(scoreValue) ? "unknown" : scoreValue > 65 ? "positive" : scoreValue < 40 ? "negative" : "neutral";
      const scoreBand = !Number.isFinite(scoreValue) ? "نامشخص" : scoreValue < 40 ? "ضعیف" : scoreValue <= 65 ? "خنثی" : "قوی";
      const scoreDelta = item.score_change_1d == null ? null : Number(item.score_change_1d);
      const scoreDeltaHtml = Number.isFinite(scoreDelta) ? `<small class="watch-score-delta ${scoreDelta > 0 ? "positive" : scoreDelta < 0 ? "negative" : "neutral"}" title="تغییر امتیاز نسبت به روز معاملاتی قبل">${scoreDelta > 0 ? "↑" : scoreDelta < 0 ? "↓" : "→"} ${num(Math.abs(scoreDelta), 1)}</small>` : "";
      const familyScores = item.family_scores || {};
      const familyScore = (key) => familyScores[key]?.score == null ? null : Number(familyScores[key].score);
      const scoreParts = [["میانگین متحرک", familyScore("moving_averages")], ["نوسان‌گر", familyScore("oscillators")], ["روند/مومنتوم", familyScore("trend_momentum")], ["حمایت/مقاومت", familyScore("support_resistance")]].filter(([, value]) => Number.isFinite(value));
      const riskScore = item.risk_rank?.score == null ? null : Number(item.risk_rank.score);
      const scoreTooltip = [...scoreParts.map(([label, value]) => `${label}: ${num(value, 1)}`), riskScore == null ? "ریسک: ناموجود" : `ریسک: ${num(riskScore, 1)}`, "حجم در امتیاز فعلی وارد نمی‌شود"].join(" · ");
      const marketValue = item.price != null && item.units != null && Number.isFinite(Number(item.price)) && Number.isFinite(Number(item.units))
        ? Number(item.price) * Number(item.units) : null;
      const exitAverage = item.active_exit_average || (item.active_exit_horizon === "کوتاه‌مدت" ? "EMA(10)" : "SMA(30)");
      const currentPrice = Number(item.price);
      const activeExitPrice = Number(item.active_exit_price);
      const exitTone = !Number.isFinite(currentPrice) || currentPrice <= 0 || !Number.isFinite(activeExitPrice) || activeExitPrice <= 0
        ? ""
        : currentPrice <= activeExitPrice
          ? "negative"
          : (currentPrice - activeExitPrice) / activeExitPrice <= 0.05
            ? "warning"
            : "positive";
      const exitState = exitTone === "negative"
        ? "قیمت به زیر حد خروج رسیده"
        : exitTone === "warning"
          ? "قیمت تا ۵٪ بالاتر از حد خروج است"
          : exitTone === "positive"
            ? "قیمت بیش از ۵٪ بالاتر از حد خروج است"
            : "قیمت یا حد خروج در دسترس نیست";
      const indicators = item.watchlist_indicators || {};
      const metric = (key) => {
        const value = Number(indicators[key]);
        return indicators[key] == null || !Number.isFinite(value) ? null : value;
      };
      const rsi = metric("rsi");
      const mfi = metric("mfi");
      const stochRsi = metric("stoch_rsi");
      const adx = metric("adx");
      const macdLine = metric("macd_line");
      const macdSignal = metric("macd_signal");
      const ema20 = metric("ema20");
      const ema50 = metric("ema50");
      const nearestSupport = metric("nearest_support");
      const nearestResistance = metric("nearest_resistance");
      const positionUnits = Number(item.units) || 0;
      const profitPct = profit.pct == null ? null : Number(profit.pct);
      const exitConfirmed = positionUnits > 0 && Number.isFinite(Number(item.last_daily_close)) && Number.isFinite(activeExitPrice) && Number(item.last_daily_close) < activeExitPrice;
      const resistanceGapPct = Number.isFinite(nearestResistance) && currentPrice > 0
        ? (nearestResistance - currentPrice) / currentPrice * 100 : null;
      const profitTakingSignals = [
        rsi != null && rsi >= 70,
        mfi != null && mfi >= 80,
        stochRsi != null && stochRsi >= 0.8,
        macdLine != null && macdSignal != null && macdLine < macdSignal,
        resistanceGapPct != null && resistanceGapPct >= 0 && resistanceGapPct <= 3,
      ].filter(Boolean).length;
      let saleDecision;
      if (custom) saleDecision = { label: "داده کافی نیست", reason: "برای این نماد دادهٔ تحلیلی در دسترس نیست." };
      else if (positionUnits <= 0) saleDecision = { label: "موقعیتی ثبت نشده", reason: "برای سیو سود یا فروش، واحدی در این نماد ثبت نشده است." };
      else if (exitConfirmed) saleDecision = { label: "فروش / خروج", reason: "آخرین کندل روزانه زیر " + exitAverage + " بسته شده؛ حد خروج تأیید است." };
      else if (profitPct != null && profitPct > 0 && profitTakingSignals >= 2) saleDecision = { label: "سیو سود پله‌ای", reason: "سود باز است و " + num(profitTakingSignals, 0) + " نشانهٔ ضعف یا مقاومت دیده می‌شود؛ سیو سود مرحله‌ای را بررسی کن." };
      else if (profitPct != null && profitPct > 0 && profitTakingSignals === 1) saleDecision = { label: "سیو سود را زیر نظر بگیر", reason: "سود باز است، اما فقط یک نشانهٔ احتیاط دیده می‌شود؛ تأیید بیشتر لازم است." };
      else if (scoreValue != null && scoreValue < 40) saleDecision = { label: "کاهش ریسک", reason: "امتیاز تکنیکال زیر ۴۰ است؛ کاهش بخشی از موقعیت را بررسی کن." };
      else if (profitPct != null && profitPct > 0) saleDecision = { label: "فعلاً سیو سود لازم نیست", reason: "سود باز است، اما نشانه‌های هم‌زمان کافی برای سیو سود دیده نمی‌شود." };
      else saleDecision = { label: "فروش تأیید نشده", reason: "حد خروج با بسته‌شدن زیر " + exitAverage + " تأیید نشده است." };
      const stochMacdExplanation = stochRsi != null && stochRsi <= 0.2 && macdLine != null && macdSignal != null && macdLine < macdSignal
        ? "StochRSI در ناحیهٔ خرید است، اما MACD زیر خط سیگنال مانده؛ برگشت هنوز تأیید نشده است."
        : "";
      const chip = (label, tone, title = "") => `<span class="watch-indicator-chip ${tone}"${title ? ` title="${esc(title)}"` : ""}>${esc(label)}</span>`;
      const indicatorChips = [];
      if (rsi != null) indicatorChips.push(chip(`RSI ${num(rsi, 1)}`, rsi >= 70 ? "negative" : rsi <= 30 ? "positive" : rsi >= 50 ? "positive" : "neutral"));
      if (mfi != null) indicatorChips.push(chip(`MFI ${num(mfi, 1)}`, mfi >= 80 ? "negative" : mfi <= 20 ? "positive" : mfi >= 50 ? "positive" : "neutral"));
      if (stochRsi != null) indicatorChips.push(chip(`StochRSI ${num(stochRsi, 2)}`, stochRsi <= 0.2 ? "positive" : stochRsi >= 0.8 ? "negative" : "neutral", stochMacdExplanation));
      if (macdLine != null && macdSignal != null) indicatorChips.push(chip(`MACD ${macdLine >= macdSignal ? "بالای سیگنال" : "زیر سیگنال"}`, macdLine >= macdSignal ? "positive" : "negative"));
      if (adx != null) indicatorChips.push(chip(`ADX ${num(adx, 1)} · قدرت ${adx >= 25 ? "بالا" : adx >= 20 ? "متوسط" : "پایین"}`, "neutral"));
      if (ema20 != null && Number.isFinite(currentPrice) && currentPrice > 0) indicatorChips.push(chip(currentPrice >= ema20 ? "بالای EMA20" : "زیر EMA20", currentPrice >= ema20 ? "positive" : "negative"));
      if (ema50 != null && Number.isFinite(currentPrice) && currentPrice > 0) indicatorChips.push(chip(currentPrice >= ema50 ? "بالای EMA50" : "زیر EMA50", currentPrice >= ema50 ? "positive" : "negative"));
      const supportForExit = item.near_exit_price ?? nearestSupport;
      const nearExitGapPct = supportForExit != null && Number.isFinite(currentPrice) && currentPrice > 0
        ? (currentPrice - Number(supportForExit)) / currentPrice * 100 : null;
      const nearExitBroken = item.near_exit_confirmed === true;
      const nearExitWarning = nearExitBroken || (nearExitGapPct != null && nearExitGapPct >= 0 && nearExitGapPct < 2);
      const exitDisplayTone = nearExitBroken ? "negative" : nearExitWarning ? "warning" : exitTone;
      const nearExitDistanceText = nearExitGapPct == null ? "" : nearExitGapPct >= 0
        ? `−${num(nearExitGapPct, 1)}٪` : `زیر سطح ${num(Math.abs(nearExitGapPct), 1)}٪`;
      const levelNotes = [nearestResistance != null ? `مقاومت نزدیک: ${money(nearestResistance)}` : null].filter(Boolean);
      const holding = item.holding_decision || {};
      const basePositionLabel = holding.label || "داده کافی نیست";
      let positionLabel = basePositionLabel;
      if (saleDecision.label === "فروش / خروج") positionLabel = saleDecision.label;
      else if (saleDecision.label === "سیو سود پله‌ای") positionLabel = basePositionLabel + " · سیو سود پله‌ای";
      else if (saleDecision.label === "سیو سود را زیر نظر بگیر") positionLabel = basePositionLabel + " · بررسی سیو سود";
      if (nearExitWarning && saleDecision.label !== "فروش / خروج") positionLabel = nearExitBroken ? "هشدار · حمایت شکسته" : "هشدار · نزدیک حمایت";
      let adding = item.add_position_decision || {};
      if (nearExitWarning) adding = { label: nearExitBroken ? "خیر · حمایت شکسته" : "صبر · نزدیک حمایت", reason: nearExitBroken ? "کندل روزانه زیر حمایت نزدیک بسته شده؛ تا بازپس‌گیری سطح، حجم اضافه نکن." : `فاصلهٔ قیمت تا حمایت نزدیک ${num(nearExitGapPct, 1)}٪ است؛ تا روشن‌شدن واکنش قیمت، حجم اضافه نکن.` };
      const showSaleReason = ["فروش / خروج", "سیو سود پله‌ای", "سیو سود را زیر نظر بگیر", "کاهش ریسک"].includes(saleDecision.label);
      const detailLines = [holding.reason, adding.reason, stochMacdExplanation, ...levelNotes, showSaleReason ? saleDecision.reason : null].filter(Boolean);
      const detailsHtml = detailLines.map((line) => `<p>${esc(line)}</p>`).join("");
      const watchAnalysis = '<div class="watch-analysis-summary"><div class="watch-analysis-actions"><span>موقعیت: <b class="' + (nearExitWarning ? 'warning' : '') + '">' + esc(positionLabel) + '</b></span><span>افزایش حجم: <b>' + esc(adding.label || "صبر") + '</b></span></div><div class="watch-indicator-chips">' + (indicatorChips.join("") || `<span class="watch-analysis-empty">${esc(item.technical_error || "دادهٔ اندیکاتورهای اصلی در دسترس نیست.")}</span>`) + '</div><details class="watch-analysis-details"><summary>جزئیات تحلیل</summary><div class="watch-analysis-details-body">' + (detailsHtml || '<p>جزئیات بیشتری برای این نماد در دسترس نیست.</p>') + '</div></details></div>';      const priceFresh = item.price != null && item.price_is_cached === false;
      const freshnessLabel = priceFresh ? "داده تازه" : "داده کهنه یا ناموجود";
      return `<tr class="${nearExitBroken ? "watchlist-row-danger" : nearExitWarning ? "watchlist-row-warning" : ""}">
        <td data-label="نماد"><div class="watchlist-symbol-cell"><button class="watch-fund-open${custom ? " watch-fund-open-unavailable" : ""}" type="button" ${openAttrs} aria-label="${custom ? "دادهٔ تحلیلی موجود نیست" : "مشاهده تحلیل"} ${esc(item.name)}"><i class="data-freshness-dot ${priceFresh ? "fresh" : "stale"}" role="img" aria-label="${freshnessLabel}" title="${freshnessLabel}"></i><strong>${esc(item.name || item.symbol || "—")}</strong></button></div></td>
        <td data-label="تعداد"><span class="watch-cell-primary">${num(item.units, 0)}</span></td>
        <td data-label="قیمت سربه‌سر"><span class="watch-cell-primary">${money(item.break_even_price)}</span></td>
        <td data-label="ارزش فعلی"><span class="watch-cell-primary">${money(marketValue)}</span></td>
        <td data-label="آخرین قیمت"><span class="watch-cell-primary">${money(item.price)}</span><small class="watch-cell-secondary ${priceTone}">${item.daily_return == null ? "—" : pct(item.daily_return)}</small></td>
        <td data-label="سود/زیان فعلی"><span class="watch-cell-primary ${profitTone}">${profit.total == null ? "—" : money(profit.total)}</span><small class="watch-cell-secondary ${profitTone}">${profit.pct == null ? "" : `(${pct(profit.pct)})`}</small></td>
        <td data-label="حد خروج" title="حد اصلی با بسته‌شدن کندل روزانه زیر ${esc(exitAverage)} تأیید می‌شود"><span class="watch-cell-primary ${exitDisplayTone}">${money(item.active_exit_price)}</span>${supportForExit != null ? `<small class="watch-near-exit ${nearExitBroken ? "negative" : nearExitWarning ? "warning" : ""}">نزدیک: ${money(supportForExit)} (${nearExitDistanceText})</small>` : ""}</td>
        <td data-label="امتیاز نماد"><span class="watch-score ${scoreTone}" title="${esc(scoreTooltip || item.technical_error || "امتیاز بر پایهٔ محاسبهٔ اندیکاتورها از نمودار روزانهٔ ره‌آورد")}">${scoreValue == null || !Number.isFinite(scoreValue) ? "—" : `${num(scoreValue, 0)}٪`}</span><small class="watch-score-band ${scoreTone}">${scoreBand}</small>${scoreDeltaHtml}</td><td data-label="تحلیل خلاصه">${watchAnalysis}</td>
      </tr>`;
    }).join("");
    body.innerHTML = `<div class="watchlist-sort-toolbar"><div><label for="watchlist-sort">مرتب‌سازی</label><select id="watchlist-sort"><option value="default" ${sortMode === "default" ? "selected" : ""}>ترتیب پیش‌فرض</option><option value="exit" ${sortMode === "exit" ? "selected" : ""}>نزدیک‌ترین به حد خروج</option><option value="score" ${sortMode === "score" ? "selected" : ""}>بیشترین افت امتیاز</option><option value="profit" ${sortMode === "profit" ? "selected" : ""}>بیشترین سود</option></select></div><small>حد خروج اصلی (${primaryExitLabel}) با بسته‌شدن کندل روزانه زیر آن تأیید می‌شود؛ حمایت نزدیک در فاصلهٔ کمتر از ۲٪ هشدار دارد.</small></div><table class="watchlist-table"><thead><tr><th scope="col">نماد <small>(${nf.format(items.length)})</small></th><th scope="col">تعداد</th><th scope="col">قیمت سربه‌سر</th><th scope="col">ارزش فعلی</th><th scope="col">آخرین قیمت</th><th scope="col">سود/زیان فعلی</th><th scope="col">حد خروج</th><th scope="col">امتیاز نماد</th><th scope="col">تحلیل خلاصه</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  async function fillVisibleFundNavs(generation = fundNavGeneration) {
    if (fundNavFillRunning || state.currentView !== "funds") return;
    const pending = [...new Set(state.funds
      .filter((fund) => !(Number(fund.nav) > 0) || fund.nav_is_cached === true)
      .map((fund) => String(fund.fund_key || fund.symbol || ""))
      .filter((key) => key && !fundNavAttemptedKeys.has(key)))];
    if (!pending.length) return;

    fundNavFillRunning = true;
    try {
      for (let offset = 0; offset < pending.length; offset += 8) {
        const batch = pending.slice(offset, offset + 8);
        batch.forEach((key) => fundNavAttemptedKeys.add(key));
        let response;
        try {
          response = await api("/api/funds/nav/batch", {
            method: "POST",
            body: JSON.stringify({ fund_keys: batch })
          });
        } catch {
          continue;
        }
        for (const result of response.items || []) {
          const key = String(result.fund_key || "");
          if (!key) continue;
          const navData = {
            nav: result.nav,
            nav_timestamp: result.nav_timestamp,
            nav_is_cached: result.nav_is_cached
          };
          fundNavValueCache.set(key, navData);
          const listed = state.funds.find((fund) => String(fund.fund_key || fund.symbol || "") === key);
          if (listed) Object.assign(listed, navData, { nav_premium_pct: result.nav_premium_pct });
        }
        if (generation === fundNavGeneration && state.currentView === "funds") {
          state.funds = sortedFundItems(state.funds);
          renderFundTable(state.funds);
        }
      }
    } finally {
      fundNavFillRunning = false;
      if (state.currentView === "funds" && generation !== fundNavGeneration) {
        queueMicrotask(() => void fillVisibleFundNavs(fundNavGeneration));
      }
    }
  }
  async function loadWatchlist() {
    const requestedHorizon = state.investmentHorizon;
    const body = $("#watchlist-items");
    if (!state.watchlist.length) body.innerHTML = `<div class="empty-state compact watchlist-empty"><b>در حال دریافت قیمت و تحلیل ره‌آورد…</b></div>`;
    try {
      const data = await api("/api/watchlist?skip_technical=true");
      if (requestedHorizon !== state.investmentHorizon) return;
      state.watchlist = data.items || [];
      renderPersonalWatchlist(state.watchlist, data.totals || {});
      const technicalItems = state.watchlist.filter((item) => !item.is_custom_symbol && item.fund_key);
      for (let offset = 0; offset < technicalItems.length; offset += 4) {
        if (requestedHorizon !== state.investmentHorizon) return;
        const batch = technicalItems.slice(offset, offset + 4);
        try {
          const scores = await api("/api/funds/scores/batch", {
            method: "POST",
            body: JSON.stringify({ fund_keys: batch.map((item) => String(item.fund_key)) })
          });
          const resultByKey = new Map((scores.items || []).map((result) => [String(result.fund_key), result]));
          for (const item of batch) {
            const result = resultByKey.get(String(item.fund_key));
            const analysis = result?.analysis;
            if (!analysis) {
              item.technical_error = result?.error || "تحلیل تکنیکال نمودار ره‌آورد آماده نشد.";
              continue;
            }
            item.technical_error = "";
            item.technical_score = result.technical_score;
            item.short_term_exit_price = analysis.short_term_exit_price;
            item.medium_term_exit_price = analysis.medium_term_exit_price;
            item.active_exit_price = state.investmentHorizon === "short" ? analysis.short_term_exit_price : analysis.medium_term_exit_price;
            item.active_exit_average = state.investmentHorizon === "short" ? "EMA(10)" : "SMA(30)";
            item.active_exit_horizon = analysis.investment_horizon_label || horizonLabel();
            item.investment_horizon_label = analysis.investment_horizon_label || horizonLabel();
            item.last_daily_close = analysis.price;
            item.last_daily_close_timestamp = analysis.data_timestamp;

            item.technical_data_timestamp = analysis.data_timestamp;
            item.purchase_assessment = result.purchase_assessment;
            item.watchlist_indicators = analysis.watchlist_indicators || {};
            item.near_exit_price = item.watchlist_indicators.nearest_support;
            item.near_exit_confirmed = item.near_exit_price != null && Number(analysis.price) < Number(item.near_exit_price);
            item.family_scores = analysis.family_scores || {};
            item.risk_rank = analysis.risk_rank || {};
            item.score_change_1d = result.score_change_1d ?? analysis.score_change_1d;
            item.volume_ratio = result.volume_ratio;
            const quoteDayChange = item.daily_return == null ? null : Number(item.daily_return);
            item.volume_pressure = Number.isFinite(Number(item.volume_ratio)) && Number(item.volume_ratio) >= 1 && Number.isFinite(quoteDayChange) && quoteDayChange < -0.5
              ? "selling"
              : Number.isFinite(Number(item.volume_ratio)) && Number(item.volume_ratio) >= 1 && Number.isFinite(quoteDayChange) && quoteDayChange > 0.5
                ? "buying" : null;

            const dailyClose = analysis.price == null ? null : Number(analysis.price);
            const activeExit = item.active_exit_price == null ? null : Number(item.active_exit_price);
            const technicalScore = item.technical_score == null ? null : Number(item.technical_score);
            const units = item.units == null ? 0 : Number(item.units);
            const hasCoreData = Number.isFinite(activeExit) && activeExit > 0 && Number.isFinite(technicalScore);
            const exitConfirmed = dailyClose != null && Number.isFinite(dailyClose) && Number.isFinite(activeExit) && dailyClose < activeExit;
            if (!hasCoreData) {
              item.holding_decision = { label: "داده کافی نیست", tone: "unknown", reason: "برای تعیین نگهداری یا خروج، قیمت و تحلیل کامل لازم است." };
              item.add_position_decision = { label: "فعلاً اضافه نکن", tone: "neutral", reason: "تا کامل‌شدن داده‌ها برای افزایش حجم صبر کن." };
            } else if (dailyClose == null || !Number.isFinite(dailyClose)) {
              item.holding_decision = units <= 0
                ? { label: "موقعیتی ثبت نشده", tone: "neutral", reason: "برای این نماد تعداد واحدی ثبت نشده است." }
                : { label: "در انتظار کندل روزانه", tone: "neutral", reason: "قیمت پایانی روزانه برای تأیید حد خروج در دسترس نیست." };
              item.add_position_decision = { label: "صبر تا تأیید روزانه", tone: "neutral", reason: "تا دریافت قیمت پایانی روزانه، شکست میانگین و شرایط افزودن حجم را تأیید نمی‌کنم." };
            } else if (exitConfirmed) {
              item.holding_decision = units <= 0
                ? { label: "موقعیتی ثبت نشده", tone: "neutral", reason: "برای این نماد تعداد واحدی ثبت نشده است." }
                : { label: "فروش / کاهش", tone: "negative", reason: "آخرین کندل روزانه زیر " + item.active_exit_average + " بسته شده و حد خروج تأیید شده است." };
              item.add_position_decision = { label: "خیر · حد خروج تأیید شد", tone: "negative", reason: "تا زمانی که کندل روزانه بالای " + item.active_exit_average + " تثبیت نشده، حجم اضافه نکن." };
            } else if (units <= 0) {
              item.holding_decision = { label: "موقعیتی ثبت نشده", tone: "neutral", reason: "برای این نماد تعداد واحدی ثبت نشده است." };
              item.add_position_decision = result.purchase_assessment?.status === "suitable"
                ? { label: "بله · پله‌ای", tone: "positive", reason: result.purchase_assessment.reason || "شرایط ورود تأیید شده؛ مرحله‌ای اضافه کن." }
                : result.purchase_assessment?.status === "unsuitable"
                  ? { label: "خیر · فعلاً", tone: "negative", reason: result.purchase_assessment.reason || "شرایط ورود مناسب نیست." }
                  : { label: result.purchase_assessment?.label || "صبر · داده کافی نیست", tone: "neutral", reason: result.purchase_assessment?.reason || "برای افزایش حجم تا کامل‌شدن شرایط ورود صبر کن." };
            } else if (technicalScore < 40) {
              item.holding_decision = { label: "کاهش ریسک", tone: "negative", reason: "امتیاز تکنیکال ضعیف است؛ نگهداری کامل ریسک بالاتری دارد." };
              item.add_position_decision = { label: "خیر · فعلاً", tone: "negative", reason: "امتیاز تکنیکال ضعیف است." };
            } else {
              item.holding_decision = { label: "نگهداری", tone: "positive", reason: "آخرین کندل روزانه بالای " + item.active_exit_average + " بسته شده؛ حد خروج فقط با بسته‌شدن روزانه زیر آن فعال می‌شود." };
              item.add_position_decision = result.purchase_assessment?.status === "suitable"
                ? { label: "بله · پله‌ای", tone: "positive", reason: result.purchase_assessment.reason || "شرایط ورود تأیید شده؛ مرحله‌ای اضافه کن." }
                : result.purchase_assessment?.status === "unsuitable"
                  ? { label: "خیر · فعلاً", tone: "negative", reason: result.purchase_assessment.reason || "شرایط ورود مناسب نیست." }
                  : { label: result.purchase_assessment?.label || "صبر · داده کافی نیست", tone: "neutral", reason: result.purchase_assessment?.reason || "برای افزایش حجم تا کامل‌شدن شرایط ورود صبر کن." };
            }
            item.distance_to_exit = item.price != null && item.active_exit_price != null
              ? { value: Number(item.price) - Number(item.active_exit_price), pct: (Number(item.price) - Number(item.active_exit_price)) / Number(item.price) * 100 }
              : null;
            if (item.volume_pressure === "selling") {
              item.add_position_decision = { label: "خیر · حجم همراه با فروش", tone: "negative", reason: `حجم معاملات ${item.volume_ratio == null ? "بالاست" : `حدود ${num(item.volume_ratio, 2)} برابر میانگین است`} و کندل روزانه نزولی بسته شده؛ افزایش حجم را فشار فروش در نظر بگیر.` };
            } else if (item.volume_pressure === "buying" && result.purchase_assessment?.status === "suitable") {
              item.add_position_decision = { label: "بله · فشار خرید", tone: "positive", reason: `حجم معاملات ${item.volume_ratio == null ? "بالاست" : `حدود ${num(item.volume_ratio, 2)} برابر میانگین است`} و کندل روزانه صعودی بسته شده؛ جهت حجم و قیمت همسو است. ورود را پله‌ای انجام بده.` };
            }
          }
          renderPersonalWatchlist(state.watchlist, data.totals || {});
        } catch (error) {
          for (const item of batch) item.technical_error ||= error?.message || "محاسبهٔ امتیاز تکنیکال ناموفق بود.";
          renderPersonalWatchlist(state.watchlist, data.totals || {});
        }
      }
    } catch (err) {
      body.innerHTML = `<div class="empty-state watchlist-empty"><b>دیده‌بان بارگیری نشد</b><small>${esc(err.message)}</small></div>`;
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
      node.setAttribute("aria-expanded", "false");
      const hint = $(".analysis-toggle-hint", node);
      if (hint) hint.textContent = "\u0628\u0631\u0627\u06cc \u0645\u0634\u0627\u0647\u062f\u0647 \u062a\u062d\u0644\u06cc\u0644 \u0639\u062f\u062f\u06cc \u06a9\u0644\u06cc\u06a9 \u06a9\u0646\u06cc\u062f \u2190";
    });
    if (shouldOpen) {
      panel.classList.remove("hidden");
      const trigger = $("[data-analysis-toggle=\"" + key + "\"]");
      trigger?.classList.add("is-open");
      trigger?.setAttribute("aria-expanded", "true");
      const hint = trigger ? $(".analysis-toggle-hint", trigger) : null;
      if (hint) hint.textContent = "\u0628\u0633\u062a\u0646 \u062a\u062d\u0644\u06cc\u0644 \u2191";
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  async function loadAdmin() {
    try {
      const data = await api("/api/admin");
      const count = data.health.counts || {};
      const statItems = [
        ["prices", "نقاط قیمت", "داده‌های بازار", "◈"],
        ["funds", "صندوق‌ها", "نمادهای قابل معامله", "▤"],
        ["alerts", "هشدارها", "شرایط فعال", "◉"],
      ];
      $("#admin-stats").innerHTML = statItems.map(([key, label, caption, icon]) => `<article class="admin-stat-card admin-stat-${key}"><span class="admin-stat-icon">${icon}</span><div class="admin-stat-copy"><span>${label}</span><small>${caption}</small><b>${nf.format(count[key] || 0)}</b></div></article>`).join("");

      const sourceClass = (status) => status === "connected" ? "connected" : status === "failed" ? "failed" : "pending";
      $("#admin-sources").innerHTML = data.sources.length ? data.sources.map((s) => {
        const detail = s.error || (s.last_data_timestamp ? `آخرین داده: ${formatDate(s.last_data_timestamp)}` : "در انتظار نخستین همگام‌سازی");
        return `<article class="admin-source-card ${sourceClass(s.status)}"><div class="admin-source-head"><span class="admin-source-dot"></span><div><strong>${esc(s.label)}</strong><small>${esc(s.name)}</small></div><b>${esc(statusText(s.status))}</b></div><div class="admin-source-meta"><span title="${esc(s.error || s.source_url || "")}">${esc(detail)}</span>${s.latency_ms != null ? `<small>${nf.format(s.latency_ms)} ms</small>` : ""}</div></article>`;
      }).join("") : `<div class="empty-state compact"><b>منبع داده‌ای ثبت نشده</b><small>پس از افزودن منبع، وضعیت اتصال اینجا نمایش داده می‌شود.</small></div>`;

      const logs = (data.recent_logs || []).slice(0, 8);
      $("#admin-logs").innerHTML = logs.length ? logs.map((l) => {
        const ok = l.status === "success";
        return `<article class="admin-log-card"><time>${esc(formatDate(l.started_at))}</time><div class="admin-log-body"><div class="admin-log-head"><strong>${esc(l.source)}</strong><span class="admin-log-status ${ok ? "success" : "failed"}">${ok ? "موفق" : "ناموفق"}</span></div><p>${esc(l.message || "همگام‌سازی انجام شد")}</p><small>${nf.format(l.records || 0)} ردیف داده</small></div></article>`;
      }).join("") : `<div class="empty-state compact"><b>گزارشی ثبت نشده</b><small>پس از همگام‌سازی، فعالیت منابع ثبت می‌شود.</small></div>`;
    } catch (err) { toast(`وضعیت سامانه خوانده نشد: ${err.message}`, true); }
  }

  async function loadSettings() {
    try {
      const s = await api("/api/settings");
      $("#settings-theme").value = s.theme || "dark";
      const intervalSelect = $("#settings-refresh-interval");
      const intervalValue = String(s.data_update_interval);
      scheduleWatchlistRefresh(s.data_update_interval);
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

  function scheduleWatchlistRefresh(intervalSeconds = state.watchlistRefreshSeconds) {
    const seconds = Math.max(60, Number(intervalSeconds) || 900);
    state.watchlistRefreshSeconds = seconds;
    if (state.watchlistRefreshTimer) clearInterval(state.watchlistRefreshTimer);
    state.watchlistRefreshTimer = setInterval(() => {
      if (state.currentView === "watchlist" && document.visibilityState === "visible") loadWatchlist();
    }, seconds * 1000);
  }

  async function openView(name) {
    if (!$("#view-" + name)) return;
    state.currentView = name;
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    const title = ({ overview: "داشبورد", funds: "صندوق‌ها", watchlist: "دیده‌بان", settings: "تنظیمات", admin: "وضعیت سامانه" })[name] || "داشبورد";
    $("#crumb-current").textContent = title;
    if (name === "funds") await loadFunds({ forceNav: true });
    if (name === "watchlist") await loadWatchlist();
    if (name === "admin") await loadAdmin();
    if (name === "settings") await loadSettings();
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
      if (state.currentView === "funds") await loadFunds({ forceNav: true });
      if (state.currentView === "watchlist") await loadWatchlist();
    } catch (err) { toast(`همگام‌سازی کامل نشد: ${err.message}`, true); }
    finally { buttons.forEach((b) => { b.disabled = false; b.classList.remove("spinning"); }); }
  }

  $$(".nav-item").forEach((button) => button.addEventListener("click", () => openView(button.dataset.view)));
  $$(".investment-horizon-select").forEach((select) => {
    select.value = state.investmentHorizon;
    select.addEventListener("change", (event) => changeInvestmentHorizon(event.target.value));
  });
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
      scheduleWatchlistRefresh(Number(value));
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
  $("#watchlist-items").addEventListener("click", async (event) => {
    const open = event.target.closest("[data-watch-open]");
    if (!open) return;
    await openView("funds");
    await showFund(open.dataset.watchOpen);
  });
  $("#watchlist-items").addEventListener("change", (event) => {
    if (event.target.id !== "watchlist-sort") return;
    state.watchlistSortMode = event.target.value;
    renderPersonalWatchlist(state.watchlist, state.watchlistTotals || {});
  });
  $("#watchlist-refresh").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.classList.add("spinning");
    try { await loadWatchlist(); }
    finally { button.disabled = false; button.classList.remove("spinning"); }
  });
  $("#fund-table").addEventListener("click", (event) => {
    if (event.target.closest("[data-clear-fund-filters]")) {
      const search = $("#fund-search");
      const category = $("#fund-category");
      if (search) search.value = "";
      if (category) category.value = "";
      loadFunds();
      return;
    }
    const button = event.target.closest("[data-fund]");
    if (button) showFund(button.dataset.fund);
  });
  $("#fund-mobile-score-sort").addEventListener("change", (event) => {
    const sortKeyByOption = {
      score_desc: ["technical_score", -1], score_asc: ["technical_score", 1],
      buy_suitability_rank: ["buy_suitability_rank", -1],
      type_asc: ["fund_type_label", 1], type_desc: ["fund_type_label", -1],
      monthly_return: ["monthly_return", -1], three_month_return: ["three_month_return", -1],
      six_month_return: ["six_month_return", -1], one_year_return: ["one_year_return", -1],
      nav_premium_pct: ["nav_premium_pct", -1], market_price: ["market_price", -1],
      data_timestamp: ["data_timestamp", -1],
    };
    const selected = sortKeyByOption[event.target.value];
    [fundSortState.key, fundSortState.direction] = selected || ["data_timestamp", -1];
    state.funds = sortedFundItems(state.funds);
    renderFundTable(state.funds);
  });

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
  $("#fund-detail").addEventListener("click", (event) => { if (event.target.closest("[data-close-fund]")) { $("#fund-detail").classList.add("hidden"); delete $("#fund-detail").dataset.fundSymbol; } });
  $(".market-strip").addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-analysis-toggle]");
    if (trigger) toggleMarketAnalysis(trigger.dataset.analysisToggle);
  });
  $(".market-strip").addEventListener("keydown", (event) => {
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
 scheduleWatchlistRefresh();
 document.addEventListener("visibilitychange", () => {
   if (!document.hidden && state.currentView === "watchlist") loadWatchlist();
 });
 localDateClock(); setInterval(localDateClock, 30_000);
  installEnglishDigits();
  syncInvestmentHorizonControl();
  api("/api/settings").then((s) => document.body.classList.toggle("light-mode", s.theme === "light")).catch(() => {});
  loadOverview();
})();
