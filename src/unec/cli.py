from __future__ import annotations

import asyncio
from collections import defaultdict

import typer
from rich.console import Console
from rich.table import Table

from .config import load_settings
from .scraper.client import AuthError, UnecClient
from .scraper.models import DayOfWeek, Lesson, WeekParity
from .scraper.parsers.schedule import parse_schedule

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

DAY_NAMES_RU = {
    DayOfWeek.MON: "Понедельник",
    DayOfWeek.TUE: "Вторник",
    DayOfWeek.WED: "Среда",
    DayOfWeek.THU: "Четверг",
    DayOfWeek.FRI: "Пятница",
    DayOfWeek.SAT: "Суббота",
    DayOfWeek.SUN: "Воскресенье",
}

WEEK_BADGE = {
    WeekParity.NORMAL: "",
    WeekParity.UPPER: " [yellow](верх)[/yellow]",
    WeekParity.LOWER: " [cyan](низ)[/cyan]",
}


@app.command()
def schedule(year_id: int | None = typer.Option(None, "--year", help="eduYear ID; defaults to current")):
    """Print the class schedule for the given (or current) academic year."""
    asyncio.run(_run_schedule(year_id))


async def _run_schedule(year_id: int | None) -> None:
    settings = load_settings()
    if not settings.unec_username or not settings.unec_password:
        console.print(
            "[red]Set UNEC_USERNAME and UNEC_PASSWORD in .env to use the dev CLI.[/red]"
        )
        raise typer.Exit(code=1)
    async with UnecClient(base_url=settings.unec_base_url) as client:
        try:
            with console.status("[bold]Logging in…[/bold]"):
                await client.login(
                    settings.unec_username,
                    settings.unec_password.get_secret_value(),
                )
        except AuthError as exc:
            console.print(f"[red]Login failed:[/red] {exc}")
            raise typer.Exit(code=1)

        with console.status("[bold]Fetching schedule…[/bold]"):
            params = {"eduYear": year_id} if year_id else None
            html = await client.get("/az/schedule", params=params)

    lessons = parse_schedule(html)
    if not lessons:
        console.print("[yellow]No lessons found in the schedule.[/yellow]")
        return

    _render_schedule(lessons)


def _render_schedule(lessons: list[Lesson]) -> None:
    by_day: dict[DayOfWeek, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        by_day[lesson.day].append(lesson)

    for day in DayOfWeek:
        day_lessons = sorted(by_day.get(day, []), key=lambda l: l.start)
        if not day_lessons:
            continue
        table = Table(
            title=f"[bold]{DAY_NAMES_RU[day]}[/bold]",
            title_justify="left",
            show_header=True,
            header_style="bold magenta",
            show_lines=True,
        )
        table.add_column("Время", style="cyan", no_wrap=True)
        table.add_column("Предмет")
        table.add_column("Тип", style="green")
        table.add_column("Аудитория", style="yellow")
        table.add_column("Преподаватель")

        for lesson in day_lessons:
            time_cell = f"{lesson.start:%H:%M}–{lesson.end:%H:%M}{WEEK_BADGE[lesson.week_parity]}"
            room_cell = lesson.room or ""
            if lesson.building:
                room_cell = f"{room_cell} ({lesson.building})"
            table.add_row(
                time_cell,
                lesson.subject,
                lesson.lesson_type or "",
                room_cell,
                lesson.teacher or "",
            )
        console.print(table)
        console.print()


@app.command("rotate-kek")
def rotate_kek() -> None:
    """Re-wrap every per-user DEK with the current primary KEK key.

    Run after prepending a new key to FERNET_KEYS. Once this completes,
    every users.encrypted_dek row is re-encrypted with the new primary,
    and the old key can be safely dropped from FERNET_KEYS.
    """
    asyncio.run(_run_rotate_kek())


async def _run_rotate_kek() -> None:
    from sqlalchemy import select, update

    from .core.security import kek_rewrap
    from .db.base import get_session_factory
    from .db.models import User

    factory = get_session_factory()
    rotated = 0
    async with factory() as session:
        rows = (await session.execute(select(User).where(User.encrypted_dek.is_not(None)))).scalars().all()
        for user in rows:
            new_blob = kek_rewrap(user.encrypted_dek)
            if new_blob == user.encrypted_dek:
                continue
            await session.execute(
                update(User).where(User.id == user.id).values(encrypted_dek=new_blob)
            )
            rotated += 1
        await session.commit()
    console.print(f"[green]✓[/green] Re-wrapped {rotated} DEK(s) with the current primary KEK")


@app.command("gen-vapid")
def gen_vapid() -> None:
    """Generate a fresh VAPID (P-256) keypair for Web Push.

    Run once. Take the PRIVATE block (PEM, multi-line) and put it into
    `secrets/vapid_private_key`. Take the PUBLIC line (single string) and
    set `VAPID_PUBLIC_KEY` in `.env`. Both must match — rotating means
    every existing push subscription becomes useless.
    """
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")

    # Use plain print() (not Rich) for the keys themselves so terminal
    # wrapping never breaks them on copy-paste. Rich is only for headings.
    console.print("\n[bold cyan]── PRIVATE ──[/bold cyan]")
    print(priv_pem.strip())
    console.print("\n[bold cyan]── PUBLIC (single line, 87 chars) ──[/bold cyan]")
    print(pub_b64)
    console.print(
        f"\n[dim]Public key length: {len(pub_b64)} chars. "
        "Save the private block (including BEGIN/END lines) to "
        "secrets/vapid_private_key, set VAPID_PUBLIC_KEY=<public> in .env.[/dim]"
    )


if __name__ == "__main__":
    app()
