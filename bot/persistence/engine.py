from __future__ import annotations
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL is None:
    raise RuntimeError("DATABASE_URL is not set in environment variables.")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,          
    future=True,
)

async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,
)
