from __future__ import annotations

from pydantic import BaseModel


class AllowArbitraryTypeConfig(BaseModel.Config):
    # Used by pydantic to allow arbitrary type e.g. pd.DataFrame
    arbitrary_types_allowed = True
