import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from config import settings

DATABASE_URL = f"mysql+aiomysql://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"

# A dictionary to store engines by running loop id to prevent cross-loop connection sharing
_loop_engines = {}

def get_loop_engine():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Fallback if no loop is running
        return create_async_engine(
            DATABASE_URL,
            pool_size=5,
            max_overflow=5,
            pool_recycle=3600,
            echo=False
        )
    
    loop_id = id(loop)
    if loop_id not in _loop_engines:
        _loop_engines[loop_id] = create_async_engine(
            DATABASE_URL,
            pool_size=5,
            max_overflow=5,
            pool_recycle=3600,
            echo=False
        )
    return _loop_engines[loop_id]

# Singleton engine export for backward compatibility with migrations/index scripts
engine = get_loop_engine()

def AsyncSessionLocal(**kwargs):
    current_engine = get_loop_engine()
    factory = async_sessionmaker(
        bind=current_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    return factory(**kwargs)

async def dispose_loop_engine():
    try:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        if loop_id in _loop_engines:
            current_engine = _loop_engines.pop(loop_id)
            await current_engine.dispose()
    except Exception:
        pass

Base = declarative_base()

async def get_db_session():
    async with AsyncSessionLocal() as session:
        yield session
        await session.commit()
