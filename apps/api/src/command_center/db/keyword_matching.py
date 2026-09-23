"""Deterministic text coverage, not an assessment of a person's qualifications.

The curated vocabulary deliberately excludes benefits and generic recruiting
boilerplate. Selected terms allow any domain. All matching is literal: source
text and selected keywords never become instructions or regular expressions.
"""

import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict

MAX_TEXT_CHARACTERS = 200_000
MAX_KEYWORDS = 50
MAX_KEYWORD_CHARACTERS = 80


class KeywordMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    term: str
    matched: bool


class KeywordAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    algorithm: Literal["keyword-coverage.v1"] = "keyword-coverage.v1"
    mode: Literal["detected", "selected"]
    score: int | None
    matched_count: int
    keyword_count: int
    keywords: list[KeywordMatch]
    limit_reached: bool = False


# Canonical display labels and common spelling/name aliases. These are explicit
# equivalences, not stemming, related skills, or inferred qualifications.
_VOCABULARY: dict[str, tuple[str, ...]] = {
    # Languages, frameworks, and application development.
    "Python": (),
    "Java": (),
    "JavaScript": ("Java Script",),
    "TypeScript": ("Type Script",),
    "C++": ("C plus plus",),
    "C#": ("C sharp", "C-sharp"),
    ".NET": ("dotnet", "dot net"),
    "Node.js": ("NodeJS", "Node JS"),
    "CI/CD": ("CI CD", "continuous integration/continuous delivery"),
    "SQL": (),
    "R": (),
    "Rust": (),
    "Ruby": (),
    "PHP": (),
    "Swift": (),
    "Kotlin": (),
    "Scala": (),
    "Golang": ("Go programming",),
    "HTML": (),
    "CSS": (),
    "React": ("React.js", "ReactJS"),
    "Angular": (),
    "Vue": ("Vue.js", "VueJS"),
    "Next.js": ("NextJS", "Next JS"),
    "Django": (),
    "Flask": (),
    "FastAPI": (),
    "Rails": ("Ruby on Rails",),
    "Spring": (),
    "GraphQL": (),
    "REST API": ("REST APIs", "RESTful API", "RESTful APIs"),
    "Microservices": (),
    "Unit testing": ("Unit-testing",),
    "Integration testing": (),
    "Test-driven development": ("Test driven development", "TDD"),
    "Software engineering": (),
    "System design": (),
    # Data, infrastructure, and technical tools.
    "PostgreSQL": ("Postgres",),
    "MySQL": (),
    "SQLite": (),
    "MongoDB": (),
    "Redis": (),
    "Elasticsearch": (),
    "Snowflake": (),
    "BigQuery": (),
    "Databricks": (),
    "Spark": ("Apache Spark",),
    "Kafka": ("Apache Kafka",),
    "Airflow": ("Apache Airflow",),
    "dbt": (),
    "AWS": ("Amazon Web Services",),
    "Azure": ("Microsoft Azure",),
    "Google Cloud": ("Google Cloud Platform", "GCP"),
    "Docker": (),
    "Kubernetes": ("k8s",),
    "Terraform": (),
    "Ansible": (),
    "Linux": (),
    "Git": (),
    "GitHub": (),
    "GitLab": (),
    "Jenkins": (),
    "DevOps": (),
    "Site reliability engineering": ("SRE",),
    "Cybersecurity": ("Cyber security",),
    "Information security": (),
    "Data engineering": (),
    "Data analysis": (),
    "Data analytics": (),
    "Data modeling": ("Data modelling",),
    "Data visualization": ("Data visualisation",),
    "Machine learning": ("Machine-learning",),
    "Deep learning": (),
    "Natural language processing": ("NLP",),
    "Computer vision": (),
    "PyTorch": (),
    "TensorFlow": (),
    "scikit-learn": ("scikit learn", "sklearn"),
    "Pandas": (),
    "NumPy": (),
    "Tableau": (),
    "Power BI": ("PowerBI",),
    "Excel": ("Microsoft Excel",),
    "Statistical analysis": (),
    "A/B testing": ("A/B tests", "AB testing"),
    # Product, design, and delivery skills.
    "Product management": (),
    "Product strategy": (),
    "Product discovery": (),
    "Product design": (),
    "Product analytics": (),
    "Product roadmap": ("Product roadmaps",),
    "User research": (),
    "UX design": ("User experience design",),
    "UI design": ("User interface design",),
    "Interaction design": (),
    "Visual design": (),
    "Graphic design": (),
    "Design systems": (),
    "Information architecture": (),
    "Usability testing": (),
    "Wireframing": (),
    "Prototyping": (),
    "Figma": (),
    "Adobe Photoshop": ("Photoshop",),
    "Adobe Illustrator": ("Illustrator",),
    "Adobe InDesign": ("InDesign",),
    "WCAG": ("Web Content Accessibility Guidelines",),
    "Project management": (),
    "Program management": (),
    "Stakeholder management": (),
    "Requirements gathering": (),
    "Agile": (),
    "Scrum": (),
    "Kanban": (),
    "Jira": (),
    "Asana": (),
    # Business, marketing, finance, and operations skills.
    "Business analysis": (),
    "Business development": (),
    "Business intelligence": (),
    "Market research": (),
    "Competitive analysis": (),
    "Customer success": (),
    "Customer support": (),
    "Account management": (),
    "Sales operations": (),
    "Salesforce": (),
    "HubSpot": (),
    "CRM": ("Customer relationship management",),
    "Digital marketing": (),
    "Content marketing": (),
    "Email marketing": (),
    "Social media marketing": (),
    "Marketing automation": (),
    "Search engine optimization": ("Search engine optimisation", "SEO"),
    "Search engine marketing": ("SEM",),
    "Google Analytics": (),
    "Copywriting": (),
    "Technical writing": (),
    "Financial analysis": (),
    "Financial modeling": ("Financial modelling",),
    "Financial reporting": (),
    "Budgeting": (),
    "Forecasting": (),
    "Accounting": (),
    "Bookkeeping": (),
    "QuickBooks": (),
    "Risk management": (),
    "Operations management": (),
    "Process improvement": (),
    "Change management": (),
    "Supply chain": (),
    "Inventory management": (),
    "Vendor management": (),
    "Procurement": (),
    "Logistics": (),
    "Lean Six Sigma": ("Six Sigma",),
    "Quality assurance": (),
    "Talent acquisition": (),
    "Human resources": (),
}


def _clean(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


_ALIASES = {
    label: tuple(dict.fromkeys(_clean(value).casefold() for value in (label, *aliases)))
    for label, aliases in _VOCABULARY.items()
}
_CANONICAL_LABEL = {alias: label for label, aliases in _ALIASES.items() for alias in aliases}


def _bounded_text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if len(value) > MAX_TEXT_CHARACTERS:
        raise ValueError(f"{field} must be at most {MAX_TEXT_CHARACTERS} characters")
    normalized = _clean(value).casefold()
    if len(normalized) > MAX_TEXT_CHARACTERS:
        raise ValueError(f"Normalized {field} must be at most {MAX_TEXT_CHARACTERS} characters")
    return normalized


def _name_character(character: str) -> bool:
    # Combining marks belong to their token even when NFKC cannot compose them.
    return (
        character.isalnum() or character in "_+#" or unicodedata.category(character).startswith("M")
    )


def _literal_position(text: str, term: str) -> int | None:
    start = text.find(term)
    while start != -1:
        end = start + len(term)
        # Dots inside names are significant; sentence-ending dots are separators.
        left_attached = start > 0 and (
            _name_character(text[start - 1])
            or (text[start - 1] == "." and start > 1 and _name_character(text[start - 2]))
        )
        right_attached = end < len(text) and (
            _name_character(text[end])
            or (text[end] == "." and end + 1 < len(text) and _name_character(text[end + 1]))
        )
        if not left_attached and not right_attached:
            return start
        start = text.find(term, start + 1)
    return None


def _first_position(text: str, aliases: tuple[str, ...]) -> int | None:
    positions = (_literal_position(text, alias) for alias in aliases)
    return min((position for position in positions if position is not None), default=None)


def _selected_terms(keywords: list[str]) -> list[tuple[str, tuple[str, ...]]]:
    if not isinstance(keywords, list):
        raise ValueError("Keywords must be a list")
    if not 1 <= len(keywords) <= MAX_KEYWORDS:
        raise ValueError(f"Choose between 1 and {MAX_KEYWORDS} keywords")
    terms = []
    seen = set()
    for value in keywords:
        if not isinstance(value, str):
            raise ValueError("Keywords must be strings")
        if len(value) > MAX_KEYWORD_CHARACTERS:
            raise ValueError(f"Each keyword must be at most {MAX_KEYWORD_CHARACTERS} characters")
        label = _clean(value)
        if not label:
            raise ValueError("Keywords must be nonblank")
        if len(label) > MAX_KEYWORD_CHARACTERS:
            raise ValueError(f"Each keyword must be at most {MAX_KEYWORD_CHARACTERS} characters")
        normalized = label.casefold()
        canonical = _CANONICAL_LABEL.get(normalized)
        identity = canonical.casefold() if canonical else normalized
        if identity not in seen:
            seen.add(identity)
            terms.append((label, _ALIASES[canonical] if canonical else (normalized,)))
    return terms


def analyze_keywords(
    job_text: str, resume_text: str, keywords: list[str] | None = None
) -> KeywordAnalysis:
    """Compare literal unique terms against résumé text without persisting data.

    Inputs are limited to 200,000 characters each, both before and after NFKC,
    whitespace normalization, and case folding. Explicit keywords must contain
    1–50 strings of 1–80 characters (raw and cleaned), and blank terms are invalid.
    Case-insensitive aliases and normalized duplicates count once; selected mode
    retains the first cleaned label and may include terms absent from the job.

    Autodetection keeps the first 50 vocabulary terms in job occurrence order
    (alphabetical for ties), reporting truncation through ``limit_reached``.
    The unweighted percentage rounds half up; no detected terms gives ``None``.
    Missing terms describe text gaps, never a person's abilities or eligibility.
    """
    job = _bounded_text(job_text, "Job text")
    resume = _bounded_text(resume_text, "Résumé text")
    limit_reached = False
    if keywords is None:
        found = []
        for label, aliases in _ALIASES.items():
            position = _first_position(job, aliases)
            if position is not None:
                found.append((position, label))
        found.sort(key=lambda item: (item[0], item[1].casefold()))
        limit_reached = len(found) > MAX_KEYWORDS
        terms = [(label, _ALIASES[label]) for _, label in found[:MAX_KEYWORDS]]
    else:
        terms = _selected_terms(keywords)

    matches = [
        KeywordMatch(term=label, matched=_first_position(resume, aliases) is not None)
        for label, aliases in terms
    ]
    keyword_count = len(matches)
    matched_count = sum(item.matched for item in matches)
    score = (200 * matched_count + keyword_count) // (2 * keyword_count) if keyword_count else None
    return KeywordAnalysis(
        mode="detected" if keywords is None else "selected",
        score=score,
        matched_count=matched_count,
        keyword_count=keyword_count,
        keywords=matches,
        limit_reached=limit_reached,
    )
