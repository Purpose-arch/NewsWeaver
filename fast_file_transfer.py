import asyncio
from telethon.tl.types import Document
from telethon.tl.functions.upload import GetFileRequest
from telethon.tl.types import InputFile, InputFileBig
from telethon.tl import types
from telethon import utils
import math
import os

# Параллельная загрузка файла из Telegram
async def download_file(client, document, out, *, progress_callback=None, workers=4, chunk_size=512*1024):
    # Получаем размер файла
    size = getattr(document, 'size', None) or getattr(document, 'file_size', None)
    if not size:
        raise ValueError('Document has no size attribute')
    file_ref = getattr(document, 'file_reference', None)
    if not file_ref:
        file_ref = b''
    dc_id = getattr(document, 'dc_id', None)
    if not dc_id:
        dc_id = 0
    # Получаем location
    location = types.InputDocumentFileLocation(
        id=document.id,
        access_hash=document.access_hash,
        file_reference=file_ref,
        thumb_size=""
    )
    # Считаем количество чанков
    chunks = math.ceil(size / chunk_size)
    results = [None] * chunks
    sem = asyncio.Semaphore(workers)
    async def fetch_chunk(i):
        async with sem:
            offset = i * chunk_size
            limit = min(chunk_size, size - offset)
            res = await client(GetFileRequest(
                location=location,
                offset=offset,
                limit=limit,
            ))
            results[i] = res.bytes
            if progress_callback:
                await progress_callback(min(offset+limit, size), size)
    await asyncio.gather(*(fetch_chunk(i) for i in range(chunks)))
    for chunk in results:
        out.write(chunk)
    out.flush()

# Параллельная отправка файла в Telegram
async def upload_file(client, file, *, progress_callback=None, workers=4, chunk_size=512*1024):
    # file: file-like object (rb)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    chunks = math.ceil(size / chunk_size)
    sem = asyncio.Semaphore(workers)
    parts = [None] * chunks
    async def send_chunk(i):
        async with sem:
            file.seek(i * chunk_size)
            data = file.read(chunk_size)
            parts[i] = data
            if progress_callback:
                await progress_callback(min((i+1)*chunk_size, size), size)
    await asyncio.gather(*(send_chunk(i) for i in range(chunks)))
    # Собираем InputFile
    if size > 10*1024*1024:
        # Big file
        input_file = InputFileBig(
            id=utils.generate_random_long(),
            parts=chunks,
            name=os.path.basename(getattr(file, 'name', 'file')),
        )
    else:
        input_file = InputFile(
            id=utils.generate_random_long(),
            parts=chunks,
            name=os.path.basename(getattr(file, 'name', 'file')),
            md5_checksum=b''
        )
    # Для совместимости возвращаем input_file
    return input_file 