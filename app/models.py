from datetime import datetime
from pydantic import BaseModel


class MockupRecord(BaseModel):
    id: str
    project: str
    project_slug: str
    title: str
    description: str | None = None
    content_type: str
    file_path: str
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime


class MockupSummary(BaseModel):
    id: str
    project: str
    project_slug: str
    title: str
    description: str | None = None
    content_type: str
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime


class ProjectInfo(BaseModel):
    project: str
    project_slug: str
    count: int
