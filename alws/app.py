import asyncio

import importlib
import logging
import threading

import sentry_sdk

from fastapi import FastAPI
from starlette.middleware.exceptions import ExceptionMiddleware

from alws import routers
from alws.auth import AuthRoutes
from alws.auth.backend import CookieBackend, BearerBackend
from alws.auth.oauth.github import get_github_oauth_client
from alws.auth.schemas import UserRead
from alws.config import settings
from alws.middlewares import handlers
from alws.test_scheduler import TestTaskScheduler


logging.basicConfig(level=settings.logging_level)

ROUTERS = [importlib.import_module(f'alws.routers.{module}')
           for module in routers.__all__]
APP_PREFIX = '/api/v1'
AUTH_PREFIX = APP_PREFIX + '/auth'
AUTH_TAG = 'auth'

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        environment=settings.sentry_environment,
    )


app = FastAPI()
app.add_middleware(ExceptionMiddleware, handlers=handlers)


if settings.test_task_scheduler_enabled:
    scheduler = None
    terminate_event = threading.Event()
    graceful_terminate_event = threading.Event()

    @app.on_event('startup')
    async def startup():
        global scheduler, terminate_event, graceful_terminate_event
        scheduler = TestTaskScheduler(terminate_event, graceful_terminate_event)
        asyncio.create_task(scheduler.run())

    @app.on_event('shutdown')
    async def shutdown():
        global terminate_event
        terminate_event.set()

for module in ROUTERS:
    for router_type in (
        'router',
        'public_router',
        'copr_router',
    ):
        router = getattr(module, router_type, None)
        if not router:
            continue
        router_params = {'router': router, 'prefix': APP_PREFIX}
        # for correct working COPR features,
        # we don't need prefix for this router
        if router_type == 'copr_router':
            router_params.pop('prefix')
        app.include_router(**router_params)

github_client = get_github_oauth_client(
    settings.github_client, settings.github_client_secret)

app.include_router(
    AuthRoutes.get_oauth_router(
        github_client,
        CookieBackend,
        settings.jwt_secret,
        redirect_url=settings.github_callback_url,
        associate_by_email=True
    ),
    prefix=AUTH_PREFIX + '/github',
    tags=[AUTH_TAG],
)
app.include_router(
    AuthRoutes.get_oauth_associate_router(
        github_client,
        UserRead,
        settings.jwt_secret,
        requires_verification=False
    ),
    prefix=AUTH_PREFIX + '/associate/github',
    tags=[AUTH_TAG],
)
app.include_router(
    AuthRoutes.get_auth_router(
        BearerBackend
    ),
    prefix=AUTH_PREFIX,
    tags=[AUTH_TAG],
)
