from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

ItemStatus = Literal[
    "downloaded",
    "converted",
    "skipped_video",
    "skipped_existing",
    "dry_run",
    "download_failed",
    "conversion_failed",
]


@dataclass(frozen=True)
class Course:
    id: str
    name: str
    state: str


@dataclass(frozen=True)
class CourseFile:
    id: str
    title_hint: str


@dataclass(frozen=True)
class DownloadOptions:
    include_videos: bool = True
    convert_word: bool = False
    convert_powerpoint: bool = False
    keep_originals: bool = True


@dataclass(frozen=True)
class ItemResult:
    course_name: str
    source_name: str
    status: ItemStatus
    output_paths: tuple[str, ...] = ()
    message: str = ""


@dataclass
class DownloadReport:
    items: list[ItemResult] = field(default_factory=list)

    def add(self, result: ItemResult) -> None:
        self.items.append(result)

    def summary(self) -> dict[str, int]:
        return dict(Counter(item.status for item in self.items))

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "summary": self.summary(),
            "items": [
                {
                    "course_name": item.course_name,
                    "source_name": item.source_name,
                    "status": item.status,
                    "output_paths": list(item.output_paths),
                    "message": item.message,
                }
                for item in self.items
            ],
        }
