# Website Scraper with Streamlit

This repository contains an asynchronous web scraper built using [Streamlit](https://streamlit.io/). The scraper crawls a given website, extracts structured content from each page, and provides an option to download the aggregated results as a TXT file.

## Features

- **Asynchronous Scraping:** Uses asynchronous techniques (via `asyncio` and a semaphore) to efficiently scrape multiple pages.
- **Content Extraction:** Extracts the main content of web pages using the `readability-lxml` library (if available) and falls back to BeautifulSoup parsing.
- **Deduplication:** Avoids duplicate scraping of URLs and duplicate content based on a content hash.
- **User Interface:** A simple Streamlit UI that allows you to:
  - Enter a URL to start scraping.
  - Specify the maximum number of pages to scrape.
  - See live progress updates.
  - Download the aggregated content as a TXT file.

## How It Works

1. **Setup & Imports:**  
   The code starts by setting up the Streamlit page configuration and importing necessary libraries, including:
   - `streamlit` for the UI.
   - `asyncio` for asynchronous operations.
   - `crawl4ai.AsyncWebCrawler` for fetching web pages.
   - `BeautifulSoup` from `beautifulsoup4` for HTML parsing.
   - Optionally, `readability` (from `readability-lxml`) for extracting main content.

2. **Content Extraction:**
   - `extract_main_content(html)`: Tries to use the `readability` library to get the main content. If that fails, it falls back to parsing `<article>` or `<main>` tags using BeautifulSoup.
   - `clean_content(text)`: Cleans and deduplicates paragraphs in the extracted text.
   - `extract_structured_data(url, html)`: Combines the title, main content, and URL into a structured dictionary.

3. **Asynchronous Scraping:**
   - `iterative_scrape(start_url, max_pages, progress_callback)`:  
     - Uses an asynchronous queue to manage URLs to be scraped.
     - Limits scraping to pages within the same domain as the starting URL.
     - Uses a semaphore to cap the number of concurrent HTTP requests.
     - Tracks progress and re-queues URLs on timeout or errors.
     - Respects a fixed depth (set by the `FIXED_DEPTH` constant) for recursive crawling.
  
4. **Data Aggregation & Download:**
   - `aggregate_structured_data(scrape_results)`: Combines all the scraped results into a single string.
   - The Streamlit UI then offers a download button to save the aggregated data as a TXT file.

