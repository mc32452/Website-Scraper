import streamlit as st
import streamlit.components.v1 as components
import asyncio
import pandas as pd
import json
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig, CacheMode
from pyvis.network import Network
import os
os.system("playwright install")


st.set_page_config(layout="wide")
st.title("Website Crawler and Scraper")
st.write("An efficient, LLM-free approach to web crawling, data extraction, and site mapping.")

def get_crawler_configs():
    browser_config = BrowserConfig(verbose=True)
    run_config = CrawlerRunConfig(
        word_count_threshold=10,
        excluded_tags=['form', 'header'],
        exclude_external_links=True,
        process_iframes=True,
        remove_overlay_elements=True,
        cache_mode=CacheMode.ENABLED
    )
    return browser_config, run_config

async def crawl_url(url: str):
    browser_config, run_config = get_crawler_configs()
    async with AsyncWebCrawler(config=browser_config) as crawler:
        return await crawler.arun(url=url, config=run_config)

async def crawl_all_links(links, max_concurrent=5):
    results = []
    browser_config, run_config = get_crawler_configs()
    semaphore = asyncio.Semaphore(max_concurrent)
    async with AsyncWebCrawler(config=browser_config) as crawler:
        async def limited_crawl(link):
            link_url = link.get("href")
            if not link_url:
                return {"URL": None, "Status": "Error", "Message": "Invalid URL", "Content": ""}
            async with semaphore:
                return await crawler.arun(url=link_url, config=run_config)
        valid_links = [link for link in links if link.get("href")]
        responses = await asyncio.gather(*(limited_crawl(link) for link in valid_links), return_exceptions=True)
    for link, response in zip(valid_links, responses):
        link_url = link.get("href")
        if isinstance(response, Exception):
            results.append({"URL": link_url, "Status": "Error", "Message": str(response), "Content": ""})
        else:
            if response.success:
                results.append({
                    "URL": link_url,
                    "Status": "Success",
                    "Message": f"Scraped {len(response.markdown)} chars",
                    "Content": response.markdown
                })
            else:
                results.append({
                    "URL": link_url,
                    "Status": "Failed",
                    "Message": response.error_message,
                    "Content": ""
                })
    return results

async def build_site_map(start_url, max_depth=2, max_concurrent=5):
    visited = set([start_url])
    nodes = {start_url: {"url": start_url}}
    edges = []
    current_level = [(start_url, 0)]
    while current_level:
        next_level = []
        tasks = []
        parent_data = []
        for parent_url, depth in current_level:
            if depth < max_depth:
                tasks.append(crawl_url(parent_url))
                parent_data.append((parent_url, depth))
        if tasks:
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            for i, response in enumerate(responses):
                parent_url, parent_depth = parent_data[i]
                if isinstance(response, Exception):
                    continue
                if response and response.success:
                    internal_links = response.links.get("internal", [])
                    for link in internal_links:
                        child_url = link.get("href")
                        # Only add URLs from the same domain (you can adjust this as needed)
                        if child_url and child_url.startswith(start_url) and child_url not in visited:
                            visited.add(child_url)
                            nodes[child_url] = {"url": child_url}
                            edges.append((parent_url, child_url))
                            next_level.append((child_url, parent_depth + 1))
        current_level = next_level
    return list(nodes.keys()), edges

tabs = st.tabs(["Scraping", "Site Map"])

with tabs[0]:
    url_input = st.text_input("Enter URL", key="scraping_url")
    if st.button("Crawl Website"):
        url = url_input.strip()
        if not url:
            st.error("Please enter a valid URL.")
        else:
            if not url.startswith("http"):
                url = "https://" + url
            st.info(f"Crawling **{url}** ...")
            try:
                main_result = asyncio.run(crawl_url(url))
            except Exception as e:
                st.error(f"An error occurred: {e}")
                main_result = None
            if main_result and main_result.success:
                internal_links = main_result.links.get("internal", [])
                if internal_links:
                    st.session_state["internal_links"] = internal_links
                    st.success("Crawl successful!")
                else:
                    st.warning("No internal links found.")
            else:
                error_msg = main_result.error_message if main_result else "No result returned."
                st.error(f"Crawl failed: {error_msg}")

    if st.button("Scrape Single Link"):
        url = url_input.strip()
        if not url:
            st.error("Please enter a valid URL.")
        else:
            if not url.startswith("http"):
                url = "https://" + url
            st.info(f"Scraping **{url}** ...")
            try:
                result = asyncio.run(crawl_url(url))
            except Exception as e:
                st.error(f"An error occurred: {e}")
                result = None
            if result and result.success:
                json_data = json.dumps({"url": url, "content": result.markdown}, indent=2)
                txt_data = result.markdown
                st.success("Scrape successful!")
                st.download_button(
                    label="Download Scraped Content as JSON",
                    data=json_data,
                    file_name="scraped_content.json",
                    mime="application/json"
                )
                st.download_button(
                    label="Download Scraped Content as TXT (Markdown)",
                    data=txt_data,
                    file_name="scraped_content.txt",
                    mime="text/plain"
                )
            else:
                error_msg = result.error_message if result else "No result returned."
                st.error(f"Scrape failed: {error_msg}")

    if "internal_links" in st.session_state:
        with st.expander("Internal Links Found"):
            links_list = [link.get("href", "") for link in st.session_state["internal_links"] if link.get("href")]
            df_links = pd.DataFrame(links_list, columns=["Links Found"])
            st.table(df_links)
        if st.button("Scrape All Links"):
            st.info("Scraping all found links...")
            try:
                all_results = asyncio.run(crawl_all_links(st.session_state["internal_links"], max_concurrent=5))
            except Exception as e:
                st.error(f"An error occurred while scraping all links: {e}")
                all_results = []
            if all_results:
                txt_content = ""
                table_data = []
                for result in all_results:
                    link_url = result["URL"]
                    status = result["Status"]
                    message = result["Message"]
                    content = result["Content"]
                    table_data.append({"URL": link_url, "Status": status, "Message": message})
                    txt_content += f"URL: {link_url}\n{content}\n\n{'-'*80}\n\n"
                json_results = json.dumps(all_results, indent=2)
                st.download_button(
                    label="Download Scraped Content as JSON",
                    data=json_results,
                    file_name="scraped_content.json",
                    mime="application/json"
                )
                st.download_button(
                    label="Download Scraped Content as TXT (Markdown)",
                    data=txt_content,
                    file_name="scraped_content.txt",
                    mime="text/plain"
                )
                st.markdown("### Scraping Results")
                df_results = pd.DataFrame([row for row in table_data if row["Status"] == "Success"])
                st.table(df_results)

with tabs[1]:
    st.header("Site Map Visualization")
    site_url = st.text_input("Enter Site URL", key="sitemap_url")
    max_depth = st.slider("Maximum Depth", min_value=1, max_value=5, value=2)
    max_concurrent = st.slider("Max Concurrent Requests", min_value=1, max_value=10, value=5)
    if st.button("Generate Site Map"):
        site_url = site_url.strip()
        if not site_url:
            st.error("Please enter a valid URL.")
        else:
            if not site_url.startswith("http"):
                site_url = "https://" + site_url
            st.info(f"Generating site map for **{site_url}** ...")
            try:
                nodes, edges = asyncio.run(build_site_map(site_url, max_depth, max_concurrent))
            except Exception as e:
                st.error(f"Error during site map generation: {e}")
                nodes, edges = [], []
            if nodes:
                net = Network(height="600px", width="100%", directed=True)
                for node in nodes:
                    color = "red" if node == site_url else "blue"
                    net.add_node(node, label=node, color=color)
                for parent, child in edges:
                    net.add_edge(parent, child)
                net.force_atlas_2based()  # Apply layout algorithm for a better visual
                html = net.generate_html()
                components.html(html, height=600, width=800, scrolling=True)
            else:
                st.warning("No nodes found for the site map.")
