# خطة سبرينت 2 - فريق بايثون (Python Core Service) 

**المشروع:** Levora  
**التاريخ:** 25 أغسطس 2026  
**الإصدار:** 2.0 (المتوافق مع القرارات المعمارية النهائية)  
**الغرض:** توفير خطة عمل تفصيلية لفريق بايثون لسبرينت 2، مع التركيز على بناء الهيكل الأساسي للخدمة، وتطبيق بنية `infrastructure` الموحدة، وبناء نظام جلب البيانات من المصادر التي توفر API.

---

## 1. ملخص التغييرات المعمارية المؤثرة على هذا السبرينت

بناءً على القرارات المعمارية النهائية (المؤرخة 25 أغسطس 2026)، تم اعتماد النموذج التالي للتفاعل بين الخدمات:

| العنصر | القرار النهائي |
|--------|---------------|
| **جدول المصادر التقني** | موجود في قاعدة بيانات بايثون، يحتوي على جميع التفاصيل التقنية (endpoint، pagination، field mapping). |
| **جدول المصادر المعتمدة** | موجود في قاعدة البيانات الرئيسية، يحتوي فقط على `source_id` (للربط) و `is_approved`. |
| **الجدولة** | تبقى في الخدمة الرئيسية، والتي ترسل قائمة معرفات المصادر المعتمدة إلى بايثون. |
| **نقل البيانات** | الرئيسية ترسل فقط `source_ids` في طلب `/scrape/run`. بايثون تقرأ التفاصيل التقنية من جدولها. |
| **الإعلام** | بايثون ترسل Webhook إلى الرئيسية عند اكتمال الجلب (مع `batch_id` و `total_opportunities`). |
| **قراءة النتائج** | الرئيسية تقرأ الفرص النظيفة مباشرة من قاعدة بيانات بايثون (صلاحيات `SELECT`). |

**التغيير الجوهري:** أُلغي اعتماد خدمة بايثون على قراءة المصادر من قاعدة البيانات الرئيسية (أُلغي `MainDBClient`). أصبحت بايثون تمتلك مصدرها الخاص للمعلومات التقنية عن المصادر.

---

## 2. هيكل المشروع النهائي (Folder Structure)

بناءً على القرارات المعمارية المعتمدة، سيتم تنظيم المشروع على النحو التالي:

```
levora-python-service/
├── src/
│   ├── api/                         # طبقة API (FastAPI)
│   │   ├── __init__.py
│   │   ├── dependencies.py          # التبعيات المشتركة (مثل: التحقق من API Key)
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── v1/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── scrape.py        # POST /api/v1/scrape/run
│   │   │   │   ├── webhook.py       # POST /api/v1/webhook/scrape-complete (تنبيه الرئيسية)
│   │   │   │   └── health.py        # GET /health
│   │   └── models/                  # نماذج الطلب والاستجابة (Pydantic)
│   │       ├── __init__.py
│   │       ├── scrape_requests.py
│   │       └── scrape_responses.py
│   │
│   ├── modules/                     # الموديولات حسب الميزة
│   │   ├── infrastructure/          # الخدمات التحتية
│   │   │   ├── __init__.py
│   │   │   ├── http/                # عميل HTTP موحد
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base_http_client.py
│   │   │   │   ├── retry_strategy.py
│   │   │   │   └── exceptions.py
│   │   │   └── webhook/             # عميل Webhook (جديد)
│   │   │       ├── __init__.py
│   │   │       └── webhook_client.py
│   │   │
│   │   ├── scraping/                # موديول الجلب (المسؤولية الأساسية للعضو الثاني)
│   │   │   ├── __init__.py
│   │   │   ├── models/              # نماذج البيانات
│   │   │   │   ├── __init__.py
│   │   │   │   ├── raw_opportunity.py
│   │   │   │   └── cleaned_opportunity.py
│   │   │   ├── services/            # منطق الأعمال
│   │   │   │   ├── __init__.py
│   │   │   │   ├── scraper_service.py      # ينسق عملية الجلب الكاملة
│   │   │   │   ├── cleaning_service.py     # تنظيف المحتوى النصي
│   │   │   │   ├── normalization_service.py # توحيد القيم
│   │   │   │   └── deduplication_service.py # كشف التكرار
│   │   │   ├── adapters/            # محولات خاصة بالمصادر
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base_adapter.py          # الواجهة الموحدة
│   │   │   │   ├── wordpress_api_adapter.py # قاعدة لمصادر WordPress
│   │   │   │   ├── almin7_adapter.py
│   │   │   │   ├── grabscholarship_adapter.py
│   │   │   │   └── adapter_factory.py       # ربط اسم المصدر بالمحول
│   │   │   └── utils/
│   │   │       ├── text_cleaner.py
│   │   │       └── date_parser.py
│   │   │
│   │   └── core/                    # الموديول الأساسي
│   │       ├── __init__.py
│   │       ├── config/              # إعدادات التطبيق
│   │       │   ├── __init__.py
│   │       │   └── settings.py
│   │       ├── database/            # مستودعات كتابة البيانات (Prisma)
│   │       │   ├── __init__.py
│   │       │   ├── prisma_client.py
│   │       │   └── repositories/
│   │       │       ├── __init__.py
│   │       │       ├── source_repository.py    # (جديد) قراءة المصادر من قاعدة بايثون
│   │       │       └── opportunity_repository.py
│   │       └── auth/                # نظام المصادقة
│   │           ├── __init__.py
│   │           ├── api_key_auth.py
│   │           └── models.py
│   │
│   ├── utils/                       # أدوات مشتركة
│   │   ├── __init__.py
│   │   └── exceptions.py
│   │
│   └── main.py                      # نقطة الدخول الرئيسية
│
├── prisma/
│   ├── schema.prisma                # (مُحدَّث) يحتوي على Source, RawOpportunity, CleanedOpportunity
│   └── migrations/
│
├── tests/                           # اختبارات الوحدة والتكامل
│   ├── __init__.py
│   ├── conftest.py
│   ├── modules/
│   │   ├── infrastructure/
│   │   │   ├── test_http_client.py
│   │   │   └── test_webhook_client.py
│   │   └── scraping/
│   │       ├── test_adapters.py
│   │       ├── test_cleaning_service.py
│   │       ├── test_normalization_service.py
│   │       ├── test_deduplication_service.py
│   │       └── test_scraper_service.py
│   └── api/
│       └── test_scrape_routes.py
│
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 3. نماذج البيانات (Prisma Schema)

```prisma
// prisma/schema.prisma

generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

// ============================================================
// جدول المصادر (يديره المطورون في قاعدة بايثون)
// ============================================================
model Source {
  id                String    @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  name              String    @unique @db.Text        // المعرف النصي (مثل "almin7")
  display_name      String    @db.Text                // الاسم المعروض (مثل "Almin7")
  base_url          String    @db.Text                // الرابط الأساسي
  api_endpoint      String    @db.Text                // مسار API (مثل "/wp-json/wp/v2/posts")
  method            String    @default("wordpress_api") @db.Text // wordpress_api, html, api
  pagination_config Json      @default("{}")          // إعدادات Pagination (page param, per_page)
  field_mapping     Json      @default("{}")          // تعيين الحقول (title -> title.rendered)
  is_active         Boolean   @default(true)
  scrape_frequency  String?   @default("daily")       // daily, weekly, hourly
  last_scraped_at   DateTime?
  created_at        DateTime  @default(now())
  updated_at        DateTime  @updatedAt

  raw_opportunities RawOpportunity[]
  opportunities     CleanedOpportunity[]

  @@map("sources")
}

// ============================================================
// البيانات الخام
// ============================================================
model RawOpportunity {
  id                String    @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  source_id         String    @map("source_id") @db.Uuid
  source            Source    @relation(fields: [source_id], references: [id])
  raw_payload       Json      @default("{}")          // الاستجابة الكاملة من المصدر
  source_url        String    @db.Text                // رابط المقالة/الفرصة في المصدر
  scraped_at        DateTime  @default(now())
  status            String    @default("pending")     // pending, processing, cleaned, failed
  error_message     String?
  created_at        DateTime  @default(now())
  updated_at        DateTime  @updatedAt

  cleaned_opportunity CleanedOpportunity?

  @@map("raw_opportunities")
}

// ============================================================
// الفرص النظيفة (الجاهزة للقراءة من قبل الخدمة الرئيسية)
// ============================================================
model CleanedOpportunity {
  id                String    @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  raw_opportunity_id String?  @map("raw_opportunity_id") @db.Uuid
  raw_opportunity   RawOpportunity? @relation(fields: [raw_opportunity_id], references: [id])

  source_id         String    @map("source_id") @db.Uuid
  source            Source    @relation(fields: [source_id], references: [id])

  // البيانات النظيفة
  title             String    @db.Text
  organization      String?   @db.Text
  opportunity_type  String?   @db.Text                // scholarship, internship, training, fellowship
  description       String?   @db.Text
  eligibility       Json      @default("{}")
  location          String?   @db.Text
  is_remote         Boolean   @default(false)
  funding_type      String?   @db.Text                // fully_funded, partially_funded, unfunded
  deadline          DateTime?
  application_url   String?   @db.Text
  source_url        String    @db.Text
  country           String?   @db.Text
  study_levels      String[]  @default([])            // Bachelor, Master, PhD
  fields_of_study   String[]  @default([])

  // حالة المعالجة
  status            String    @default("pending")     // pending, cleaned, failed
  error_message     String?
  content_hash      String?   @db.Text                // لمنع التكرار

  created_at        DateTime  @default(now())
  updated_at        DateTime  @updatedAt

  match_scores      MatchScore[]

  @@map("cleaned_opportunities")
}

// ============================================================
// نتائج المطابقة (لمشروع مستقبلي - هيكل أولي)
// ============================================================
model MatchScore {
  id                String    @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  user_id           String    @db.Uuid                // معرف من الخدمة الرئيسية (بدون FK)
  opportunity_id    String    @map("opportunity_id") @db.Uuid
  opportunity       CleanedOpportunity @relation(fields: [opportunity_id], references: [id])
  score_pct         Int
  score_breakdown   Json      @default("{}")
  calculation_version Int     @default(1)
  calculated_at     DateTime  @default(now())
  created_at        DateTime  @default(now())
  updated_at        DateTime  @updatedAt

  @@unique([user_id, opportunity_id])
  @@map("match_scores")
}

// ============================================================
// مفاتيح API (للمصادقة)
// ============================================================
model ApiKey {
  id                String    @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  key               String    @unique @db.Text
  name              String    @db.Text
  is_active         Boolean   @default(true)
  last_used_at      DateTime?
  expires_at        DateTime?
  created_at        DateTime  @default(now())

  @@map("api_keys")
}
```

---

## 4. توزيع المهام في سبرينت 2

### 4.1 ترتيب المهام (حسب الأولوية)

| الأولوية | المجموعة | الوصف |
| :--- | :--- | :--- |
| **1** | **البنية التحتية الأساسية** | تجهيز البيئة، قاعدة البيانات، وإعدادات المشروع. |
| **2** | **موديول `infrastructure`** | بناء العميل HTTP الموحد وعميل Webhook. |
| **3** | **موديول `core`** | المصادقة بـ API Key، مستودعات قراءة وكتابة البيانات. |
| **4** | **موديول `scraping` - الجزء الأول** | نماذج البيانات، المحولات (BaseAdapter + WordPressApiAdapter + محولان فعليان). |
| **5** | **موديول `scraping` - الجزء الثاني** | خدمات التنظيف، التوحيد، منع التكرار، وخدمة الجلب الرئيسية. |
| **6** | **طبقة API** | إنشاء نقاط النهاية (`/scrape/run`, `/health`) وربطها بالخدمات. |
| **7** | **التكامل والاختبارات** | اختبارات التكامل، معالجة الأخطاء، التوثيق. |

---

### 4.2 تقسيم المهام على الأعضاء

#### العضو الأول (Member 1) - مسؤول عن البنية التحتية، المصادقة، وطبقة API

| المعرف | المهمة | الوصف التفصيلي | اختبارات مطلوبة | الأولوية |
| :--- | :--- | :--- | :--- | :--- |
| **A-01** | تهيئة المشروع وإعداد البيئة | إنشاء مشروع Python باستخدام Poetry، تثبيت الاعتماديات الأساسية (FastAPI، Prisma، Pydantic، httpx، pytest)، إعداد `.env.example`، تهيئة git والربط مع المستودع البعيد وإنشاء initial commit. | - | 1 |
| **A-02** | تكوين Prisma وإنشاء الجداول الأولية | كتابة `schema.prisma` (كما هو موضح في القسم 3) مع جداول: `Source`, `RawOpportunity`, `CleanedOpportunity`, `ApiKey`. تشغيل أول ترحيل (Migration) وإنشاء اتصال بقاعدة بيانات PostgreSQL خارجية. | اختبار الاتصال بقاعدة البيانات ووجود الجداول. | 1 |
| **A-03** | بناء موديول `infrastructure.http` | تنفيذ `BaseHttpClient` مع دعم الطلبات غير المتزامنة (async)، معالجة الأخطاء الأساسية، وإعداد سياسة إعادة المحاولة البسيطة (Retry). | اختبار نجاح وفشل الطلبات، وإعادة المحاولة. | 2 |
| **A-04** | بناء موديول `infrastructure.webhook` | تنفيذ `WebhookClient` لإرسال إشعارات إلى الخدمة الرئيسية عند اكتمال الجلب. يحتوي على منطق إعادة المحاولة وفشل الاتصال. | اختبار إرسال Webhook بنجاح وفشل. | 2 |
| **A-05** | بناء نظام المصادقة (API Key) | إنشاء جدول `ApiKey` في Prisma، كتابة خدمة للتحقق من صحة المفتاح، وإضافة اعتماد (Dependency) في FastAPI لحماية نقاط النهاية. | اختبار التحقق من صحة المفاتيح الصحيحة والخاطئة. | 3 |
| **A-06** | إنشاء مستودع كتابة البيانات (OpportunityRepository) | تنفيذ مستودع في `core.database.repositories` لكتابة الفرص الخام (`RawOpportunity`) والنظيفة (`CleanedOpportunity`) في قاعدة بيانات بايثون باستخدام Prisma. | اختبار إدراج البيانات في قاعدة البيانات. | 3 |
| **A-07** | إنشاء مستودع قراءة المصادر (SourceRepository) | تنفيذ مستودع لقراءة المصادر من جدول `Source` في قاعدة بيانات بايثون (بناءً على المعرفات الواردة في طلب الجلب). | اختبار قراءة المصادر من قاعدة البيانات. | 3 |
| **A-08** | بناء نقطة النهاية `/health` | إنشاء نقطة `GET /health` للتحقق من صحة الخدمة والاتصال بقاعدة البيانات. | اختبار نقطة النهاية. | 4 |
| **A-09** | بناء نقطة النهاية `/scrape/run` | إنشاء نقطة `POST /api/v1/scrape/run` المحمية بـ API Key، والتي تستقبل `source_ids` وتستدعي `ScraperService` (التي سيبنيها العضو الثاني). | اختبار نقطة النهاية باستخدام عميل اختبار FastAPI. | 5 |
| **A-10** | بناء نقطة النهاية `/webhook/scrape-complete` | إنشاء نقطة `POST /api/v1/webhook/scrape-complete` (للتنبيه الداخلي أو للاختبار). | اختبار استقبال Webhook. | 5 |
| **A-11** | إنشاء مستخدم قاعدة البيانات للخدمة الرئيسية | كتابة أمر (Script) أو تعليمات لإنشاء مستخدم في قاعدة بيانات بايثون بصلاحيات قراءة فقط على جداول `CleanedOpportunity` و `MatchScore`. | التحقق من صلاحيات المستخدم. | 6 |
| **A-12** | توثيق آلية التواصل مع الخدمة الرئيسية | كتابة وثيقة توضح نقاط النهاية، طريقة المصادقة، تنسيق البيانات، وصلاحيات قاعدة البيانات. | - | 6 |

---

#### العضو الثاني (Member 2) - مسؤول عن موديول الجلب (Scraping)

| المعرف | المهمة | الوصف التفصيلي | اختبارات مطلوبة | الأولوية |
| :--- | :--- | :--- | :--- | :--- |
| **B-01** | تعريف نماذج البيانات (Pydantic) | بناء `RawOpportunity` و `CleanedOpportunity` باستخدام Pydantic (مطابقة لنماذج Prisma). | اختبار صلاحية النماذج مع بيانات JSON وهمية. | 1 |
| **B-02** | بناء `BaseAdapter` | إنشاء الواجهة الموحدة لجميع المحولات مع دوال `fetch()` و `parse()` مجردة (abstract). | اختبار الوراثة والالتزام بالواجهة. | 2 |
| **B-03** | بناء `WordPressApiAdapter` | إنشاء محول أساسي لمصادر WordPress، يتعامل مع `/wp-json/wp/v2/posts`، ويدعم Pagination (page, per_page). | اختبار الاتصال بـ API حقيقي (Almin7). | 2 |
| **B-04** | بناء `Almin7Adapter` | محول خاص بموقع Almin7، يرث من `WordPressApiAdapter`. يقوم بـ: تحديد `source_name="almin7"`، وقراءة التصنيفات لتصفية المقالات (الاحتفاظ بالفرص فقط). | اختبار جلب 20 مقالة وتصفيتها. | 3 |
| **B-05** | بناء `GrabScholarshipAdapter` | محول خاص بموقع GrabScholarship، يرث من `WordPressApiAdapter`. يقوم بـ: تحديد `source_name="grabscholarship"`، واستخدام التصنيفات (MBA, Bachelor, PhD, Internship) لتحديد نوع الفرصة. | اختبار جلب الفرص من تصنيفات محددة. | 3 |
| **B-06** | بناء `AdapterFactory` | تنفيذ مصنع (Factory) يقوم بتسجيل المحولات وربطها بأسمائها (`almin7` → `Almin7Adapter`). | اختبار إرجاع المحول المناسب بناءً على الاسم. | 3 |
| **B-07** | بناء `CleaningService` | تنفيذ خدمة تنظيف مركزي: إزالة علامات HTML من النص، استخراج النص النظيف، تحليل التواريخ باستخدام `dateparser`. | اختبار مع محتوى HTML حقيقي من Almin7 و GrabScholarship. | 4 |
| **B-08** | بناء `NormalizationService` | تنفيذ خدمة توحيد القيم: تحويل `funding_type` (`fully funded` → `FULLY_FUNDED`)، `study_levels`، `opportunity_type`. | اختبار توحيد قيم مختلفة من مصدرين. | 4 |
| **B-09** | بناء `DeduplicationService` | تنفيذ خدمة كشف التكرار: استخدام `title` مطبع (normalized) + `organization` أو `source_url` لاكتشاف المكررات. | اختبار مع فرصة مكررة (نفس المنحة في Almin7 و GrabScholar). | 4 |
| **B-10** | بناء `ScraperService` | تنفيذ خدمة الجلب الرئيسية التي: (1) تستقبل قائمة معرفات المصادر، (2) تقرأ المصادر من `SourceRepository`، (3) تستدعي `AdapterFactory` للحصول على المحول المناسب، (4) تنفذ `fetch()` و `parse()`، (5) تمرر البيانات إلى `CleaningService`، (6) `NormalizationService`، (7) `DeduplicationService`، (8) تخزن عبر `OpportunityRepository`. | اختبار الدورة الكاملة لمصدر واحد. | 5 |
| **B-11** | ربط `ScraperService` مع `WebhookClient` | بعد اكتمال الجلب، يستدعي `ScraperService` الـ `WebhookClient` لإرسال إشعار إلى الخدمة الرئيسية يحتوي على `batch_id` و `total_opportunities`. | اختبار إرسال Webhook بعد اكتمال الجلب. | 5 |
| **B-12** | إدخال بيانات المصادر الأولية في قاعدة البيانات | كتابة أمر (Script) أو تعليمات لإدراج سجلات المصادر (Almin7, GrabScholarship) في جدول `Source` في قاعدة بيانات بايثون. | التحقق من وجود البيانات في قاعدة البيانات. | 5 |

---

### 4.3 المهام المشتركة (التطوير التكراري)

| المعرف | المهمة | الوصف التفصيلي | اختبارات مطلوبة | الأولوية |
| :--- | :--- | :--- | :--- | :--- |
| **C-01** | معالجة الأخطاء الأساسية | إضافة منطق للتعامل مع فشل المصادر الفردية (تسجيل الخطأ، متابعة المصادر الأخرى) في `ScraperService`. | اختبار استمرارية العمل عند فشل مصدر. | 5 |
| **C-02** | كتابة اختبارات التكامل الشاملة | اختبار الدورة الكاملة من API إلى التخزين باستخدام قاعدة بيانات اختبارية ومحولات وهمية. | تغطية السيناريوهات الناجحة والخاطئة. | 6 |
| **C-03** | توثيق الكود وإعداد README | كتابة Docstrings للوظائف الرئيسية، وتحديث README بتعليمات التشغيل، وإضافة مصدر جديد، وتشغيل الاختبارات. | - | 6 |
| **C-04** | مراجعة الكود وتوحيد الأسلوب | مراجعة الكود بين العضوين، تطبيق `black` و `ruff`، والتأكد من اجتياز الاختبارات. | - | 6 |

---

## 5. ضوابط ومعايير الجودة

1. **الاختبارات:** كل مهمة (عدا التوثيق) يجب أن تكون مصحوبة باختبارات وحدة (Unit Tests) على الأقل، واختبارات تكامل (Integration Tests) للمهام التي تتفاعل مع قواعد البيانات أو الخدمات الخارجية.
2. **التزامن (Async):** استخدام `async/await` في جميع الوظائف التي تتعامل مع I/O (طلبات HTTP، قاعدة البيانات).
3. **حقن التبعية:** يتم حقن جميع التبعيات عبر المُنشئ لتسهيل الاختبار وفك الاقتران.
4. **إدارة الأخطاء:** استخدام استثناءات مخصصة (Custom Exceptions) في كل موديول، مع تسجيل الأخطاء الأساسي.
5. **متغيرات البيئة:** جميع الإعدادات الحساسة (مثل: روابط قواعد البيانات، المفاتيح) تُقرأ من متغيرات البيئة (`.env`).

---

## 6. متطلبات النجاح (Definition of Done)

1. **التكامل:** يمكن استدعاء نقطة `POST /api/v1/scrape/run` بنجاح، وتشغيل عملية جلب كاملة من مصدرين على الأقل (Almin7 و GrabScholarship)، مع تخزين البيانات في قاعدة بيانات بايثون.
2. **Webhook:** بعد اكتمال الجلب، تُرسل خدمة بايثون Webhook إلى الخدمة الرئيسية (في بيئة الاختبار) بنجاح.
3. **الاختبارات:** جميع الاختبارات (الوحدة والتكامل) تمر بنجاح.
4. **التوثيق:** README ووثيقة التكامل مع الخدمة الرئيسية مكتملة.
5. **المستخدم:** تم إنشاء مستخدم قاعدة البيانات للخدمة الرئيسية بصلاحيات قراءة فقط على جداول `CleanedOpportunity` و `MatchScore`.

---

## 7. الخلاصة

تم تصميم هذه الخطة لتمكين فريق بايثون من البدء فوراً في سبرينت 2، مع توفير هيكل مرن وقابل للتوسع. تم ترتيب المهام بحيث تبدأ بالأساسيات، ثم تتدرج نحو بناء الموديولات المتقدمة، مع التأكيد على ضرورة إنشاء اختبارات لكل مهمة لضمان جودة الكود واستقرار الخدمة.

**التغييرات الجوهرية مقارنة بالإصدار السابق:**

| العنصر | الإصدار السابق | الإصدار الحالي |
|--------|---------------|----------------|
| جدول المصادر | يُقرأ من قاعدة الرئيسية (عبر `MainDBClient`) | يُقرأ من قاعدة بايثون (جدول `Source`) |
| `MainDBClient` | مطلوب لقراءة المصادر | **أُلغي** بالكامل |
| `SourceRepository` | غير موجود | **جديد** لقراءة المصادر من قاعدة بايثون |
| `WebhookClient` | غير موجود | **جديد** لإعلام الرئيسية بانتهاء الجلب |
| مهام العضو الثاني | غير محددة | **محددة بالكامل** (12 مهمة) |

---

*تم إعداد هذه الخطة بناءً على القرارات المعمارية النهائية المؤرخة 25 أغسطس 2026، مع التركيز على استقلالية خدمة بايثون في إدارة المصادر وجلب البيانات، مع الحفاظ على التكامل السلس مع الخدمة الرئيسية عبر Webhook والقراءة المباشرة من قاعدة البيانات.*
