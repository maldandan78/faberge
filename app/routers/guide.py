"""ИИ-гид: генерация рассказа (YandexGPT) и диалог с подсказками."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from .. import models as m
from .. import schemas as sch
from ..db import get_session
from ..services import UpstreamError, llm, tts

router = APIRouter(prefix="/guide", tags=["ИИ-гид"])


@router.post("/story", response_model=sch.StoryResponse, summary="Сгенерировать рассказ об экспонате")
async def generate_story(req: sch.StoryRequest, session: AsyncSession = Depends(get_session)) -> sch.StoryResponse:
    if req.exhibit_id is None and not req.label_slug:
        raise HTTPException(status_code=400, detail="Укажите exhibit_id или label_slug.")

    ex = None
    if req.exhibit_id is not None:
        ex = await crud.get_exhibit_orm(session, req.exhibit_id)
    elif req.label_slug:
        ex = await crud.get_exhibit_by_slug_orm(session, req.label_slug)
    if ex is None:
        raise HTTPException(status_code=404, detail="Экспонат не найден.")

    try:
        text, questions, model = await llm.generate_story(
            crud.exhibit_to_dict(ex), req.style.value, req.language, req.max_questions
        )
        audio_url = None
        if req.include_audio:
            audio_url = (await tts.synthesize(text)).audio_url
    except UpstreamError as exc:
        raise HTTPException(status_code=502, detail=exc.message)

    return sch.StoryResponse(
        exhibit_id=ex.id,
        label_slug=ex.label_slug,
        style=req.style,
        text=text,
        suggested_questions=questions,
        audio_url=audio_url,
        model=model,
        generated_at=datetime.now(timezone.utc),
    )


@router.post("/chat", response_model=sch.ChatResponse, summary="Диалог с ИИ-гидом")
async def chat(req: sch.ChatRequest, session: AsyncSession = Depends(get_session)) -> sch.ChatResponse:
    # Сессия диалога.
    sess: Optional[m.GuideSession] = None
    if req.session_id is not None:
        sess = await session.get(m.GuideSession, req.session_id)
    context = req.context
    if sess is None:
        sess = m.GuideSession(context=context.model_dump() if context else None)
        session.add(sess)
        await session.flush()
    elif context is None and sess.context:
        context = sch.GuideContext(**sess.context)

    # Контекст-обоснование для модели.
    grounding = ""
    exhibit_dict = None
    if context is not None:
        ex = None
        if context.exhibit_id is not None:
            ex = await crud.get_exhibit_orm(session, context.exhibit_id)
        elif context.label_slug:
            ex = await crud.get_exhibit_by_slug_orm(session, context.label_slug)
        if ex is not None:
            exhibit_dict = crud.exhibit_to_dict(ex)
            grounding = " ".join(p for p in (ex.short_description, ex.raw_history) if p)
            context = sch.GuideContext(exhibit_id=ex.id, label_slug=ex.label_slug, hall_id=context.hall_id)
        elif context.hall_id is not None:
            hall = await session.get(m.Hall, context.hall_id)
            if hall is not None:
                grounding = hall.description or hall.name or ""

    # История диалога.
    history: List[Tuple[str, str]] = []
    if req.history:
        history = [(msg.role, msg.content) for msg in req.history]
    else:
        rows = (
            await session.execute(
                select(m.GuideMessage).where(m.GuideMessage.session_id == sess.id).order_by(m.GuideMessage.id)
            )
        ).scalars().all()
        history = [(r.role, r.content) for r in rows]

    try:
        answer, questions = await llm.chat(
            grounding, history, req.message, req.language, req.max_questions, exhibit_dict
        )
    except UpstreamError as exc:
        raise HTTPException(status_code=502, detail=exc.message)

    session.add(m.GuideMessage(session_id=sess.id, role="user", content=req.message))
    session.add(m.GuideMessage(session_id=sess.id, role="assistant", content=answer))
    sess.last_activity = datetime.now(timezone.utc)
    if context is not None:
        sess.context = context.model_dump()
    await session.commit()

    return sch.ChatResponse(session_id=sess.id, answer=answer, suggested_questions=questions, context=context)
