"""Recognize bounded public posting URLs without fetching or trusting page instructions."""

import re
from typing import Literal, TypedDict
from urllib.parse import parse_qs, unquote, urlsplit

JobPlatform = Literal["greenhouse", "lever", "ashby", "workday", "icims"]


class JobIdentityValue(TypedDict):
    platform: JobPlatform
    organization: str
    posting_id: str
    canonical_url: str


_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z")
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
_TENANT = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_GREENHOUSE = {"boards.greenhouse.io", "job-boards.greenhouse.io"}


def _path_segments(path: str) -> list[str] | None:
    path = path.removesuffix("/")
    if not path.startswith("/"):
        return None
    segments = [unquote(segment) for segment in path[1:].split("/")]
    if len(segments) > 16 or any(not _SEGMENT.fullmatch(segment) for segment in segments):
        return None
    return segments


def posting_identity(url: str) -> JobIdentityValue | None:
    """Only known URL shapes establish identity; labels and query tracking never do."""
    if not url or len(url) > 4096 or re.search(r"[\s\x00-\x1f\x7f-\x9f\ufeff\\]", url):
        return None
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            return None
    except ValueError:
        return None
    path = _path_segments(parsed.path)
    if path is None:
        return None
    origin = f"https://{host}"
    platform: JobPlatform
    organization: str
    posting_id: str
    canonical: str
    if host in _GREENHOUSE:
        platform = "greenhouse"
        if len(path) == 3 and path[1] == "jobs" and path[2].isascii() and path[2].isdigit():
            organization, posting_id = path[0], path[2]
        elif path == ["embed", "job_app"]:
            try:
                query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=4096)
            except ValueError:
                return None
            organizations, identifiers = query.get("for", []), query.get("token", [])
            if (
                len(organizations) != 1
                or len(identifiers) != 1
                or not _SEGMENT.fullmatch(organizations[0])
                or not re.fullmatch(r"[0-9]{1,200}", identifiers[0])
            ):
                return None
            organization, posting_id = organizations[0], identifiers[0]
        else:
            return None
        canonical = f"https://job-boards.greenhouse.io/{organization}/jobs/{posting_id}"
    elif host in {"jobs.lever.co", "jobs.eu.lever.co", "jobs.ashbyhq.com"}:
        platform = "ashby" if host == "jobs.ashbyhq.com" else "lever"
        suffix = "application" if platform == "ashby" else "apply"
        if (
            len(path) not in {2, 3}
            or not _UUID.fullmatch(path[1])
            or (len(path) == 3 and path[2] != suffix)
        ):
            return None
        organization, posting_id = path[0], path[1].lower()
        canonical = f"{origin}/{organization}/{posting_id}"
    elif re.fullmatch(rf"{_TENANT}\.wd[0-9]{{1,61}}\.myworkdayjobs\.com", host):
        platform = "workday"
        base = path[1:] if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", path[0]) else path
        if (
            len(base) < 4
            or base[1] != "job"
            or (len(base) > 4 and base[4] != "apply")
            or "_" not in base[3]
        ):
            return None
        posting_id = base[3].rsplit("_", 1)[1]
        if not re.fullmatch(r"[A-Za-z0-9-]{1,200}", posting_id):
            return None
        organization = f"{host}@{base[0]}"
        prefix = path[: len(path) - len(base)]
        canonical = origin + "/" + "/".join(prefix + base[:4])
    elif re.fullmatch(rf"{_TENANT}\.icims\.com", host):
        platform = "icims"
        if len(path) < 2 or path[0] != "jobs" or not re.fullmatch(r"[0-9]+", path[1]):
            return None
        organization, posting_id = host, path[1]
        canonical = f"{origin}/jobs/{posting_id}"
    else:
        return None
    if len(organization) > 200 or len(canonical) > 2000:
        return None
    return {
        "platform": platform,
        "organization": organization,
        "posting_id": posting_id,
        "canonical_url": canonical,
    }


def identity_key(identity: JobIdentityValue) -> tuple[str, str, str]:
    return identity["platform"], identity["organization"], identity["posting_id"]


def stored_identity(value: object) -> JobIdentityValue | None:
    if not isinstance(value, dict) or not isinstance(value.get("canonical_url"), str):
        return None
    parsed = posting_identity(value["canonical_url"])
    return parsed if parsed == value else None


def observed_identity(page_url: str, supplied: JobIdentityValue | None) -> JobIdentityValue | None:
    """Bind recognized metadata to the stored capture; only embed IDs need safe metadata."""
    detected = posting_identity(page_url)
    if supplied is None:
        return detected
    canonical = posting_identity(supplied["canonical_url"])
    if canonical != supplied:
        raise ValueError("Choose a recognized canonical job posting")
    if detected is not None:
        if identity_key(detected) != identity_key(supplied):
            raise ValueError("The job posting does not match this captured page")
        return detected
    # Browser snapshots intentionally omit query data. For the fixed Greenhouse
    # embed route, retain only the reader's validated organization and numeric ID.
    parsed = urlsplit(page_url)
    if (
        parsed.scheme == "https"
        and parsed.hostname in _GREENHOUSE
        and parsed.username is None
        and parsed.password is None
        and parsed.port in {None, 443}
        and _path_segments(parsed.path) == ["embed", "job_app"]
        and supplied["platform"] == "greenhouse"
    ):
        return canonical
    raise ValueError("The job posting does not match this captured page")
