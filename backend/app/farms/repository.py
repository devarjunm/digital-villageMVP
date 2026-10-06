"""Farm persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.farms.models import Farm, SoilTest


class FarmRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, farm_id: uuid.UUID, *, include_deleted: bool = False) -> Farm | None:
        farm = self.db.get(Farm, farm_id)
        if farm is None:
            return None
        if farm.deleted_at is not None and not include_deleted:
            return None
        return farm

    def list_for_owner(self, owner_id: uuid.UUID) -> list[Farm]:
        return list(
            self.db.execute(
                select(Farm)
                .where(Farm.owner_id == owner_id, Farm.deleted_at.is_(None))
                .order_by(Farm.created_at.desc())
            )
            .scalars()
            .all()
        )

    def create(self, **fields) -> Farm:
        farm = Farm(**fields)
        self.db.add(farm)
        self.db.flush()
        return farm

    def soft_delete(self, farm: Farm) -> None:
        farm.deleted_at = utcnow()
        for crop in farm.crops:
            crop.deleted_at = utcnow()
        self.db.flush()

    # ------------------------------------------------------------ soil tests
    def latest_soil_test(self, farm_id: uuid.UUID) -> SoilTest | None:
        return (
            self.db.execute(
                select(SoilTest)
                .where(SoilTest.farm_id == farm_id)
                .order_by(SoilTest.tested_on.desc())
            )
            .scalars()
            .first()
        )

    def add_soil_test(self, **fields) -> SoilTest:
        test = SoilTest(**fields)
        self.db.add(test)
        self.db.flush()
        return test
