"""Academic Assistant HTTP entry point."""

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .database import database_path, migrate, schema_version


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.database_path = database_path()
    migrate(app.state.database_path)
    yield


app = FastAPI(title="Academic Assistant", lifespan=lifespan)


@app.get("/health")
def health():
    try:
        version = schema_version(app.state.database_path)
    except sqlite3.Error:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok", "schema_version": version}
