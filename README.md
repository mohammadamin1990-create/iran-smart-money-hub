---
title: Iran Smart Money Hub
emoji: 📈
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# مرکز ابری دوطرفه پول هوشمند و سیگنال دینامیک بورس ایران (متصل به بله)

بسته یکپارچه ابری شامل:
1. **موتور تحلیل کمی، پول هوشمند و رادار فاندبیس (`src/`)**
2. **موتور سیگنال ۳۰ دقیقه‌ای ورود و خروج و حد ضرر متحرک (`dynamic_daemon/`)**
3. **چت‌بات دوطرفه تعاملی بله + مغز مکالمه Gemini 3.8 Flash (`cloud_hub/` + `KNOWLEDGE_BASE.md`)**

تمام کلیدهای محرمانه (`BALE_BOT_TOKEN`، `BALE_CHAT_ID`، `GEMINI_API_KEY`) صرفاً از طریق متغیرهای محیطی امن سرور (Secrets) خوانده می‌شوند.
