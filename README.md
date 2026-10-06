# نگاه بازار | Iran Market Lens

داشبورد فارسی برای پایش طلا، دلار تتر، صندوق‌های قابل معامله و تحلیل تکنیکال بر پایه داده‌های ره‌آورد۳۶۵ و تبدیل دلار از تتر/تبدیل.

**نسخهٔ آنلاین چابکان:** https://docker-92phyf.chbkn.dev

**نسخهٔ آنلاین Vercel:** https://iran-market-lens.vercel.app

**نسخهٔ پشتیبان Render:** https://iran-market-lens.onrender.com

**مخزن GitHub:** https://github.com/jonathanpierceate-cloud/iran-market-lens

## امکانات

- فهرست و جست‌وجوی صندوق‌ها از ره‌آورد۳۶۵
- نمودار قیمت، NAV، بازدهی و وضعیت داده
- اندیکاتورهای ره‌آورد۳۶۵ با مقدار، محدوده راهنما و تفسیر فارسی
- تحلیل روند، حمایت و مقاومت و جمع‌بندی خرید/نگهداری/فروش
- دیده‌بان شخصی با قیمت سر‌به‌سر و تعداد واحد
- قیمت طلا و دلار تتر و ذخیره تاریخچه در SQLite
- خروجی CSV، Excel و JSON
- رابط راست‌چین و واکنش‌گرا برای دسکتاپ و موبایل

## اجرای محلی

### Windows

```powershell
./start.bat
```

یا میانبر `نگاه بازار` روی دسکتاپ را اجرا کنید.

### Linux / macOS

```sh
chmod +x start.sh
./start.sh
```

سپس مرورگر را روی `http://127.0.0.1:8000/` باز کنید.

## اجرای Docker

```sh
docker compose up --build
```

سپس `http://127.0.0.1:8000/` را باز کنید.

Dockerfile به‌صورت خودکار از متغیر `PORT` استفاده می‌کند؛ بنابراین برای میزبان‌هایی مثل Render مناسب است.

## انتشار عمومی با GitHub، Docker و چابکان

این مخزن شامل `Dockerfile`، `render.yaml` و workflow ساخت Docker است. سرویس چابکان با Dockerfile ریشه، مخزن عمومی GitHub را clone می‌کند و با Uvicorn روی پورت 8000 اجرا می‌شود.

برای به‌روزرسانی نسخهٔ چابکان، ابتدا تغییرات را به شاخهٔ `main` push کنید و سپس از پنل چابکان گزینهٔ «استقرار مجدد» را بزنید تا Dockerfile دوباره ساخته شود.

1. مخزن را در GitHub روی شاخه `main` قرار دهید.
2. در Render گزینه New > Blueprint را بزنید.
3. مخزن GitHub را انتخاب کنید.
4. Render از `render.yaml` سرویس Docker را می‌سازد و یک آدرس `onrender.com` می‌دهد.

نسخه رایگان Render برای آزمایش مناسب است، اما فایل SQLite در آن پایدار نیست و ممکن است با restart یا deploy دوباره ساخته شود. برای نگهداری دائمی دیده‌بان و تاریخچه باید از دیسک پایدار پولی یا پایگاه‌داده بیرونی استفاده شود.

## انتشار روی Vercel

Vercel از entrypoint موجود در `api/index.py` استفاده می‌کند و هر push شاخهٔ `main` را خودکار منتشر می‌کند. روی Vercel، اولین نمونهٔ سرد قبل از پاسخ یک واکشی زنده انجام می‌دهد؛ سپس workflow گیت‌هاب در `.github/workflows/refresh-vercel.yml` هر ۱۵ دقیقه endpoint تازه‌سازی را صدا می‌زند. چون فایل‌سیستم توابع Vercel موقت است، دیده‌بان و تاریخچهٔ ماندگار باید روی نسخهٔ چابکان یا یک پایگاه‌دادهٔ بیرونی نگهداری شوند.

## تنظیمات محیطی

نمونه تنظیمات در `.env.example` قرار دارد. مهم‌ترین متغیرها:

```dotenv
DATA_DIR=./data
DATABASE_PATH=./data/market.db
DATA_UPDATE_INTERVAL=900
HTTP_TIMEOUT_SECONDS=15
MAX_STALE_HOURS=36
```

## API

- `GET /api/health`
- `GET /api/funds?search=&category=&sort=`
- `GET /api/funds/{symbol}/analysis`
- `GET /api/watchlist`
- `POST /api/refresh`
- `GET /docs`
