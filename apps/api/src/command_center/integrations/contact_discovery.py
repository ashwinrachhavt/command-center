"""Bounded Apollo/Hunter requests. Provider claims never overwrite a contact implicitly."""

from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, EmailStr, Field, TypeAdapter, ValidationError

Provider = Literal["apollo", "hunter"]


class ContactProviderError(Exception):
    def __init__(self, code: str, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


class Prospect(BaseModel):
    provider: Provider
    external_id: str
    name: str
    name_complete: bool
    title: str | None = None
    company_name: str | None = None
    domain: str | None = None
    email: str | None = None
    email_status: str = "unknown"
    linkedin_url: str | None = None
    confidence: int | None = Field(default=None, ge=0, le=100)
    sources: list[str] = Field(default_factory=list)


class ProspectPage(BaseModel):
    items: list[Prospect]
    total: int
    page: int
    has_more: bool


def professional_domain(value: str) -> str:
    value = value.strip()
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("Enter a company domain, such as example.com")
        value = parsed.hostname or ""
    try:
        domain = value.lower().removeprefix("www.").encode("idna").decode()
    except UnicodeError:
        raise ValueError("Enter a valid company domain") from None
    labels = domain.split(".")
    if (
        len(domain) > 253
        or len(labels) < 2
        or any(
            not part
            or len(part) > 63
            or not part[0].isalnum()
            or not part[-1].isalnum()
            or any(not char.isalnum() and char != "-" for char in part)
            for part in labels
        )
    ):
        raise ValueError("Enter a company domain, such as example.com")
    return domain


def _text(value: Any, limit: int = 300) -> str | None:
    return value[:limit].strip() or None if isinstance(value, str) else None


def _email(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 320:
        return None
    try:
        return str(TypeAdapter(EmailStr).validate_python(value))
    except ValidationError:
        return None


def _count(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1_000_000_000:
        return value
    raise ContactProviderError(
        "invalid_response", "The provider returned invalid pagination.", uncertain=True
    )


def _public_link(value: Any, *, linkedin: bool = False) -> str | None:
    link = _text(value, 2000)
    if not link:
        return None
    try:
        url = urlsplit(link)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return None
        if linkedin and url.hostname not in {"linkedin.com", "www.linkedin.com"}:
            return None
        return link
    except ValueError:
        return None


class ContactDiscoveryClient:
    """Fixed HTTPS hosts, no redirects/retries, small pages and redacted errors."""

    def __init__(self, http: httpx.AsyncClient, *, apollo_key: str = "", hunter_key: str = ""):
        self.http = http
        self.keys = {"apollo": apollo_key, "hunter": hunter_key}

    async def request(
        self, provider: Provider, path: str, params: dict[str, Any], *, method: str = "GET"
    ) -> dict[str, Any]:
        key = self.keys[provider]
        if not key:
            raise ContactProviderError(
                "not_configured", f"Connect {provider.title()} before discovering contacts"
            )
        headers = {"accept": "application/json"}
        query = dict(params)
        if provider == "apollo":
            host = "https://api.apollo.io/api/v1"
            headers["x-api-key"] = key
            headers["Cache-Control"] = "no-cache"
        else:
            host = "https://api.hunter.io/v2"
            query["api_key"] = key
        try:
            async with self.http.stream(
                method,
                f"{host}/{path}",
                params=query,
                headers=headers,
                follow_redirects=False,
                timeout=25,
            ) as response:
                # Never expose response bodies or credential-bearing request URLs in errors.
                if response.status_code in {401, 403}:
                    raise ContactProviderError(
                        "access_denied",
                        "The provider denied access. Check the key and endpoint permissions.",
                    )
                if response.status_code == 402:
                    raise ContactProviderError(
                        "quota_exhausted", "The provider's available credits are exhausted."
                    )
                if response.status_code == 429:
                    raise ContactProviderError(
                        "rate_or_quota_limit",
                        "Provider rate or credit limit reached. Check your provider account.",
                    )
                if response.status_code >= 500:
                    raise ContactProviderError(
                        "unavailable",
                        "The provider is unavailable; the request outcome is unknown.",
                        uncertain=True,
                    )
                if response.status_code >= 400:
                    raise ContactProviderError(
                        "invalid_request",
                        "The provider rejected this page. Check filters and account plan limits.",
                    )
                if response.status_code != 200:
                    raise ContactProviderError(
                        "unexpected_response",
                        "The provider returned an unsupported response.",
                        uncertain=True,
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise ContactProviderError(
                            "response_too_large",
                            "The provider returned too much data. Narrow the search.",
                            uncertain=True,
                        )
                import json

                data = json.loads(content)
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
                return data
        except (httpx.TimeoutException, httpx.TransportError):
            raise ContactProviderError(
                "outcome_unknown",
                "The outcome is unknown. This request will not be repeated automatically.",
                uncertain=True,
            ) from None
        except (ValueError, UnicodeError):
            raise ContactProviderError(
                "invalid_response",
                "The provider returned unreadable data; the request outcome is unknown.",
                uncertain=True,
            ) from None

    async def search(
        self, provider: Provider, *, domain: str, title: str = "", page: int = 1
    ) -> ProspectPage:
        domain = professional_domain(domain)
        if not 1 <= page <= 500:
            raise ValueError("Choose a page between 1 and 500")
        if provider == "apollo":
            params: dict[str, Any] = {
                "q_organization_domains_list[]": domain,
                "per_page": 10,
                "page": page,
            }
            if title.strip():
                params["person_titles[]"] = title.strip()
            response = await self.request(
                provider, "mixed_people/api_search", params, method="POST"
            )
            people = response.get("people")
            if not isinstance(people, list):
                raise ContactProviderError(
                    "invalid_response", "Apollo did not return a people list.", uncertain=True
                )
            items = [
                self.apollo_person(person, domain=domain, preview=True)
                for person in people[:10]
                if isinstance(person, dict) and person.get("id")
            ]
            total = _count(response.get("total_entries", 0))
        else:
            response = await self.request(
                provider,
                "domain-search",
                {"domain": domain, "type": "personal", "limit": 10, "offset": (page - 1) * 10},
            )
            data = response.get("data") or {}
            emails = data.get("emails") if isinstance(data, dict) else None
            if not isinstance(emails, list):
                raise ContactProviderError(
                    "invalid_response", "Hunter did not return an email list.", uncertain=True
                )
            items = [
                self.hunter_person(person, domain=domain, company=data.get("organization"))
                for person in emails[:10]
                if isinstance(person, dict) and person.get("value")
            ]
            meta = response.get("meta")
            total = _count(meta.get("results", 0) if isinstance(meta, dict) else 0)
        return ProspectPage(items=items, total=max(0, total), page=page, has_more=page * 10 < total)

    async def reveal_apollo(self, external_id: str) -> Prospect | None:
        if not external_id or len(external_id) > 100:
            raise ValueError("Choose a person from Apollo search")
        response = await self.request(
            "apollo",
            "people/match",
            {
                "id": external_id,
                "reveal_personal_emails": "false",
                "reveal_phone_number": "false",
                "run_waterfall_email": "false",
                "run_waterfall_phone": "false",
            },
            method="POST",
        )
        person = response.get("person")
        return (
            self.apollo_person(person, preview=False)
            if isinstance(person, dict) and person.get("id")
            else None
        )

    @staticmethod
    def apollo_person(
        person: dict[str, Any], *, domain: str | None = None, preview: bool
    ) -> Prospect:
        organization = person.get("organization") or {}
        organization = organization if isinstance(organization, dict) else {}
        first = _text(person.get("first_name"), 100) or ""
        last = _text(person.get("last_name_obfuscated" if preview else "last_name"), 100) or ""
        name = (
            (f"{first} {last}".strip() if preview else _text(person.get("name"), 200))
            or f"{first} {last}".strip()
            or "Name unavailable"
        )
        email = None if preview else _email(person.get("email"))
        if email and ("@" not in email or email.endswith("@domain.com")):
            email = None
        return Prospect(
            provider="apollo",
            external_id=str(person["id"])[:100],
            name=name,
            name_complete=not preview and name != "Name unavailable",
            title=_text(person.get("title"), 200),
            company_name=_text(organization.get("name"), 200),
            domain=_text(organization.get("primary_domain")) or domain,
            email=email,
            email_status=_text(person.get("email_status"))
            or ("not_revealed" if preview else "unknown"),
            linkedin_url=_public_link(person.get("linkedin_url"), linkedin=True),
        )

    @staticmethod
    def hunter_person(person: dict[str, Any], *, domain: str, company: Any) -> Prospect:
        name = " ".join(
            filter(
                None, [_text(person.get("first_name"), 100), _text(person.get("last_name"), 100)]
            )
        )
        email = _email(person.get("value"))
        verification = person.get("verification")
        verification = verification if isinstance(verification, dict) else {}
        sources = person.get("sources")
        sources = sources if isinstance(sources, list) else []
        confidence = person.get("confidence", person.get("score"))
        return Prospect(
            provider="hunter",
            external_id=str(person.get("email_id") or email or "")[:320],
            name=name or "Name unavailable",
            name_complete=bool(name),
            title=_text(person.get("position"), 200),
            company_name=_text(company, 200),
            domain=domain,
            email=email,
            email_status=_text(verification.get("status")) or "unknown",
            linkedin_url=_public_link(
                person.get("linkedin_url") or person.get("linkedin"), linkedin=True
            ),
            confidence=confidence
            if isinstance(confidence, int) and 0 <= confidence <= 100
            else None,
            sources=[
                url
                for source in sources[:20]
                if isinstance(source, dict) and (url := _public_link(source.get("uri")))
            ],
        )
