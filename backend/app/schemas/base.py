"""
Shared base schemas.

Every endpoint that returns a metric, rank, or explanation MUST
return a response that inherits from VersionedResponse so that
all outputs are traceable and reproducible.
"""

from datetime import date

from pydantic import BaseModel, Field


class VersionedResponse(BaseModel):
    """
    Base for all metric/ranking/explanation responses.

    These four fields are non-negotiable on every such response:
    - data_version:        which data snapshot was used
    - rule_version:        which rule-set version was applied
    - calculation_version: which metric-engine version was used
    - as_of_date:          the evaluation date of the data
    """

    data_version: str = Field(description="Data snapshot version identifier")
    rule_version: str = Field(description="Rule-set version applied to produce this result")
    calculation_version: str = Field(description="Metric calculation engine version")
    as_of_date: date = Field(description="Evaluation date for the underlying data")
