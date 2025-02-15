if not os.path.exists("/home/appuser/.cache/ms-playwright"):
    os.system("playwright install chromium")

st.write("Playwright is ready to use!")

import streamlit as st
st.set_page_config(layout="wide")
import asyncio
import logging
from urllib.parse import urlparse, urljoin
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup
import re
import hashlib

try:
    from readability import Document
except ImportError:
    Document = None

logging.basicConfig(level=logging.ERROR, format="%(asctime)s [%(levelname)s] %(message)s")

visited_urls = set()
visited_lock = asyncio.Lock()
FIXED_DEPTH = 2
seen_content_hashes = set()

def extract_main_content(html):
    if Document:
        try:
            doc = Document(html)
            return doc.summary(html_partial=True)
        except Exception as e:
            logging.error(f"Readability extraction failed: {e}")
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article")
    if article:
        return article.get_text(separator="\n", strip=True)
    main = soup.find("main")
    if main:
        return main.get_text(separator="\n", strip=True)
    return soup.get_text(separator="\n", strip=True)

def clean_content(text):
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    seen = set()
    deduped = []
    for para in paragraphs:
        if para not in seen:
            seen.add(para)
            deduped.append(para)
    return "\n\n".join(deduped)

def extract_structured_data(url, html):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    content = extract_main_content(html)
    content = re.sub(r'\s+', ' ', content).strip()
    content = clean_content(content)
    return {"url": url, "title": title, "content": content}

async def iterative_scrape(start_url, max_pages, progress_callback=None):
    queue = asyncio.Queue()
    await queue.put((start_url, FIXED_DEPTH))
    results = []
    semaphore = asyncio.Semaphore(10)
    allowed_domain = urlparse(start_url).netloc

    async with AsyncWebCrawler() as crawler:
        while not queue.empty():
            if len(visited_urls) >= max_pages:
                break
            url, depth = await queue.get()
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                queue.task_done()
                continue
            async with visited_lock:
                if url in visited_urls:
                    queue.task_done()
                    continue
                visited_urls.add(url)
            try:
                async with semaphore:
                    result = await crawler.arun(url=url)
                html = getattr(result, "html", "")
                if html:
                    data = extract_structured_data(url, html)
                    content_hash = hashlib.md5(data.get("content").encode("utf-8")).hexdigest()
                    if content_hash not in seen_content_hashes:
                        seen_content_hashes.add(content_hash)
                        results.append(data)
                if progress_callback:
                    progress_callback(len(visited_urls))
                if depth > 0 and html:
                    soup = BeautifulSoup(html, "html.parser")
                    for a in soup.find_all("a", href=True):
                        link = a["href"]
                        full_link = urljoin(url, link)
                        parsed_link = urlparse(full_link)
                        if parsed_link.scheme in ("http", "https") and parsed_link.netloc == allowed_domain:
                            await queue.put((full_link, depth - 1))
            except asyncio.TimeoutError:
                logging.error(f"Timeout error while scraping {url}. Retrying later.")
                await queue.put((url, depth))
            except Exception as e:
                logging.error(f"Error scraping {url}: {e}")
            finally:
                queue.task_done()
    return results

def aggregate_structured_data(scrape_results):
    return "\n\n".join(
        f"Title: {data.get('title')}\nContent: {data.get('content')}"
        for data in scrape_results
    )

if "scrape_results" not in st.session_state:
    st.session_state.scrape_results = None

st.title("Website Scraper")
url_input = st.text_input("Enter the URL to scrape", "")
max_pages = st.number_input("Max Pages to Scrape", min_value=1, value=1, step=1)

if st.button("Scrape Website"):
    if not url_input:
        st.error("Please enter a URL to scrape.")
    else:
        if not url_input.startswith("http://") and not url_input.startswith("https://"):
            url_input = "https://" + url_input
        parsed_input = urlparse(url_input)
        if parsed_input.scheme not in ("http", "https"):
            st.error("Please enter a valid URL (must start with http:// or https://).")
        else:
            visited_urls.clear()
            seen_content_hashes.clear()
            st.session_state.scrape_results = None
            progress_text = st.empty()
            def update_progress(count):
                progress_text.text(f"Pages scraped so far: {count}")
            with st.spinner("Scraping in progress..."):
                scrape_results = asyncio.run(iterative_scrape(url_input, max_pages, progress_callback=update_progress))
            st.session_state.scrape_results = scrape_results
            st.success(f"Scraped {len(scrape_results)} page(s).")

if st.session_state.scrape_results:
    aggregated_text = aggregate_structured_data(st.session_state.scrape_results)
    domain = urlparse(url_input).netloc
    file_name = f"scraped_{domain}.txt" if domain else "scraped_data.txt"
    st.download_button(
        label="Download as TXT",
        data=aggregated_text,
        file_name=file_name,
        mime="text/plain",
    )
