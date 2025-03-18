import os
import aiofiles
import aiohttp
import asyncio
from bs4 import BeautifulSoup

DOMAIN = "http://0114.xy08.my"
BASE_URL = DOMAIN + "/XiuRen/"
CONCURRENCY_LIMIT = 100  # 提高并发连接数
ALBUM_CONCURRENCY = 5    # 专辑页面的并发数
PAGE_BATCH_SIZE = 10     # 子页面批量探测数量
RETRIES = 3
TIMEOUT = 30

async def download_image(session, url, folder, counter):
    for attempt in range(RETRIES):
        try:
            async with session.get(DOMAIN + url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as response:
                if response.status == 200:
                    file_name = url.split("/")[-1]
                    file_path = os.path.join(folder, f"{counter}_{file_name}")
                    
                    async with aiofiles.open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(1024*1024):
                            await f.write(chunk)
                    print(f"✅ Downloaded {url}")
                    return True
        except Exception as e:
            print(f"⚠️ Attempt {attempt+1} failed: {e}, URL: {url}")
            if attempt == RETRIES - 1:
                print(f"❌ Failed after {RETRIES} retries: {url}")
                return False
            await asyncio.sleep(2 ** attempt)
    return False

async def fetch_page(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as response:
            return await response.text() if response.status == 200 else None
    except Exception as e:
        print(f"⚠️ Failed to fetch {url}: {e}")
        return None

async def process_subpage(session, url, folder, counter_j):
    html = await fetch_page(session, url)
    if not html: return

    try:
        soup = BeautifulSoup(html, 'html.parser')
        images = soup.select("body > div.main > div > div > div:nth-child(6) > p img")
        tasks = []
        for idx, img in enumerate(images, 1):
            if img.get('src'):
                tasks.append(
                    download_image(session, img['src'], folder, f"{counter_j}{idx:04d}")
                )
        await asyncio.gather(*tasks)
    except Exception as e:
        print(f"⚠️ Parsing failed: {url} - {e}")

async def process_album(session, i):
    main_url = f"{BASE_URL}{i}.html"
    html = await fetch_page(session, main_url)
    if not html: return

    try:
        soup = BeautifulSoup(html, 'html.parser')
        title_tag = soup.select_one("body > div.main > div > div > div:nth-child(2) > h1")
        if not title_tag: return

        folder_name = title_tag.text.strip()
        folder = os.path.join("./downloads", folder_name)
        if os.path.exists(folder):
            print(f"⏩ 目录已存在: {folder_name}, 跳过...")
            return
        os.makedirs(folder, exist_ok=True)

        # 批量探测子页面
        j = 1
        while True:
            batch_tasks = []
            for dj in range(PAGE_BATCH_SIZE):
                sub_url = f"{BASE_URL}{i}_{j + dj}.html"
                batch_tasks.append(fetch_page(session, sub_url))
            
            pages = await asyncio.gather(*batch_tasks)
            found = any(pages)
            
            # 并发处理存在的子页面
            process_tasks = []
            for dj, page in enumerate(pages):
                if page:
                    current_j = j + dj
                    process_tasks.append(
                        process_subpage(session, f"{BASE_URL}{i}_{current_j}.html", folder, current_j)
                    )
            
            await asyncio.gather(*process_tasks)
            
            if not found:
                break
            j += PAGE_BATCH_SIZE

    except Exception as e:
        print(f"⚠️ Album processing error: {main_url} - {e}")

async def main():
    # 优化连接池配置
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY_LIMIT,
        limit_per_host=CONCURRENCY_LIMIT,
        ssl=False
    )
    
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=TIMEOUT)
    ) as session:
        # 使用信号量控制专辑并发
        semaphore = asyncio.Semaphore(ALBUM_CONCURRENCY)
        tasks = []
        for i in range(17060, 0, -1):
            tasks.append(asyncio.create_task(
                process_album_wrapped(session, i, semaphore)
            ))
        await asyncio.gather(*tasks)

async def process_album_wrapped(session, i, semaphore):
    async with semaphore:
        await process_album(session, i)

if __name__ == "__main__":
    asyncio.run(main())
