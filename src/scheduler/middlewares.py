import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pyinstrument import Profiler
from pyinstrument.renderers.html import HTMLRenderer
from pyinstrument.renderers.speedscope import SpeedscopeRenderer

from fastapi import FastAPI, Request

def register_middlewares(app: FastAPI):
    ...
    if app.settings.PROFILING_ENABLED is True:

        @app.middleware("http")
        async def profile_request(request: Request, call_next: Callable):
            """Profile the current request

            Taken from https://pyinstrument.readthedocs.io/en/latest/guide.html#profile-a-web-request-in-fastapi
            with small improvements.

            """
            # we map a profile type to a file extension, as well as a pyinstrument profile renderer
            profile_type_to_ext = {"html": "html", "speedscope": "speedscope.json"}
            profile_type_to_renderer = {
                "html": HTMLRenderer,
                "speedscope": SpeedscopeRenderer,
            }

            # if the `profile=true` HTTP query argument is passed, we profile the request
            if request.query_params.get("profile", False):

                # The default profile format is speedscope
                profile_type = request.query_params.get("profile_format", "speedscope")

                # we profile the request along with all additional middlewares, by interrupting
                # the program every 1ms1 and records the entire stack at that point
                with Profiler(interval=0.001, async_mode="enabled") as profiler:
                    response = await call_next(request)

                # we dump the profiling into a file
                extension = profile_type_to_ext[profile_type]
                renderer = profile_type_to_renderer[profile_type]()
                with open(f"profile.{extension}", "w") as out:
                    out.write(profiler.output(renderer=renderer))
                return response

            # Proceed without profiling
            return await call_next(request)