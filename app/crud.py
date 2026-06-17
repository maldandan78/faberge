"""Запросы к БД и сериализация ORM → Pydantic."""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import models as m
from . import schemas as sch


# ── Сериализаторы ────────────────────────────────────────────────────────────
def to_hall(h: m.Hall, showcase_count: Optional[int] = None, exhibit_count: Optional[int] = None) -> sch.Hall:
    return sch.Hall(
        id=h.id,
        hall_number=h.hall_number,
        name=h.name,
        description=h.description,
        level=h.level,
        cover_image_url=h.cover_image_url,
        showcase_count=showcase_count,
        exhibit_count=exhibit_count,
    )


def to_hall_brief(h: m.Hall) -> sch.HallBrief:
    return sch.HallBrief(id=h.id, hall_number=h.hall_number, name=h.name)


def to_showcase(s: m.Showcase, exhibit_count: Optional[int] = None) -> sch.Showcase:
    return sch.Showcase(
        id=s.id, hall_id=s.hall_id, showcase_number=s.showcase_number, name=s.name, exhibit_count=exhibit_count
    )


def to_exhibit_summary(e: m.Exhibit) -> sch.ExhibitSummary:
    hall_id = e.showcase.hall_id if e.showcase else None
    return sch.ExhibitSummary(
        id=e.id,
        label_slug=e.label_slug,
        name=e.name,
        year_created=e.year_created,
        master_name=e.master_name,
        thumbnail_url=e.image_url,
        hall_id=hall_id,
        showcase_id=e.showcase_id,
    )


def to_exhibit(e: m.Exhibit, admin: bool = False) -> sch.Exhibit:
    hall = to_hall_brief(e.showcase.hall) if e.showcase and e.showcase.hall else None
    showcase = sch.ShowcaseBrief(id=e.showcase.id, showcase_number=e.showcase.showcase_number) if e.showcase else None
    images = [sch.Image(url=i.url, alt=i.alt, width=i.width, height=i.height) for i in e.images]
    cls = sch.ExhibitAdmin if admin else sch.Exhibit
    data = dict(
        id=e.id,
        label_slug=e.label_slug,
        name=e.name,
        year_created=e.year_created,
        master_name=e.master_name,
        material=e.material,
        short_description=e.short_description,
        image_url=e.image_url,
        images=images,
        model_3d_url=e.model_3d_url,
        model_3d_embed=e.model_3d_embed,
        audio_url=e.audio_url,
        source_url=e.source_url,
        hall=hall,
        showcase=showcase,
    )
    if admin:
        data["raw_history"] = e.raw_history
    return cls(**data)


def exhibit_to_dict(e: m.Exhibit) -> Dict:
    return {
        "id": e.id,
        "label_slug": e.label_slug,
        "name": e.name,
        "year_created": e.year_created,
        "master_name": e.master_name,
        "material": e.material,
        "short_description": e.short_description,
        "raw_history": e.raw_history,
    }


# ── Загрузчики с нужными relationship ────────────────────────────────────────
_EXHIBIT_FULL = (
    selectinload(m.Exhibit.showcase).selectinload(m.Showcase.hall),
    selectinload(m.Exhibit.images),
)
_EXHIBIT_SUMMARY = (selectinload(m.Exhibit.showcase),)


# ── Счётчики ─────────────────────────────────────────────────────────────────
async def _hall_counts(session: AsyncSession, hall_ids: Sequence[int]) -> Tuple[Dict[int, int], Dict[int, int]]:
    if not hall_ids:
        return {}, {}
    sc_rows = await session.execute(
        select(m.Showcase.hall_id, func.count(m.Showcase.id)).where(m.Showcase.hall_id.in_(hall_ids)).group_by(m.Showcase.hall_id)
    )
    showcase_counts = {hid: cnt for hid, cnt in sc_rows.all()}
    ex_rows = await session.execute(
        select(m.Showcase.hall_id, func.count(m.Exhibit.id))
        .join(m.Exhibit, m.Exhibit.showcase_id == m.Showcase.id)
        .where(m.Showcase.hall_id.in_(hall_ids))
        .group_by(m.Showcase.hall_id)
    )
    exhibit_counts = {hid: cnt for hid, cnt in ex_rows.all()}
    return showcase_counts, exhibit_counts


async def _showcase_exhibit_counts(session: AsyncSession, showcase_ids: Sequence[int]) -> Dict[int, int]:
    if not showcase_ids:
        return {}
    rows = await session.execute(
        select(m.Exhibit.showcase_id, func.count(m.Exhibit.id))
        .where(m.Exhibit.showcase_id.in_(showcase_ids))
        .group_by(m.Exhibit.showcase_id)
    )
    return {sid: cnt for sid, cnt in rows.all()}


# ── Карта / навигация ────────────────────────────────────────────────────────
async def get_map(session: AsyncSession) -> sch.MapResponse:
    halls = (
        (await session.execute(select(m.Hall).options(selectinload(m.Hall.showcases)).order_by(m.Hall.hall_number)))
        .scalars()
        .all()
    )
    hall_ids = [h.id for h in halls]
    showcase_counts, exhibit_counts = await _hall_counts(session, hall_ids)
    all_showcase_ids = [s.id for h in halls for s in h.showcases]
    sc_ex_counts = await _showcase_exhibit_counts(session, all_showcase_ids)

    map_halls: List[sch.MapHall] = []
    for h in halls:
        showcases = [
            sch.Showcase(
                id=s.id, hall_id=s.hall_id, showcase_number=s.showcase_number, name=s.name,
                exhibit_count=sc_ex_counts.get(s.id, 0),
            )
            for s in h.showcases
        ]
        map_halls.append(
            sch.MapHall(
                id=h.id, hall_number=h.hall_number, name=h.name, description=h.description, level=h.level,
                cover_image_url=h.cover_image_url, showcase_count=showcase_counts.get(h.id, 0),
                exhibit_count=exhibit_counts.get(h.id, 0), showcases=showcases,
            )
        )
    return sch.MapResponse(halls=map_halls)


async def list_halls(session: AsyncSession, limit: int, offset: int) -> sch.HallListResponse:
    total = (await session.execute(select(func.count(m.Hall.id)))).scalar_one()
    halls = (
        (await session.execute(select(m.Hall).order_by(m.Hall.hall_number).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    showcase_counts, exhibit_counts = await _hall_counts(session, [h.id for h in halls])
    items = [to_hall(h, showcase_counts.get(h.id, 0), exhibit_counts.get(h.id, 0)) for h in halls]
    return sch.HallListResponse(items=items, total=total, limit=limit, offset=offset)


async def get_hall(session: AsyncSession, hall_id: int) -> Optional[sch.HallDetail]:
    hall = (
        await session.execute(select(m.Hall).options(selectinload(m.Hall.showcases)).where(m.Hall.id == hall_id))
    ).scalar_one_or_none()
    if hall is None:
        return None
    showcase_counts, exhibit_counts = await _hall_counts(session, [hall.id])
    sc_ex_counts = await _showcase_exhibit_counts(session, [s.id for s in hall.showcases])
    showcases = [to_showcase(s, sc_ex_counts.get(s.id, 0)) for s in hall.showcases]
    return sch.HallDetail(
        id=hall.id, hall_number=hall.hall_number, name=hall.name, description=hall.description, level=hall.level,
        cover_image_url=hall.cover_image_url, showcase_count=showcase_counts.get(hall.id, 0),
        exhibit_count=exhibit_counts.get(hall.id, 0), showcases=showcases,
    )


async def hall_exists(session: AsyncSession, hall_id: int) -> bool:
    return (await session.execute(select(m.Hall.id).where(m.Hall.id == hall_id))).scalar_one_or_none() is not None


async def list_hall_showcases(session: AsyncSession, hall_id: int, limit: int, offset: int) -> sch.ShowcaseListResponse:
    total = (await session.execute(select(func.count(m.Showcase.id)).where(m.Showcase.hall_id == hall_id))).scalar_one()
    showcases = (
        (
            await session.execute(
                select(m.Showcase).where(m.Showcase.hall_id == hall_id).order_by(m.Showcase.showcase_number).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    counts = await _showcase_exhibit_counts(session, [s.id for s in showcases])
    items = [to_showcase(s, counts.get(s.id, 0)) for s in showcases]
    return sch.ShowcaseListResponse(items=items, total=total, limit=limit, offset=offset)


async def list_showcases(
    session: AsyncSession, limit: int, offset: int, hall_id: Optional[int] = None
) -> sch.ShowcaseListResponse:
    flt = (m.Showcase.hall_id == hall_id) if hall_id is not None else None
    count_stmt = select(func.count(m.Showcase.id))
    list_stmt = select(m.Showcase).order_by(m.Showcase.hall_id, m.Showcase.showcase_number)
    if flt is not None:
        count_stmt = count_stmt.where(flt)
        list_stmt = list_stmt.where(flt)
    total = (await session.execute(count_stmt)).scalar_one()
    showcases = (await session.execute(list_stmt.limit(limit).offset(offset))).scalars().all()
    counts = await _showcase_exhibit_counts(session, [s.id for s in showcases])
    items = [to_showcase(s, counts.get(s.id, 0)) for s in showcases]
    return sch.ShowcaseListResponse(items=items, total=total, limit=limit, offset=offset)


async def get_showcase(session: AsyncSession, showcase_id: int) -> Optional[sch.ShowcaseDetail]:
    s = (
        await session.execute(
            select(m.Showcase)
            .options(selectinload(m.Showcase.hall), selectinload(m.Showcase.exhibits).selectinload(m.Exhibit.showcase))
            .where(m.Showcase.id == showcase_id)
        )
    ).scalar_one_or_none()
    if s is None:
        return None
    counts = await _showcase_exhibit_counts(session, [s.id])
    exhibits = [to_exhibit_summary(e) for e in s.exhibits]
    return sch.ShowcaseDetail(
        id=s.id, hall_id=s.hall_id, showcase_number=s.showcase_number, name=s.name,
        exhibit_count=counts.get(s.id, 0), hall=to_hall_brief(s.hall) if s.hall else None, exhibits=exhibits,
    )


async def showcase_exists(session: AsyncSession, showcase_id: int) -> bool:
    return (await session.execute(select(m.Showcase.id).where(m.Showcase.id == showcase_id))).scalar_one_or_none() is not None


# ── Экспонаты ────────────────────────────────────────────────────────────────
async def _exhibits_page(session: AsyncSession, base_filter, limit: int, offset: int) -> sch.ExhibitListResponse:
    total = (await session.execute(select(func.count()).select_from(select(m.Exhibit.id).where(base_filter).subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                select(m.Exhibit).options(*_EXHIBIT_SUMMARY).where(base_filter).order_by(m.Exhibit.id).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return sch.ExhibitListResponse(items=[to_exhibit_summary(e) for e in rows], total=total, limit=limit, offset=offset)


async def list_hall_exhibits(session: AsyncSession, hall_id: int, limit: int, offset: int) -> sch.ExhibitListResponse:
    flt = m.Exhibit.showcase_id.in_(select(m.Showcase.id).where(m.Showcase.hall_id == hall_id))
    return await _exhibits_page(session, flt, limit, offset)


async def list_showcase_exhibits(session: AsyncSession, showcase_id: int, limit: int, offset: int) -> sch.ExhibitListResponse:
    return await _exhibits_page(session, m.Exhibit.showcase_id == showcase_id, limit, offset)


async def list_exhibits(
    session: AsyncSession, limit: int, offset: int, hall_id: Optional[int], showcase_id: Optional[int],
    label_slug: Optional[str], q: Optional[str],
) -> sch.ExhibitListResponse:
    conds = []
    if hall_id is not None:
        conds.append(m.Exhibit.showcase_id.in_(select(m.Showcase.id).where(m.Showcase.hall_id == hall_id)))
    if showcase_id is not None:
        conds.append(m.Exhibit.showcase_id == showcase_id)
    if label_slug:
        conds.append(m.Exhibit.label_slug == label_slug)
    if q:
        conds.append(m.Exhibit.name.ilike(f"%{q}%"))
    flt = and_(*conds) if conds else (m.Exhibit.id == m.Exhibit.id)
    return await _exhibits_page(session, flt, limit, offset)


async def get_exhibit_orm(session: AsyncSession, exhibit_id: int) -> Optional[m.Exhibit]:
    return (
        await session.execute(select(m.Exhibit).options(*_EXHIBIT_FULL).where(m.Exhibit.id == exhibit_id))
    ).scalar_one_or_none()


async def get_exhibit_by_slug_orm(session: AsyncSession, label_slug: str) -> Optional[m.Exhibit]:
    return (
        await session.execute(select(m.Exhibit).options(*_EXHIBIT_FULL).where(m.Exhibit.label_slug == label_slug))
    ).scalar_one_or_none()


async def list_related(session: AsyncSession, exhibit_id: int, limit: int) -> Optional[sch.ExhibitListResponse]:
    hall_id = (
        await session.execute(
            select(m.Showcase.hall_id).join(m.Exhibit, m.Exhibit.showcase_id == m.Showcase.id).where(m.Exhibit.id == exhibit_id)
        )
    ).scalar_one_or_none()
    if hall_id is None:
        # экспонат не найден или не привязан к витрине/залу
        exists = (await session.execute(select(m.Exhibit.id).where(m.Exhibit.id == exhibit_id))).scalar_one_or_none()
        if exists is None:
            return None
        return sch.ExhibitListResponse(items=[], total=0, limit=limit, offset=0)
    flt = and_(
        m.Exhibit.id != exhibit_id,
        m.Exhibit.showcase_id.in_(select(m.Showcase.id).where(m.Showcase.hall_id == hall_id)),
    )
    return await _exhibits_page(session, flt, limit, 0)


async def all_label_slugs(session: AsyncSession) -> List[str]:
    rows = await session.execute(select(m.Exhibit.label_slug).where(m.Exhibit.label_slug.isnot(None)).order_by(m.Exhibit.id))
    return [r[0] for r in rows.all()]


async def names_by_slugs(session: AsyncSession, slugs: Sequence[str]) -> Dict[str, str]:
    if not slugs:
        return {}
    rows = await session.execute(select(m.Exhibit.label_slug, m.Exhibit.name).where(m.Exhibit.label_slug.in_(list(slugs))))
    return {slug: name for slug, name in rows.all()}


# ── Поиск ────────────────────────────────────────────────────────────────────
async def search(session: AsyncSession, q: str, limit: int) -> sch.SearchResponse:
    like = f"%{q}%"
    halls = (
        (await session.execute(select(m.Hall).where(or_(m.Hall.name.ilike(like), m.Hall.description.ilike(like))).order_by(m.Hall.hall_number).limit(limit)))
        .scalars()
        .all()
    )
    exhibits = (
        (
            await session.execute(
                select(m.Exhibit).options(*_EXHIBIT_SUMMARY).where(or_(m.Exhibit.name.ilike(like), m.Exhibit.master_name.ilike(like))).order_by(m.Exhibit.id).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    hall_items = [to_hall(h) for h in halls]
    exhibit_items = [to_exhibit_summary(e) for e in exhibits]
    return sch.SearchResponse(query=q, halls=hall_items, exhibits=exhibit_items, total=len(hall_items) + len(exhibit_items))


# ── Администрирование (CRUD) ─────────────────────────────────────────────────
async def create_hall(session: AsyncSession, data: sch.HallCreate) -> sch.HallDetail:
    hall = m.Hall(hall_number=data.hall_number, name=data.name, description=data.description, level=data.level)
    session.add(hall)
    await session.commit()
    result = await get_hall(session, hall.id)
    assert result is not None
    return result


async def create_showcase(session: AsyncSession, data: sch.ShowcaseCreate) -> sch.ShowcaseDetail:
    sc = m.Showcase(hall_id=data.hall_id, showcase_number=data.showcase_number, name=data.name)
    session.add(sc)
    await session.commit()
    result = await get_showcase(session, sc.id)
    assert result is not None
    return result


async def create_exhibit(session: AsyncSession, data: sch.ExhibitCreate) -> m.Exhibit:
    ex = m.Exhibit(**data.model_dump())
    session.add(ex)
    await session.commit()
    return await get_exhibit_orm(session, ex.id)  # type: ignore[return-value]


async def replace_exhibit(session: AsyncSession, ex: m.Exhibit, data: sch.ExhibitUpdate) -> m.Exhibit:
    for field, value in data.model_dump().items():
        setattr(ex, field, value)
    await session.commit()
    return await get_exhibit_orm(session, ex.id)  # type: ignore[return-value]


async def patch_exhibit(session: AsyncSession, ex: m.Exhibit, data: sch.ExhibitPatch) -> m.Exhibit:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ex, field, value)
    await session.commit()
    return await get_exhibit_orm(session, ex.id)  # type: ignore[return-value]


async def delete_exhibit(session: AsyncSession, ex: m.Exhibit) -> None:
    await session.delete(ex)
    await session.commit()


def collect_image_urls(ex: m.Exhibit) -> List[str]:
    """Все URL изображений экспоната (первичное + галерея) — для очистки хранилища.

    Требует, чтобы коллекция ``ex.images`` была уже загружена (см. ``_EXHIBIT_FULL``).
    """
    urls = [img.url for img in ex.images]
    if ex.image_url:
        urls.append(ex.image_url)
    return urls


async def get_exhibit_image(session: AsyncSession, exhibit_id: int, image_id: int) -> Optional[m.ExhibitImage]:
    return (
        await session.execute(
            select(m.ExhibitImage).where(
                m.ExhibitImage.id == image_id, m.ExhibitImage.exhibit_id == exhibit_id
            )
        )
    ).scalar_one_or_none()


async def delete_exhibit_image(session: AsyncSession, img: m.ExhibitImage) -> None:
    # Если удаляем первичное изображение — снимаем ссылку с exhibits.image_url.
    if img.is_primary:
        ex = await session.get(m.Exhibit, img.exhibit_id)
        if ex is not None and ex.image_url == img.url:
            ex.image_url = None
    await session.delete(img)
    await session.commit()


async def add_exhibit_image(session: AsyncSession, exhibit_id: int, url: str, is_primary: bool) -> None:
    if is_primary:
        ex = await session.get(m.Exhibit, exhibit_id)
        if ex is not None:
            ex.image_url = url
    pos = (await session.execute(select(func.coalesce(func.max(m.ExhibitImage.position), -1)).where(m.ExhibitImage.exhibit_id == exhibit_id))).scalar_one() + 1
    session.add(m.ExhibitImage(exhibit_id=exhibit_id, url=url, is_primary=is_primary, position=pos))
    await session.commit()


# ── Телеметрия / аналитика ───────────────────────────────────────────────────
async def insert_events(session: AsyncSession, batch: sch.EventBatch) -> int:
    objs = [
        m.Event(
            session_id=batch.session_id, type=e.type, exhibit_id=e.exhibit_id, hall_id=e.hall_id,
            label_slug=e.label_slug, props=e.props, ts=e.ts,
        )
        for e in batch.events
    ]
    session.add_all(objs)
    await session.commit()
    return len(objs)


async def analytics_overview(session: AsyncSession, dfrom: Optional[date], dto: Optional[date]) -> sch.AnalyticsOverview:
    def _range(col):
        conds = []
        if dfrom is not None:
            conds.append(col >= dfrom)
        if dto is not None:
            conds.append(col < dto)
        return and_(*conds) if conds else None

    ev_range = _range(m.Event.ts)

    async def _count(flt):
        stmt = select(func.count()).select_from(m.Event)
        if ev_range is not None:
            stmt = stmt.where(ev_range)
        if flt is not None:
            stmt = stmt.where(flt)
        return (await session.execute(stmt)).scalar_one()

    total_sessions_stmt = select(func.count(func.distinct(m.Event.session_id))).select_from(m.Event)
    if ev_range is not None:
        total_sessions_stmt = total_sessions_stmt.where(ev_range)
    total_sessions = (await session.execute(total_sessions_stmt)).scalar_one()

    total_recognitions = await _count(m.Event.type == "recognition")
    success = await _count(and_(m.Event.type == "recognition", cast(m.Event.props["recognized"].astext, String) == "true"))
    total_audio_plays = await _count(m.Event.type == "audio_play")

    msg_stmt = select(func.count()).select_from(m.GuideMessage).where(m.GuideMessage.role == "user")
    if dfrom is not None:
        msg_stmt = msg_stmt.where(m.GuideMessage.created_at >= dfrom)
    if dto is not None:
        msg_stmt = msg_stmt.where(m.GuideMessage.created_at < dto)
    total_chat_messages = (await session.execute(msg_stmt)).scalar_one()

    top_exhibits = await _top_items(session, m.Event.exhibit_id, "exhibit_view", m.Exhibit, ev_range)
    top_halls = await _top_items(session, m.Event.hall_id, "hall_view", m.Hall, ev_range)

    rate = round(success / total_recognitions, 4) if total_recognitions else 0.0
    return sch.AnalyticsOverview(
        from_=dfrom.isoformat() if dfrom else None,
        to=dto.isoformat() if dto else None,
        total_sessions=total_sessions,
        total_recognitions=total_recognitions,
        recognition_success_rate=rate,
        total_chat_messages=total_chat_messages,
        total_audio_plays=total_audio_plays,
        top_exhibits=top_exhibits,
        top_halls=top_halls,
    )


async def _top_items(session: AsyncSession, id_col, ev_type: str, entity, ev_range) -> List[sch.AnalyticsTopItem]:
    stmt = select(id_col, func.count().label("c")).select_from(m.Event).where(m.Event.type == ev_type, id_col.isnot(None))
    if ev_range is not None:
        stmt = stmt.where(ev_range)
    stmt = stmt.group_by(id_col).order_by(func.count().desc()).limit(5)
    rows = (await session.execute(stmt)).all()
    items: List[sch.AnalyticsTopItem] = []
    for ent_id, count in rows:
        name = (await session.execute(select(entity.name).where(entity.id == ent_id))).scalar_one_or_none()
        items.append(sch.AnalyticsTopItem(id=ent_id, name=name, count=count))
    return items
