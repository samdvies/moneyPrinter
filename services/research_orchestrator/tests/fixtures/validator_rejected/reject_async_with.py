"""Rejected: async with inside an async function."""


async def compute_signal(snapshot, params):
    async with snapshot["ctx"] as ctx:
        return float(ctx["price"])
