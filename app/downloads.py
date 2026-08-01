import pathlib

from app.drive import DriveDownloadError, download_to_spool, get_metadata
from app.gotenberg import GotenbergError, convert_to_pdf
from app.zipstreamer import ArchiveEntry
from gcr_downloader.files import allocate_unique_name, conversion_kind, is_video_file, safe_filename
from gcr_downloader.models import Course, CourseFile, DownloadOptions, DownloadReport, ItemResult


def prepare_download(
    drive,
    course: Course,
    files: list[CourseFile],
    options: DownloadOptions,
) -> tuple[list[ArchiveEntry], DownloadReport]:
    entries: list[ArchiveEntry] = []
    report = DownloadReport()
    used_paths: set[str] = set()
    course_directory = safe_filename(course.name)

    for course_file in files:
        try:
            metadata = get_metadata(drive, course_file.id, course_file.title_hint)
        except DriveDownloadError:
            report.add(ItemResult(course.name, course_file.title_hint, "download_failed", message="Failed to fetch file metadata"))
            continue

        source_name = metadata.name
        if not options.include_videos and is_video_file(source_name, metadata.mime_type):
            report.add(ItemResult(course.name, source_name, "skipped_video", message="Video excluded"))
            continue

        try:
            source = download_to_spool(drive, course_file.id, metadata.mime_type)
        except DriveDownloadError:
            report.add(ItemResult(course.name, source_name, "download_failed", message="Download failed after three attempts"))
            continue

        kind = conversion_kind(source_name, options)
        raw_source_path = f"{course_directory}/{source_name}"
        if kind is None:
            source_path = allocate_unique_name(raw_source_path, used_paths)
            entries.append(ArchiveEntry(source_path, source))
            report.add(ItemResult(course.name, source_name, "downloaded", (source_path,)))
            continue

        try:
            pdf = convert_to_pdf(source, source_name)
        except GotenbergError:
            source_path = allocate_unique_name(raw_source_path, used_paths)
            entries.append(ArchiveEntry(source_path, source))
            report.add(ItemResult(course.name, source_name, "conversion_failed", (source_path,), "Document conversion failed"))
            continue

        raw_pdf_path = pathlib.PurePosixPath(raw_source_path).with_suffix(".pdf").as_posix()
        pdf_path = allocate_unique_name(raw_pdf_path, used_paths)
        outputs: list[str] = []
        if options.keep_originals:
            source_path = allocate_unique_name(raw_source_path, used_paths)
            entries.append(ArchiveEntry(source_path, source))
            outputs.append(source_path)
        else:
            source.close()
        entries.append(ArchiveEntry(pdf_path, pdf))
        outputs.append(pdf_path)
        report.add(ItemResult(course.name, source_name, "converted", tuple(outputs)))

    return entries, report
