from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.scraping.adapters.almin7_adapter import Almin7Adapter


def test_almin7_adapter_parse_scholarship():
    adapter = Almin7Adapter()
    raw_item = {
        "title": {
            "rendered": "منحة الحكومة التركية 2026 لدراسة البكالوريوس والماجستير ممول بالكامل"
        },
        "content": {
            "rendered": "<p>منحة ممولة بالكامل في تركيا لدراسة البكالوريوس والماجستير. آخر موعد للتقديم: 20 فبراير 2026</p>"
        },
        "link": "https://almin7.com/turkey-scholarship-2026",
    }

    parsed = adapter.parse(raw_item)
    assert parsed["opportunity_type"] == "scholarship"
    assert "Bachelor" in parsed["study_levels"]
    assert "Master" in parsed["study_levels"]
    assert parsed["country"] == "تركيا"
    assert parsed["funding_type"] == "fully_funded"
    assert "20 فبراير 2026" in parsed["deadline"]


def test_almin7_adapter_determine_opportunity_types():
    adapter = Almin7Adapter()

    # Fellowship
    fellowship_item = {
        "title": {"rendered": "برنامج زمالة بحثية في ألمانيا"},
        "content": {"rendered": "زمالة ما بعد الدكتوراه"},
    }
    assert adapter.parse(fellowship_item)["opportunity_type"] == "fellowship"

    # Internship (Arabic)
    internship_item = {
        "title": {"rendered": "فرصة تدريب صيفي في كندا للطلاب"},
        "content": {"rendered": "تدريب عملي مدفوع"},
    }
    assert adapter.parse(internship_item)["opportunity_type"] == "internship"

    # Training
    training_item = {
        "title": {"rendered": "دورة تدريبية مكثفة في الذكاء الاصطناعي"},
        "content": {"rendered": "معسكر تدريبي"},
    }
    assert adapter.parse(training_item)["opportunity_type"] == "training"

    # Volunteering
    volunteering_item = {
        "title": {"rendered": "فرصة عمل تطوعي في فرنسا"},
        "content": {"rendered": "تطوع ممول بالكامل"},
    }
    assert adapter.parse(volunteering_item)["opportunity_type"] == "volunteering"

    # International scholarship regression: 'international' should NOT be internship
    international_item = {
        "title": {"rendered": "International Scholarship for Undergraduates in UK"},
        "content": {"rendered": "Full funding"},
    }
    assert adapter.parse(international_item)["opportunity_type"] == "scholarship"


def test_almin7_adapter_is_opportunity_by_category():
    adapter = Almin7Adapter()

    # 1. Opportunity category -> accepted
    opp_item = {
        "title": {"rendered": "منحة جامعة ميونخ في ألمانيا 2026"},
        "categories": ["منح دراسية", "ألمانيا"],
    }
    assert adapter.is_opportunity(opp_item) is True

    # 2. Non-opportunity category (Articles/News) -> rejected
    article_item = {
        "title": {"rendered": "كيف تختار تخصصك الجامعي الأنسب"},
        "categories": ["مقالات", "نصائح وإرشادات"],
    }
    assert adapter.is_opportunity(article_item) is False

    # 3. Fallback on title when categories are empty
    real_fallback_item = {"title": {"rendered": "منحة كندا للبكالوريوس 2026"}}
    assert adapter.is_opportunity(real_fallback_item) is True

    advice_fallback_item = {"title": {"rendered": "نصائح للدراسة في الخارج"}}
    assert adapter.is_opportunity(advice_fallback_item) is False


@pytest.mark.asyncio
async def test_almin7_adapter_fetch_html_listings():
    # Simulate HTML response from /scholarship/
    sample_cards = []
    for i in range(1, 15):
        sample_cards.append(f"""
        <article class="al7-archive-card post-{i} scholarship type-scholarship location-turkey">
            <h2 class="al7-archive-posttitle">
                <a href="https://almin7.com/scholarship/turkey-{i}/">منحة ممولة بالكامل رقم {i} لدراسة البكالوريوس في تركيا</a>
            </h2>
            <div class="al7-archive-meta">
                <span class="al7-archive-type">منحة</span>
            </div>
            <p class="al7-archive-excerpt">تفاصيل المنحة رقم {i}. بكالوريوس وماجستير.</p>
            <div class="al7-archive-taxline">
                <a href="https://almin7.com/location/turkey/">تركيا</a>
            </div>
            <div class="al7-archive-cardfoot">
                <span>20 مارس، 2026</span>
                <a class="al7-archive-action" href="https://university-{i}.edu.tr/apply">التقديم الرسمي</a>
            </div>
        </article>
        """)

    # Add 6 general advice articles (e.g. from non-scholarship categories)
    for j in range(15, 21):
        sample_cards.append(f"""
        <article class="al7-archive-card post-{j} post type-post category-articles">
            <h2 class="al7-archive-posttitle">
                <a href="https://almin7.com/article-{j}/">نصائح وإرشادات عامة رقم {j} للدراسة في الخارج</a>
            </h2>
            <div class="al7-archive-meta">
                <span class="al7-archive-type">مقال</span>
            </div>
            <p class="al7-archive-excerpt">مقال عام غير مرتبط بمنحة {j}.</p>
            <div class="al7-archive-cardfoot">
                <span>15 مارس، 2026</span>
            </div>
        </article>
        """)

    html_content = (
        f"<html><body><div class='posts'>{''.join(sample_cards)}</div></body></html>"
    )

    mock_response = MagicMock()
    mock_response.text = html_content
    mock_response.is_success = True

    adapter = Almin7Adapter()
    adapter.http_client.get = AsyncMock(return_value=mock_response)

    # 1. جلب 20 مقال بالضبط عبر HTML scraper
    raw_items = await adapter.fetch(limit=20)
    assert len(raw_items) == 20

    # 2. فحص استخراج الحقول من كروت الـ HTML
    first_item = raw_items[0]
    assert "منحة ممولة بالكامل رقم 1" in first_item["title"]
    assert first_item["country"] == "تركيا"
    assert first_item["application_url"] == "https://university-1.edu.tr/apply"
    assert first_item["badge"] == "منحة"

    # 3. تطبيق is_opportunity لتصفية المقالات العامة واستبقاء المنح فقط
    filtered_opportunities = [
        item for item in raw_items if adapter.is_opportunity(item)
    ]

    assert len(filtered_opportunities) == 14
    for opp in filtered_opportunities:
        assert opp["badge"] == "منحة"
        parsed = adapter.parse(opp)
        assert parsed["opportunity_type"] == "scholarship"
        assert parsed["application_url"].startswith("https://university-")


def test_almin7_adapter_parse_scraped_card():
    adapter = Almin7Adapter()
    scraped_item = {
        "title": "منحة الجامعة الرومانية الأمريكية",
        "link": "https://almin7.com/scholarship/romanian-american-university/",
        "source_url": "https://almin7.com/scholarship/romanian-american-university/",
        "application_url": "https://www.rau.ro/scholarship-regulations/?lang=en",
        "excerpt": "تعد منحة الجامعة الرومانية الأمريكية واحدة من أبرز الفرص الدراسية لدراسة البكالوريوس والماجستير ممول بالكامل",
        "content": "تعد منحة الجامعة الرومانية الأمريكية واحدة من أبرز الفرص الدراسية لدراسة البكالوريوس والماجستير ممول بالكامل. آخر موعد للتقديم: 15 أكتوبر 2026",
        "published_at": "6 سبتمبر، 2026",
        "country": "رومانيا",
        "badge": "منحة",
        "categories": ["منحة", "رومانيا", "scholarship-in-europe"],
        "card_classes": ["al7-archive-card", "type-scholarship", "location-rwmanya"],
    }

    parsed = adapter.parse(scraped_item)
    assert parsed["title"] == "منحة الجامعة الرومانية الأمريكية"
    assert (
        parsed["source_url"]
        == "https://almin7.com/scholarship/romanian-american-university/"
    )
    assert (
        parsed["application_url"]
        == "https://www.rau.ro/scholarship-regulations/?lang=en"
    )
    assert parsed["country"] == "رومانيا"
    assert parsed["opportunity_type"] == "scholarship"
    assert "Bachelor" in parsed["study_levels"]
    assert "Master" in parsed["study_levels"]
    assert parsed["funding_type"] == "fully_funded"
    assert parsed["deadline"] == "15 أكتوبر 2026"
    assert adapter.is_opportunity(scraped_item) is True


def test_almin7_adapter_reject_articles_and_specializations():
    adapter = Almin7Adapter()

    # 1. Reject by article badge
    article_by_badge = {
        "title": "ترتيب الجامعات الهنغارية لعام 2026",
        "badge": "مقال",
        "card_classes": [
            "al7-archive-card",
            "type-post",
            "category-university-rankings",
        ],
        "link": "https://almin7.com/university-rankings/hungary/",
    }
    assert adapter.is_opportunity(article_by_badge) is False

    # 2. Reject by URL pattern (specialization)
    spec_item = {
        "title": "دراسة الطب البشري في الأرجنتين",
        "badge": "",
        "card_classes": ["type-post"],
        "link": "https://almin7.com/specialization/medicine-argentina/",
    }
    assert adapter.is_opportunity(spec_item) is False

    # 3. Reject study abroad guides
    guide_item = {
        "title": "الدراسة في التشيك والتكاليف السنوية",
        "badge": "مقال",
        "card_classes": ["type-post", "category-study-abroad"],
        "link": "https://almin7.com/study-abroad/czech/",
    }
    assert adapter.is_opportunity(guide_item) is False

    # 4. Reject generic "study X in Y" articles
    study_guide_items = [
        {
            "title": "دراسة هندسة الحاسوب في قطر",
            "link": "https://almin7.com/study-computer-engineering-qatar/",
            "categories": ["قطر"],
        },
        {
            "title": "دراسة الرياضيات في عُمان",
            "link": "https://almin7.com/study-mathematics-oman/",
            "categories": ["عُمان"],
        },
        {
            "title": "دراسة هندسة الحاسوب في بروناي دار السلام",
            "link": "https://almin7.com/study-computer-engineering-brunei/",
            "categories": ["بروناي دار السلام"],
        },
        {
            "title": "دراسة الفيزياء في هنغاريا",
            "link": "https://almin7.com/study-physics-hungary/",
            "categories": ["هنغاريا"],
        },
    ]

    for item in study_guide_items:
        assert adapter.is_opportunity(item) is False
