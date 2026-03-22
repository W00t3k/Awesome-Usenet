from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

router = APIRouter()
templates: Jinja2Templates | None = None  # injected by main.py


def set_templates(t: Jinja2Templates) -> None:
    global templates
    templates = t


def _ctx(request: Request) -> dict:
    from app.config import settings
    return {"request": request, "app_title": settings.app_title}


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", _ctx(request))


@router.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("integrations.html", _ctx(request))


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("chat.html", _ctx(request))


@router.get("/usenet", response_class=HTMLResponse)
async def usenet_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("usenet.html", _ctx(request))


@router.get("/tv", response_class=HTMLResponse)
async def tv_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("tv.html", _ctx(request))
