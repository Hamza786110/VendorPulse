import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "contractguard")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI is not set — check your .env file")
    app.state.mongo_client = AsyncIOMotorClient(MONGODB_URI)
    app.state.db = app.state.mongo_client[MONGODB_DB_NAME]
    yield
    app.state.mongo_client.close()


app = FastAPI(title="ContractGuard API", lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok", "message": "ContractGuard API is running"}


@app.get("/health")
async def health_check():
    try:
        await app.state.mongo_client.admin.command("ping")
        db_status = "connected"
        healthy = True
    except Exception as e:
        db_status = f"error: {e}"
        healthy = False

    return {"api": "ok", "database": db_status, "healthy": healthy}