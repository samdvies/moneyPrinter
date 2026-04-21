"""Rejected: async function with await expression."""
import asyncio


def compute_signal(snapshot, params):
    # Can't actually await here in a sync function; AsyncFunctionDef fires first
    # if we use async def.  Use an AsyncFunctionDef to exercise Await path.
    pass


async def _helper(snapshot, params):
    await asyncio.sleep(0)
    return float(snapshot["price"])
