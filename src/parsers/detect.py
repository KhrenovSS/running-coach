# Определение типа файла тренировки по содержимому (Sniff workout file kind by content) — #78, 11.09.2026
#
# Загрузка верила расширению: `.exe`, переименованный в `.tcx`, уходил в парсер и в raw/. Теперь
# содержимое сверяется с расширением ДО сохранения сырья. (Content sniff before raw save / parse.)

FIT_MAGIC_OFFSET = 8            # байты 8..12 заголовка FIT — сигнатура ".FIT" (FIT header data-type field)
FIT_MAGIC = b".FIT"
_TCX_STARTS = (b"<?xml", b"<TrainingCenterDatabase")
_BOM = b"\xef\xbb\xbf"


def sniff_kind(contents: bytes) -> str | None:
    """'fit' | 'tcx' | None по первым байтам (без разбора всего файла). (Kind by leading bytes.)"""
    if not contents:
        return None
    if contents[FIT_MAGIC_OFFSET:FIT_MAGIC_OFFSET + len(FIT_MAGIC)] == FIT_MAGIC:
        return "fit"
    head = contents[:256]
    if head.startswith(_BOM):
        head = head[len(_BOM):]
    head = head.lstrip()
    if head.startswith(_TCX_STARTS):
        return "tcx"
    return None
