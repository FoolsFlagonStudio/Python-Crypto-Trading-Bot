import asyncio
import platform


def apply_windows_event_loop_fix():
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
