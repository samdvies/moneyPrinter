"""Public pydantic models for the auth subsystem. No secrets land here."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Operator(BaseModel):
    """Authenticated dashboard operator. Excludes password_hash by design."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    email: str
    created_at: datetime
