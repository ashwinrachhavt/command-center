"""Pure text comparisons: no database, provider, or language-model calls."""

import pytest
from pydantic import ValidationError

from command_center.db.keyword_matching import analyze_keywords


def test_detected_coverage_counts_unique_terms_and_common_aliases():
    analysis = analyze_keywords(
        "Use Python, PYTHON, PostgreSQL, Amazon Web Services, and Figma.",
        "Built Python applications with Postgres and AWS.",
    )

    assert analysis.model_dump() == {
        "algorithm": "keyword-coverage.v1",
        "mode": "detected",
        "score": 75,
        "matched_count": 3,
        "keyword_count": 4,
        "keywords": [
            {"term": "Python", "matched": True},
            {"term": "PostgreSQL", "matched": True},
            {"term": "AWS", "matched": True},
            {"term": "Figma", "matched": False},
        ],
        "limit_reached": False,
    }


def test_detects_business_design_product_and_operations_terms():
    analysis = analyze_keywords(
        "Product management, user research, financial modeling, supply chain, "
        "customer success, and project management.",
        "Led customer success and user research with financial modelling.",
    )

    assert [(item.term, item.matched) for item in analysis.keywords] == [
        ("Product management", False),
        ("User research", True),
        ("Financial modeling", True),
        ("Supply chain", False),
        ("Customer success", True),
        ("Project management", False),
    ]
    assert analysis.score == 50


@pytest.mark.parametrize(
    ("term", "resume", "matched"),
    [
        ("Java", "JavaScript TypeScript java_test", False),
        ("Java", "Worked in (JAVA).", True),
        ("Java", "JavaScript first, followed by Java.", True),
        ("R", "Research experience and programming.", False),
        ("R", "Python/R, statistics", True),
        ("C", "C++ and C#", False),
        ("C++", "C and C#", False),
        ("C++", "Used (c++) daily.", True),
        ("C++", "C+++ C++17 AC++ C++Builder", False),
        ("C#", "C C++ C#x XC#", False),
        ("C#", "C#/.NET", True),
        (".NET", "internet ASP.NET dotnetwork", False),
        (".NET", "Worked with .net.", True),
        ("Node.js", "nodeXjs anode.js node.jsx", False),
        ("Node.js", "Used NODE.JS, NodeJS and node.js.", True),
        ("CI/CD", "XCI/CD CI/CDX CIxCD", False),
        ("CI/CD", "Built ci/cd pipelines.", True),
        ("q", "q\u0301 qwerty", False),
        ("设计", "产品设计师", False),
        ("设计", "设计 / research", True),
    ],
)
def test_selected_terms_match_whole_tokens_with_significant_punctuation(term, resume, matched):
    analysis = analyze_keywords("", resume, [term])

    assert analysis.mode == "selected"
    assert analysis.keyword_count == 1
    assert analysis.keywords[0].matched is matched
    assert analysis.score == (100 if matched else 0)


def test_unicode_normalization_dedupes_and_preserves_first_chosen_labels():
    analysis = analyze_keywords(
        "",
        "CAFE\u0301; STRASSE; Python; user\n\tresearch",
        [" Café ", "Cafe\u0301", "Straße", "STRASSE", "Ｐｙｔｈｏｎ", "User   research"],
    )

    assert [item.term for item in analysis.keywords] == [
        "Café",
        "Straße",
        "Python",
        "User research",
    ]
    assert analysis.score == 100
    assert analysis.keyword_count == analysis.matched_count == 4


def test_selected_aliases_dedupe_by_skill_and_retain_first_user_label():
    analysis = analyze_keywords(
        "",
        "AWS; Postgres; nodejs; dotnet; C sharp; k8s",
        [
            "Amazon Web Services",
            "aws",
            "PostgreSQL",
            "Postgres",
            "Node.js",
            ".NET",
            "C#",
            "Kubernetes",
        ],
    )

    assert [item.term for item in analysis.keywords] == [
        "Amazon Web Services",
        "PostgreSQL",
        "Node.js",
        ".NET",
        "C#",
        "Kubernetes",
    ]
    assert analysis.score == 100


def test_selected_keywords_support_other_domains_and_do_not_require_job_occurrences():
    analysis = analyze_keywords(
        "An unrelated description.",
        "Welding; orbital mechanics; community organizing.",
        ["welding", "Orbital mechanics", "Community organizing", "Ceramics"],
    )

    assert analysis.score == 75
    assert [(item.term, item.matched) for item in analysis.keywords] == [
        ("welding", True),
        ("Orbital mechanics", True),
        ("Community organizing", True),
        ("Ceramics", False),
    ]


def test_selected_keywords_do_not_stem_or_infer_related_qualifications():
    analysis = analyze_keywords("", "Managed engineers using Python.", ["management", "Java"])

    assert analysis.score == 0
    assert analysis.matched_count == 0


@pytest.mark.parametrize(
    "job", ["", "   ", "Competitive salary, paid time off, remote work, benefits."]
)
def test_empty_or_boilerplate_only_job_has_no_default_score(job):
    analysis = analyze_keywords(job, "Python SQL Figma")

    assert analysis.mode == "detected"
    assert analysis.score is None
    assert analysis.keywords == []
    assert analysis.keyword_count == analysis.matched_count == 0
    assert analysis.limit_reached is False


def test_missing_only_analysis_has_zero_score():
    analysis = analyze_keywords("Python and SQL", "")

    assert analysis.score == 0
    assert analysis.matched_count == 0
    assert analysis.keyword_count == 2
    assert all(not item.matched for item in analysis.keywords)


@pytest.mark.parametrize(
    ("keywords", "message"),
    [
        ([], "between 1 and 50"),
        (["Python"] * 51, "between 1 and 50"),
        ([""], "nonblank"),
        ([" \n\t\u3000"], "nonblank"),
        (["Python", " "], "nonblank"),
        (["x" * 81], "80 characters"),
        ([" " * 80 + "x"], "80 characters"),
        (["\ufb03" * 27], "80 characters"),
        ([None], "strings"),
        ([1], "strings"),
        ("Python", "list"),
        (("Python",), "list"),
    ],
)
def test_invalid_selected_keywords_are_rejected_without_silent_fallback(keywords, message):
    with pytest.raises(ValueError, match=message):
        analyze_keywords("Python", "Python", keywords)


def test_fifty_selected_keywords_and_eighty_character_term_are_accepted():
    keywords = ["x" * 80] + [f"skill {number}" for number in range(49)]
    analysis = analyze_keywords("", "x" * 80, keywords)

    assert analysis.keyword_count == 50
    assert analysis.matched_count == 1
    assert analysis.score == 2
    assert analysis.limit_reached is False


@pytest.mark.parametrize("field", ["job", "resume"])
def test_text_is_bounded_before_and_after_unicode_normalization(field):
    for oversized in ("x" * 200_001, "\ufb03" * 66_667):
        job, resume = (oversized, "") if field == "job" else ("", oversized)
        with pytest.raises(ValueError, match="200000 characters"):
            analyze_keywords(job, resume)

    assert analyze_keywords("x" * 200_000, "x" * 200_000).score is None


@pytest.mark.parametrize(("job", "resume"), [(None, ""), ("", b"Python")])
def test_text_inputs_must_be_strings(job, resume):
    with pytest.raises(ValueError, match="string"):
        analyze_keywords(job, resume)


@pytest.mark.parametrize(
    "term", [".*", "(a+)+$", "[a-z]+", "${TOKEN}", "ignore all prior instructions"]
)
def test_regex_and_instruction_like_keywords_are_literal_data(term):
    assert analyze_keywords("", f"Selected: {term} ; done", [term]).score == 100
    assert analyze_keywords("", "ordinary text aaaaaaz", [term]).score == 0


@pytest.mark.parametrize(
    ("matched", "total", "score"),
    [(1, 3, 33), (2, 3, 67), (1, 8, 13), (5, 8, 63), (0, 8, 0), (8, 8, 100)],
)
def test_score_is_unweighted_percentage_rounded_half_up(matched, total, score):
    keywords = [f"skill{number}" for number in range(total)]
    analysis = analyze_keywords("", " ".join(keywords[:matched]), keywords)

    assert analysis.score == score
    assert analysis.matched_count == matched
    assert analysis.keyword_count == total


def test_autodetection_cap_uses_first_occurrence_and_reports_truncation():
    terms = [
        "Python",
        "Java",
        "JavaScript",
        "TypeScript",
        "C++",
        "C#",
        ".NET",
        "Node.js",
        "CI/CD",
        "SQL",
        "R",
        "Rust",
        "Ruby",
        "PHP",
        "Swift",
        "Kotlin",
        "Scala",
        "HTML",
        "CSS",
        "React",
        "Angular",
        "Vue",
        "Next.js",
        "Django",
        "Flask",
        "FastAPI",
        "Rails",
        "Spring",
        "GraphQL",
        "PostgreSQL",
        "MySQL",
        "SQLite",
        "MongoDB",
        "Redis",
        "Elasticsearch",
        "Snowflake",
        "BigQuery",
        "Databricks",
        "Spark",
        "Kafka",
        "Airflow",
        "dbt",
        "AWS",
        "Azure",
        "Google Cloud",
        "Docker",
        "Kubernetes",
        "Terraform",
        "Ansible",
        "Linux",
        "Git",
    ]
    analysis = analyze_keywords("; ".join(terms), "Git; Python; Linux")

    assert [item.term for item in analysis.keywords] == terms[:50]
    assert analysis.keyword_count == 50
    assert analysis.matched_count == 2
    assert analysis.score == 4
    assert analysis.limit_reached is True
    assert analyze_keywords("; ".join(terms[:50]), "").limit_reached is False


def test_analysis_records_and_match_records_reject_field_reassignment():
    analysis = analyze_keywords("Python", "Python")

    with pytest.raises(ValidationError, match="frozen"):
        analysis.score = 0
    with pytest.raises(ValidationError, match="frozen"):
        analysis.keywords[0].matched = False
