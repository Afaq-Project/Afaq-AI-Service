from src.modules.scraping.adapters.grabscholarship_adapter import GrabScholarshipAdapter


def test_grabscholarship_classification_regression_international_scholarship():
    """Regression test: 'International' in title/categories MUST NOT cause scholarship to become internship."""
    adapter = GrabScholarshipAdapter()

    # Case 1: University of Alberta International Undergraduate Scholarships
    item1 = {
        "title": {
            "rendered": "University of Alberta International Undergraduate Scholarships"
        },
        "content": {
            "rendered": "<p>Are you aware that incoming students receive international scholarships? Covers tuition fees.</p>"
        },
        "categories": [
            "Scholarships",
            "Undergraduate Scholarships",
            "America",
            "Canada",
        ],
        "link": "https://grabscholarships.com/university-of-alberta-international-undergraduate-scholarships/",
    }
    parsed1 = adapter.parse(item1)
    assert (
        parsed1["opportunity_type"] == "scholarship"
    ), "International Undergraduate Scholarships must be 'scholarship' not 'internship'"
    assert "Bachelor" in parsed1["study_levels"]
    assert parsed1["country"] == "Canada"

    # Case 2: DAAD Helmut Schmidt Scholarship for International Students
    item2 = {
        "title": {
            "rendered": "DAAD Helmut Schmidt Scholarship 2026 | Fully Funded Study in Germany for International Students"
        },
        "content": {
            "rendered": "<p>Fully funded master program for international candidates.</p>"
        },
        "categories": ["Masters Scholarships", "Scholarships", "Europe", "Germany"],
        "link": "https://grabscholarships.com/daad-helmut-schmidt-scholarship/",
    }
    parsed2 = adapter.parse(item2)
    assert parsed2["opportunity_type"] == "scholarship"
    assert parsed2["funding_type"] == "fully_funded"
    assert parsed2["country"] == "Germany"

    # Case 3: University of Manitoba Scholarships for International Students
    item3 = {
        "title": {
            "rendered": "University of Manitoba Scholarships 2026 in Canada for International Students (Fully Funded)"
        },
        "content": {"rendered": "<p>Scholarships for international students.</p>"},
        "categories": [
            "Masters Scholarships",
            "Ph.D Scholarships",
            "Scholarships",
            "Canada",
        ],
        "link": "https://grabscholarships.com/university-of-manitoba-scholarships/",
    }
    parsed3 = adapter.parse(item3)
    assert parsed3["opportunity_type"] == "scholarship"

    # Case 4: Swansea University Centenary Scholarship
    item4 = {
        "title": {
            "rendered": "Swansea University Centenary Scholarship in the UK (Fully Funded MBA Opportunity)"
        },
        "content": {"rendered": "<p>Full funding for MBA studies in the UK.</p>"},
        "categories": ["Masters Scholarships", "Scholarships", "UK"],
        "link": "https://grabscholarships.com/swansea-university-centenary-scholarship/",
    }
    parsed4 = adapter.parse(item4)
    assert parsed4["opportunity_type"] == "scholarship"
    assert "Master" in parsed4["study_levels"]
    assert parsed4["country"] == "UK"


def test_grabscholarship_actual_internship():
    adapter = GrabScholarshipAdapter()
    item = {
        "title": {
            "rendered": "CERN Summer Student Internship 2026 in Switzerland (Fully Funded)"
        },
        "content": {
            "rendered": "<p>Internship program for technical undergraduate students. Full monthly stipend included.</p>"
        },
        "categories": ["Internships", "Switzerland"],
        "link": "https://grabscholarships.com/cern-summer-internship/",
    }
    parsed = adapter.parse(item)
    assert parsed["opportunity_type"] == "internship"
    assert parsed["country"] == "Switzerland"


def test_grabscholarship_is_opportunity_filtering():
    adapter = GrabScholarshipAdapter()

    # 1. Non-opportunity article: Guide to choosing courses
    guide_item = {
        "title": {"rendered": "A Guide to Choosing University Courses"},
        "content": {
            "rendered": "<p>Tips and guidelines for selecting your degree major.</p>"
        },
        "categories": ["University Courses"],
        "link": "https://grabscholarships.com/a-guide-to-choosing-university-courses/",
    }
    assert adapter.is_opportunity(guide_item) is False

    # 2. Non-opportunity article: University profile
    caltech_item = {
        "title": {"rendered": "California Institute of Technology (Caltech)"},
        "content": {
            "rendered": "<p>General info about Caltech campus, rankings, and faculty.</p>"
        },
        "categories": ["Top Universities"],
        "link": "https://grabscholarships.com/california-institute-of-technology-caltech/",
    }
    assert adapter.is_opportunity(caltech_item) is False

    # 3. Real scholarship
    real_item = {
        "title": {"rendered": "ASU MasterCard Scholarship in USA (Fully Funded)"},
        "content": {
            "rendered": "<p>Apply now for fully funded master degree. Deadline: 14 September</p>"
        },
        "categories": ["Masters Scholarships", "USA"],
        "link": "https://grabscholarships.com/asu-mastercard-scholarship/",
    }
    assert adapter.is_opportunity(real_item) is True


def test_grabscholarship_organization_extraction():
    adapter = GrabScholarshipAdapter()

    # Case 1: Organization in content label
    item1 = {
        "title": {"rendered": "Master Scholarship Program 2026"},
        "content": {
            "rendered": "<p>Host Institution: University of Cambridge</p><p>Fully funded.</p>"
        },
        "categories": ["Scholarships"],
        "link": "https://grabscholarships.com/cambridge-scholarship/",
    }
    parsed1 = adapter.parse(item1)
    assert parsed1["organization"] == "University of Cambridge"

    # Case 2: Organization in title (University pattern)
    item2 = {
        "title": {
            "rendered": "Harvard University Undergraduate Scholarship 2026 in USA"
        },
        "content": {"rendered": "<p>Fully funded study in USA.</p>"},
        "categories": ["Scholarships"],
        "link": "https://grabscholarships.com/harvard-scholarship/",
    }
    parsed2 = adapter.parse(item2)
    assert parsed2["organization"] == "Harvard University"


def test_grabscholarship_deadline_extraction():
    adapter = GrabScholarshipAdapter()

    item = {
        "title": {"rendered": "DAAD Scholarship 2026"},
        "content": {
            "rendered": "<p>Application deadline: 15 October 2026. For all international candidates.</p>"
        },
        "categories": ["Scholarships"],
        "link": "https://grabscholarships.com/daad-2026/",
    }
    parsed = adapter.parse(item)
    assert parsed["deadline"] == "15 October 2026"


def test_grabscholarship_eligibility_extraction_heading_with_list():
    """Test extracting eligibility criteria under <h2> with unordered list items."""
    adapter = GrabScholarshipAdapter()

    item = {
        "title": {
            "rendered": "MacEwan University Scholarships for International Students 2026"
        },
        "content": {"rendered": """
                <h2>Scholarship Benefits</h2>
                <p>Tuition fee waiver up to $10,000.</p>
                <h2>Eligibility Requirements for MacEwan Scholarships 2026</h2>
                <p>To be considered for MacEwan University scholarships, applicants must:</p>
                <ul>
                    <li>Be an international student (non-Canadian citizen or resident)</li>
                    <li>Be admitted into an eligible undergraduate program at MacEwan University</li>
                    <li>Register in at least 12 credits per term for both Fall and Winter semesters</li>
                    <li>Demonstrate academic excellence in high school or previous studies</li>
                    <li>Provide a valid high school completion certificate</li>
                </ul>
                <h2>Application Process for MacEwan University Scholarships</h2>
                <p>Submit your application through the student portal.</p>
            """},
        "categories": ["Scholarships", "Canada Scholarships"],
        "link": "https://grabscholarships.com/macewan-university-scholarships/",
    }

    parsed = adapter.parse(item)
    assert "eligibility" in parsed
    elig = parsed["eligibility"]
    assert "eligibility_text" in elig
    text = elig["eligibility_text"]

    assert "non-Canadian citizen" in text
    assert "undergraduate program" in text
    assert "12 credits per term" in text
    assert "academic excellence" in text

    # Boundary stopping: Must NOT contain next section content
    assert "Submit your application" not in text
    assert "Tuition fee waiver" not in text


def test_grabscholarship_eligibility_extraction_with_subheadings():
    """Test extracting eligibility with nested sub-headings like Academic/Admission requirements."""
    adapter = GrabScholarshipAdapter()

    item = {
        "title": {
            "rendered": "Beijing Normal University CSC Scholarship 2026 | Fully Funded in China"
        },
        "content": {"rendered": """
                <h2>Financial Coverage</h2>
                <p>Full tuition waiver, accommodation, monthly stipend.</p>
                <h2>Eligibility Criteria for Beijing Normal University CSC Scholarship</h2>
                <p>Applicants must meet the following conditions:</p>
                <ul>
                    <li>Must be non-Chinese citizens in good health</li>
                    <li>Master's applicants: Hold a Bachelor's degree, under the age of 35</li>
                    <li>PhD applicants: Hold a Master's degree, under the age of 40</li>
                    <li>Should not be currently enrolled in any Chinese university</li>
                </ul>
                <h2>How to Apply</h2>
                <p>Apply via the CSC online portal.</p>
            """},
        "categories": ["CSC Scholarships", "China"],
        "link": "https://grabscholarships.com/beijing-normal-university-csc-scholarship/",
    }

    parsed = adapter.parse(item)
    text = parsed["eligibility"]["eligibility_text"]
    assert "non-Chinese citizens" in text
    assert "under the age of 35" in text
    assert "under the age of 40" in text
    assert "Apply via the CSC" not in text


def test_grabscholarship_eligibility_missing_returns_empty_dict():
    """Test that a post without eligibility criteria returns an empty dict for eligibility."""
    adapter = GrabScholarshipAdapter()

    item = {
        "title": {"rendered": "Study Tips for International Students"},
        "content": {
            "rendered": "<p>Here are some great tips for preparing to study abroad.</p>"
        },
        "categories": ["Advice"],
        "link": "https://grabscholarships.com/study-tips/",
    }

    parsed = adapter.parse(item)
    assert parsed["eligibility"] == {}


def test_grabscholarship_eligibility_does_not_pollute_with_categories():
    """Ensure categories/tags and destination country are not leaked into eligibility_text."""
    adapter = GrabScholarshipAdapter()

    item = {
        "title": {"rendered": "Sample Award"},
        "content": {"rendered": """
                <h2>Eligibility Criteria</h2>
                <ul>
                    <li>Minimum GPA 3.5 required.</li>
                </ul>
                <h2>How to Apply</h2>
                <p>Online application form.</p>
            """},
        "categories": ["Germany Scholarships", "Postgraduate", "Europe"],
        "link": "https://grabscholarships.com/sample-award/",
    }

    parsed = adapter.parse(item)
    text = parsed["eligibility"]["eligibility_text"]
    assert "Minimum GPA 3.5 required." in text
    assert "Germany Scholarships" not in text
    assert "Europe" not in text
