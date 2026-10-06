"""Farmer profile persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.farmers.models import FarmerProfile


class FarmerRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_user(self, user_id: uuid.UUID) -> FarmerProfile | None:
        return self.db.execute(
            select(FarmerProfile).where(FarmerProfile.user_id == user_id)
        ).scalar_one_or_none()

    def get(self, profile_id: uuid.UUID) -> FarmerProfile | None:
        return self.db.get(FarmerProfile, profile_id)

    def create(self, **fields) -> FarmerProfile:
        profile = FarmerProfile(**fields)
        self.db.add(profile)
        self.db.flush()
        return profile

    def ensure_for_user(self, *, user) -> FarmerProfile:
        profile = self.get_by_user(user.id)
        if profile is None:
            profile = self.create(
                user_id=user.id,
                display_name=user.full_name,
                state=None,
                primary_crops=[],
                interests=[],
            )
        return profile
