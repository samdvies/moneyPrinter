"""Rejected: AsyncFunctionDef is not allowed."""


async def compute_signal(snapshot, params):
    return float(snapshot["price"])
