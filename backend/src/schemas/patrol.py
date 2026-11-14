from pydantic import BaseModel, Field


class PatrolBatchInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=1, max_length=5000)


class DispatchInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    job_id: int
    patrol_batch_id: int
    quota: int = Field(ge=1, le=5000)
