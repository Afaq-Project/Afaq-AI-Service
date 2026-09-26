from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.scraping.adapters.wordpress_api_adapter import (
    WordPressApiAdapter,
    get_nested_field,
)


def test_get_nested_field_helper():
    data = {
        "title": {"rendered": "Master Scholarship"},
        "nested": {"level1": {"level2": "Deep Value"}},
        "list_items": [{"name": "First"}, {"name": "Second"}],
    }
    assert get_nested_field(data, "title.rendered") == "Master Scholarship"
    assert get_nested_field(data, "nested.level1.level2") == "Deep Value"
    assert get_nested_field(data, "list_items.0.name") == "First"
    assert get_nested_field(data, "non.existent.path") is None
    assert get_nested_field(data, None) is None


def test_wordpress_api_adapter_parse_default_mapping():
    adapter = WordPressApiAdapter()
    raw_item = {
        "title": {"rendered": "Default WP Title"},
        "content": {"rendered": "<p>Default content rendered</p>"},
        "excerpt": {"rendered": "<p>Default excerpt</p>"},
        "link": "https://example.com/wp-post-1",
        "date": "2026-09-01T12:00:00",
        "_embedded": {"wp:term": [[{"name": "Category 1"}, {"name": "Category 2"}]]},
    }

    parsed = adapter.parse(raw_item)
    assert parsed["title"] == "Default WP Title"
    assert parsed["content"] == "<p>Default content rendered</p>"
    assert parsed["description"] == "<p>Default excerpt</p>"
    assert parsed["source_url"] == "https://example.com/wp-post-1"
    assert parsed["published_at"] == "2026-09-01T12:00:00"
    assert parsed["categories"] == ["Category 1", "Category 2"]
    # Critical fix: categories must not be copied to fields_of_study
    assert parsed["fields_of_study"] == []


def test_wordpress_api_adapter_explicit_fields_of_study_mapping():
    custom_config = {
        "field_mapping": {
            "fields_of_study": "meta.academic_fields",
        }
    }
    adapter = WordPressApiAdapter(source_config=custom_config)
    raw_item = {
        "title": {"rendered": "Engineering Scholarship"},
        "meta": {"academic_fields": ["Computer Science", "Artificial Intelligence"]},
        "categories": ["Masters Scholarships", "Europe"],
    }
    parsed = adapter.parse(raw_item)
    assert parsed["categories"] == ["Masters Scholarships", "Europe"]
    assert parsed["fields_of_study"] == ["Computer Science", "Artificial Intelligence"]


def test_wordpress_api_adapter_custom_field_mapping():
    custom_config = {
        "field_mapping": {
            "title": "custom_title",
            "description": "meta.custom_desc",
            "content": "raw_body",
            "url": "custom_link",
            "date": "meta.published_date",
        }
    }
    adapter = WordPressApiAdapter(source_config=custom_config)

    raw_item = {
        "custom_title": "Custom Title from Mapping",
        "meta": {
            "custom_desc": "Custom description extracted via path",
            "published_date": "2026-10-15",
        },
        "raw_body": "<p>Raw body content</p>",
        "custom_link": "https://custom-domain.com/post-99",
        # Default WP paths that should NOT be used because custom mapping is active:
        "title": {"rendered": "Ignored Default Title"},
        "link": "https://ignored.com",
    }

    parsed = adapter.parse(raw_item)
    assert parsed["title"] == "Custom Title from Mapping"
    assert parsed["description"] == "Custom description extracted via path"
    assert parsed["content"] == "<p>Raw body content</p>"
    assert parsed["source_url"] == "https://custom-domain.com/post-99"
    assert parsed["published_at"] == "2026-10-15"


@pytest.mark.asyncio
async def test_wordpress_api_adapter_fetch_pagination():
    mock_http = MagicMock()
    # Mock first page with 2 posts, second page empty
    mock_resp_page1 = MagicMock()
    mock_resp_page1.json.return_value = [
        {"id": 1, "title": {"rendered": "Post 1"}},
        {"id": 2, "title": {"rendered": "Post 2"}},
    ]

    mock_resp_page2 = MagicMock()
    mock_resp_page2.json.return_value = []

    mock_http.get = AsyncMock(side_effect=[mock_resp_page1, mock_resp_page2])

    adapter = WordPressApiAdapter(
        source_config={
            "base_url": "https://test-wp.com",
            "pagination_config": {"per_page": 2},
        },
        http_client=mock_http,
    )

    posts = await adapter.fetch(limit=2)
    assert len(posts) == 2
    assert posts[0]["id"] == 1
    assert posts[1]["id"] == 2
