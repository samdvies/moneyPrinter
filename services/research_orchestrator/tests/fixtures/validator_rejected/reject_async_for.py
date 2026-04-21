"""Rejected: async for inside an async function."""


async def compute_signal(snapshot, params):
    async for item in snapshot["stream"]:
        return float(item)
    return None
