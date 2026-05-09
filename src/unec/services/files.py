"""Browse + download teaching materials from UNEC's /az/files page."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import FilesPageCache
from ..scraper.client import UnecClient
from ..scraper.parsers.files import (
    FILE_TYPE_ORDER,
    FilesOption,
    FilesSubject,
    FilesTeacher,
    FilesTheme,
    ParsedFilesPage,
    parse_files_page,
)
from .unec_session import UnecSessionManager

# UNEC's own JS makes this hidden XHR when the subject dropdown changes.
# The endpoint name is misspelled in their code ("Teahers" not "Teachers"),
# we have to spell it the same way.
_TEACHERS_BY_SUBJECT_PATH = "/az/getTeahersBySubject"

# Splice the teachers AJAX response back into the main page's teacherList
# <select> so the rest of the parser sees a normally-populated dropdown.
_TEACHER_LIST_RE = re.compile(
    r'(<select[^>]*id="teacherList"[^>]*>)(.*?)(</select>)',
    re.DOTALL,
)
_TEACHER_PLACEHOLDER = '<option value="">-- Müəllimi seçin --</option>'

# Cached pages are considered fresh for 30 days — UNEC materials are normally
# stable for a whole semester. Manual `force=true` bypasses the freshness
# check and re-fetches.
CACHE_TTL_DAYS = 30


def _params_hash(params: dict[str, str]) -> str:
    canon = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.sha256(canon.encode()).hexdigest()[:32]


def _splice_teachers(main_html: str, teacher_options_html: str) -> str:
    """Replace empty <select id='teacherList'> block with fetched options."""
    return _TEACHER_LIST_RE.sub(
        lambda m: (
            f"{m.group(1)}{_TEACHER_PLACEHOLDER}{teacher_options_html}{m.group(3)}"
        ),
        main_html,
        count=1,
    )


_PAGE_LINK_RE = re.compile(r"/az/files/page/(\d+)")
# Safety cap: in practice UNEC subjects have under 30 themes total.
_MAX_PAGES = 50


def _detect_max_page(html: str) -> int:
    """Find the highest page number referenced in the pagination block."""
    matches = _PAGE_LINK_RE.findall(html)
    if not matches:
        return 1
    return min(_MAX_PAGES, max(int(m) for m in matches))


def _serialize(page: ParsedFilesPage) -> str:
    return json.dumps(asdict(page), ensure_ascii=False)


def _deserialize(raw: str) -> ParsedFilesPage:
    data = json.loads(raw)
    return ParsedFilesPage(
        years=[FilesOption(**o) for o in data["years"]],
        semesters=[FilesOption(**o) for o in data["semesters"]],
        subjects=[FilesSubject(**o) for o in data["subjects"]],
        teachers=[FilesTeacher(**o) for o in data["teachers"]],
        themes=[FilesTheme(**o) for o in data["themes"]],
    )


@dataclass(slots=True)
class DownloadedFile:
    body: bytes
    content_type: str
    filename: str


async def list_options(
    db_session: AsyncSession,
    redis_client: redis.Redis,
    *,
    user_id: uuid.UUID,
    edu_year_id: str | None = None,
    edu_semester_id: str | None = None,
    subject: str | None = None,
    subj_id: str | None = None,
    teacher: str | None = None,
    force: bool = False,
) -> tuple[ParsedFilesPage, datetime | None]:
    """Cascade of filter options + themes table for the current selection.

    Returns ``(page, last_synced_at)``. last_synced_at is None when the
    response just came from UNEC live; non-None when served from the
    Postgres cache. ``force=True`` skips the cache read.
    """
    params: dict[str, str] = {}
    if edu_year_id:
        params["eduYearFiles"] = edu_year_id
    if edu_semester_id:
        params["eduSemester"] = edu_semester_id
    if subject:
        params["subject"] = subject
    if subj_id:
        params["subjId"] = subj_id
    if teacher:
        params["teachers"] = teacher

    h = _params_hash(params)

    if not force:
        cached = await db_session.get(FilesPageCache, (user_id, h))
        if cached is not None:
            age = datetime.now(UTC) - cached.last_synced_at
            if age < timedelta(days=CACHE_TTL_DAYS):
                try:
                    return _deserialize(cached.html), cached.last_synced_at
                except (json.JSONDecodeError, KeyError):
                    # Pre-paginated cache (raw HTML) — silently rebuild.
                    pass

    manager = UnecSessionManager(redis_client)

    # When subject is selected but teacher isn't, UNEC's JS fires a hidden
    # XHR to fetch teachers for that subject. We replicate it server-side
    # and splice the response into the main HTML so the rest of the parser
    # sees a normally-populated teacherList.
    needs_teachers = bool(subject) and not teacher

    async def _do(client: UnecClient) -> ParsedFilesPage:
        # Page 1 — has dropdowns + first slice of themes.
        main_html = await client.get("/az/files", params=params)
        if needs_teachers and subj_id:
            teacher_options = await client.post(
                _TEACHERS_BY_SUBJECT_PATH,
                data={"id": subject, "data-subject": subj_id},
                xhr=True,
            )
            main_html = _splice_teachers(main_html, teacher_options)
        page = parse_files_page(main_html)

        # Pagination: themes split across /az/files/page/N. Fetch the rest
        # (we already have page 1) and append theme rows in order.
        max_page = _detect_max_page(main_html)
        for n in range(2, max_page + 1):
            extra_html = await client.get(f"/az/files/page/{n}", params=params)
            page.themes.extend(parse_files_page(extra_html).themes)
        return page

    page = await manager.fetch(user_id, db_session, _do)
    serialized = _serialize(page)

    # Upsert the cache row — keep one row per (user, params hash).
    row = await db_session.get(FilesPageCache, (user_id, h))
    if row is None:
        db_session.add(
            FilesPageCache(
                user_id=user_id, params_hash=h, html=serialized, last_synced_at=datetime.now(UTC)
            )
        )
    else:
        row.html = serialized
        row.last_synced_at = datetime.now(UTC)
    await db_session.commit()

    return page, None


async def download_theme_file(
    db_session: AsyncSession,
    redis_client: redis.Redis,
    *,
    user_id: uuid.UUID,
    theme_id: str,
    file_type: str,
) -> DownloadedFile:
    """Two-step download — register intent, then GET the actual bytes."""
    if file_type not in FILE_TYPE_ORDER:
        raise ValueError(f"unknown file_type: {file_type}")

    manager = UnecSessionManager(redis_client)

    async def _do(client: UnecClient) -> tuple[bytes, str, str | None]:
        await client.post_multipart(
            "/az/downloadFileForTheme",
            fields={"selectedFileType": file_type, "selectedThemeId": theme_id},
        )
        return await client.download(f"/az/downloadOneFile/{theme_id}/{file_type}")

    body, ctype, filename = await manager.fetch(user_id, db_session, _do)

    if not filename:
        ext = _ext_from_content_type(ctype)
        filename = f"{file_type}-{theme_id}{ext}"

    return DownloadedFile(body=body, content_type=ctype, filename=filename)


async def download_arbitrary(
    db_session: AsyncSession,
    redis_client: redis.Redis,
    *,
    user_id: uuid.UUID,
    path: str,
) -> DownloadedFile:
    """Download a UNEC file by absolute path (e.g. teacher's syllabus link).

    Locked down to the /ASEU/* tree where UNEC keeps uploaded materials.
    Rejects '..' segments outright — even though the UNEC server is the
    real authority on what each session can read, defence in depth.
    """
    if not path.startswith("/ASEU/"):
        raise ValueError("path must point inside /ASEU/")
    if ".." in path:
        raise ValueError("path traversal segments are not allowed")

    manager = UnecSessionManager(redis_client)

    async def _do(client: UnecClient) -> tuple[bytes, str, str | None]:
        return await client.download(path)

    body, ctype, filename = await manager.fetch(user_id, db_session, _do)
    if not filename:
        filename = path.rsplit("/", 1)[-1] or "download"
    return DownloadedFile(body=body, content_type=ctype, filename=filename)


def _ext_from_content_type(ctype: str) -> str:
    base = ctype.split(";", 1)[0].strip().lower()
    mapping = {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-powerpoint": ".pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/zip": ".zip",
    }
    return mapping.get(base, "")
