import streamlit as st
import asyncio
import logging
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import re
import hashlib
import os

# Ensure Playwright browsers are installed
if not os.path.exists("/home/appuser/.cache/ms-playwright"):
    os.system("playwright install chromium")

st.set_page_config(layout="wide")

try:
    from readability import Document
except ImportError:
    Document = None

# Crawl4AI imports based on documentation recommendations
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, RateLimiter, CrawlerMonitor, DisplayMode
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher

logging.basicConfig(level=logging.ERROR, format="%(asctime)s [%(levelname)s] %(message)s")

# Utility functions for content extraction
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

# Dispatcher and run configuration based on Crawl4AI docs (&#8203;:contentReference[oaicite:2]{index=2})
def get_dispatcher():
    rate_limiter = RateLimiter(
        base_delay=(1.0, 3.0),  # randomized delay between requests
        max_delay=60.0,         # cap for backoff delay
        max_retries=3,          # retry limit
        rate_limit_codes=[429, 503]
    )
    monitor = CrawlerMonitor(max_visible_rows=15, display_mode=DisplayMode.DETAILED)
    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=70.0,
        check_interval=1.0,
        max_session_permit=10,
        rate_limiter=rate_limiter,
        monitor=monitor
    )
    return dispatcher

run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

# --- Sitemap Mode ---
async def crawl_from_sitemap(start_url: str, max_pages: int, progress_callback=None):
    sitemap_url = urljoin(start_url, "sitemap.xml")
    urls = []
    async with AsyncWebCrawler() as crawler:
        try:
            result = await crawler.arun(url=sitemap_url)
        except Exception as e:
            logging.error(f"Error fetching sitemap: {e}")
            return []
        sitemap_html = getattr(result, "html", "")
        if sitemap_html:
            soup = BeautifulSoup(sitemap_html, "xml")
            loc_tags = soup.find_all("loc")
            urls = [loc.get_text(strip=True) for loc in loc_tags]
        else:
            logging.error("No sitemap.xml found or sitemap is empty.")
            return []
    # Limit URLs to max_pages if necessary
    urls = urls[:max_pages] if max_pages < len(urls) else urls

    dispatcher = get_dispatcher()
    async with AsyncWebCrawler() as crawler:
        # Crawl all URLs concurrently using arun_many (batch processing)
        results = await crawler.arun_many(urls=urls, config=run_config, dispatcher=dispatcher)
        if progress_callback:
            progress_callback(len(results))
        return results

# --- Iterative (Breadth-First) Mode ---
async def iterative_crawl(start_url: str, max_pages: int, fixed_depth: int = 2, progress_callback=None):
    seen_urls = {start_url}
    current_level = [start_url]
    all_results = []
    dispatcher = get_dispatcher()

    while current_level and fixed_depth >= 0 and len(seen_urls) < max_pages:
        async with AsyncWebCrawler() as crawler:
            # Crawl current level concurrently
            results = await crawler.arun_many(urls=current_level, config=run_config, dispatcher=dispatcher)
            all_results.extend(results)
            if progress_callback:
                progress_callback(len(all_results))
            next_level = []
            for res in results:
                html = getattr(res, "html", "")
                if html:
                    soup = BeautifulSoup(html, "html.parser")
                    for a in soup.find_all("a", href=True):
                        link = urljoin(res.url, a["href"])
                        # Only consider links within the same domain
                        if urlparse(link).netloc == urlparse(start_url).netloc and link not in seen_urls:
                            seen_urls.add(link)
                            next_level.append(link)
                        if len(seen_urls) >= max_pages:
                            break
            current_level = next_level
        fixed_depth -= 1
    return all_results

def aggregate_structured_data(scrape_results):
    # Map crawl4ai results to structured data and aggregate
    texts = []
    for res in scrape_results:
        html = getattr(res, "html", "")
        if html:
            data = extract_structured_data(res.url, html)
            texts.append(f"Title: {data.get('title')}\nURL: {data.get('url')}\nContent: {data.get('content')}")
    return "\n\n".join(texts)

# --- Streamlit UI ---
if "scrape_results" not in st.session_state:
    st.session_state.scrape_results = None

st.title("Advanced Website Scraper")

url_input = st.text_input("Enter the URL to scrape", "")
max_pages = st.number_input("Max Pages to Scrape", min_value=1, value=10, step=1)

# Checkbox to select scraping mode
scrape_entire_site = st.checkbox("Scrape entire website via sitemap.xml", value=False)

progress_text = st.empty()

def update_progress(count):
    progress_text.text(f"Pages processed so far: {count}")

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
            st.session_state.scrape_results = None
            # Run the appropriate mode using asyncio.run()
            if scrape_entire_site:
                with st.spinner("Scraping entire website via sitemap.xml..."):
                    scrape_results = asyncio.run(crawl_from_sitemap(url_input, max_pages, progress_callback=update_progress))
            else:
                with st.spinner("Iterative crawling in progress..."):
                    scrape_results = asyncio.run(iterative_crawl(url_input, max_pages, fixed_depth=2, progress_callback=update_progress))
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
