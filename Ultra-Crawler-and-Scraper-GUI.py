import logging
import requests
import scrapy
from bs4 import BeautifulSoup
from scrapy.crawler import CrawlerProcess
import tkinter as tk
from tkinter import filedialog
import os
import time
import easygui
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import Process, Manager, Lock
import re
import sys
import random
import urllib3
from urllib.parse import urljoin, urlparse

# Global variables
lock = Lock()  # Lock for thread-safe operations on shared data

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger('scrapy').setLevel(logging.WARNING)
logging.basicConfig(level=logging.WARNING)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def select_random_proxy_scrapy(validated_proxies):
    with lock:
        if validated_proxies:
            proxy = random.choice(validated_proxies)
            return f"http://{proxy}"  # Prepend the protocol for Scrapy
    print("No validated proxies available.")
    return None


def select_random_user_agent(user_agent_file):
    if user_agent_file:
        with open(user_agent_file, "r") as file:
            user_agents = [line.strip() for line in file if line.strip()]
        if user_agents:
            return random.choice(user_agents)
    return None


def validate_proxy(proxy, timeout, required_success):
    test_urls = [
        "https://www.google.com",
        "https://www.bing.com",
        "https://www.yahoo.com",
        "https://httpbin.org/ip"
    ]
    success_count = 0
    for url in test_urls:
        try:
            response = requests.get(url, proxies={"http": proxy, "https": proxy}, timeout=timeout)
            if response.status_code == 200 and "html" in response.headers.get("Content-Type", "").lower():
                success_count += 1
                if success_count >= required_success:
                    return True
        except requests.exceptions.RequestException:
            pass
    return False


def validate_proxies(proxy_list, max_proxies, timeout, required_success, max_workers, validated_proxies):
    easygui.msgbox("Proxy validation started", title="Proxy Validation")

    validated_proxies[:] = []  # Clear the shared list
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {executor.submit(validate_proxy, proxy, timeout, required_success): proxy for proxy in proxy_list}

        try:
            for future in as_completed(future_to_proxy):
                proxy = future_to_proxy[future]
                try:
                    if future.result():
                        validated_proxies.append(proxy)
                        print(f"Valid proxy: {proxy}")
                        if len(validated_proxies) >= max_proxies:
                            for future in future_to_proxy:
                                future.cancel()
                            break
                except Exception as exc:
                    print(f"Proxy {proxy} failed validation with exception: {exc}")
        finally:
            executor.shutdown(wait=True)

    easygui.msgbox(f"Proxy validation finished. Number of valid proxies: {len(validated_proxies)}", title="Proxy Validation Finished")

    if len(validated_proxies) < max_proxies:
        print(f"Warning: Only {len(validated_proxies)} valid proxies found, less than the requested {max_proxies}.")


def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '_', filename)


def clear_terminal():
    os.system('cls' if os.name == 'nt' else 'clear')


def load_scraped_urls(scraped_urls_file):
    if os.path.exists(scraped_urls_file):
        with open(scraped_urls_file, 'r') as f:
            return set(line.strip() for line in f)
    return set()


def load_discovered_urls(discovered_urls_file):
    if os.path.exists(discovered_urls_file):
        with open(discovered_urls_file, 'r') as f:
            return set(line.strip() for line in f)
    return set()


def save_content(response, folder_path, scraped_urls_file):
    page_title = sanitize_filename(response.url)
    file_path = os.path.join(folder_path, f"{page_title}.html")

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(response.text)

    with open(scraped_urls_file, 'a') as f:
        f.write(response.url + '\n')

    print(f"Content saved: {file_path}")


def download_file(url, folder_path, extension):
    """Download a file from a URL and save it with a specific extension."""
    try:
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            file_name = url.split("/")[-1]
            file_name = sanitize_filename(file_name.split(".")[0]) + extension  # Save with the given extension
            file_path = os.path.join(folder_path, file_name)
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            return file_path
        else:
            print(f"Failed to download: {url}")
    except requests.RequestException as e:
        print(f"Error downloading {url}: {e}")
    return None


def save_full_data(response, folder_path, scraped_urls_file, extracted_items):
    """
    Saves full data including the page's HTML, metadata, headings, paragraphs, links, and downloads media content like images, videos, and audio files.
    """
    page_title = sanitize_filename(response.url)

    # Save the entire HTML content of the page
    html_file_path = os.path.join(folder_path, f"{page_title}.html")
    with open(html_file_path, 'w', encoding='utf-8') as f:
        f.write(response.text)

    # Save metadata such as title, meta description, keywords, and author information
    metadata_file_path = os.path.join(folder_path, f"{page_title}_metadata.txt")
    with open(metadata_file_path, 'w', encoding='utf-8') as f:
        f.write(f"URL: {response.url}\n")
        f.write(f"Title: {extracted_items.get('title', 'N/A')}\n")
        f.write(f"Meta Description: {extracted_items.get('meta_description', 'N/A')}\n")
        f.write(f"Meta Keywords: {extracted_items.get('meta_keywords', 'N/A')}\n")
        f.write(f"Meta Author: {extracted_items.get('meta_author', 'N/A')}\n")
        f.write(f"Charset: {extracted_items.get('meta_charset', 'N/A')}\n")

    # Save headings
    headings_file_path = os.path.join(folder_path, f"{page_title}_headings.txt")
    with open(headings_file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(extracted_items.get('headings', [])))

    # Save paragraphs
    paragraphs_file_path = os.path.join(folder_path, f"{page_title}_paragraphs.txt")
    with open(paragraphs_file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(extracted_items.get('paragraphs', [])))

    # Save links
    links_file_path = os.path.join(folder_path, f"{page_title}_links.txt")
    with open(links_file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(extracted_items.get('links', [])))

    # Create subfolders for media files
    images_folder = os.path.join(folder_path, 'images')
    videos_folder = os.path.join(folder_path, 'videos')
    audio_folder = os.path.join(folder_path, 'audio')

    os.makedirs(images_folder, exist_ok=True)
    os.makedirs(videos_folder, exist_ok=True)
    os.makedirs(audio_folder, exist_ok=True)

    # Download and save images as .jpeg
    for img_url in extracted_items.get('images', []):
        image_path = download_file(response.urljoin(img_url), images_folder, ".jpeg")
        if image_path:
            print(f"Image saved: {image_path}")

    # Download and save videos as .mp4
    for video_url in extracted_items.get('videos', []):
        video_path = download_file(response.urljoin(video_url), videos_folder, ".mp4")
        if video_path:
            print(f"Video saved: {video_path}")

    # Download and save audio files as .mp3
    for audio_url in extracted_items.get('audio_files', []):
        audio_path = download_file(response.urljoin(audio_url), audio_folder, ".mp3")
        if audio_path:
            print(f"Audio saved: {audio_path}")

    # Save the scraped URL to the scraped URLs file
    with open(scraped_urls_file, 'a') as f:
        f.write(response.url + '\n')

    print(f"Full data and media saved for: {page_title}")


def extract_items(response):
    title = response.css('title::text').get()
    headings = response.css('h1, h2, h3, h4, h5, h6::text').getall()
    paragraphs = response.css('p::text').getall()
    links = response.css('a::attr(href)').getall()
    images = response.css('img::attr(src)').getall()

    meta_description = response.css('meta[name="description"]::attr(content)').get() or ''
    meta_keywords = response.css('meta[name="keywords"]::attr(content)').get() or ''
    meta_author = response.css('meta[name="author"]::attr(content)').get() or ''
    meta_charset = response.css('meta[charset]::attr(charset)').get() or ''

    videos = response.css('video source::attr(src)').getall()
    iframes = response.css('iframe::attr(src)').getall()
    audio_files = response.css('audio source::attr(src)').getall()

    return {
        'title': title,
        'headings': headings,
        'paragraphs': paragraphs,
        'links': links,
        'images': images,
        'videos': videos,
        'iframes': iframes,
        'audio_files': audio_files,
        'meta_description': meta_description,
        'meta_keywords': meta_keywords,
        'meta_author': meta_author,
        'meta_charset': meta_charset
    }


def extract_and_share_urls(content, base_url, discovered_urls_file, only_same_base, shared_discovered_urls, processed_urls):
    soup = BeautifulSoup(content, 'html.parser')
    base_domain = urlparse(base_url).netloc

    with open(discovered_urls_file, 'a', buffering=8192) as f:
        for link in soup.find_all('a', href=True):
            url = urljoin(base_url, link['href'])
            url_domain = urlparse(url).netloc

            if url not in processed_urls and url not in shared_discovered_urls:
                if only_same_base:
                    if base_domain == url_domain:
                        with lock:
                            shared_discovered_urls.append(url)
                        f.write(url + '\n')
                else:
                    with lock:
                        shared_discovered_urls.append(url)
                    f.write(url + '\n')


class RecursiveSpider(scrapy.Spider):
    name = "recursive_spider"

    def __init__(self, start_urls, folder_path, depth_limit, user_agent_file, max_retries, delay, discovered_urls_file,
                 only_same_base, shared_discovered_urls, processed_urls, validated_proxies, concurrent_requests, mode,
                 scraped_urls_file, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_urls = start_urls
        self.folder_path = folder_path
        self.user_agent_file = user_agent_file
        self.max_retries = max_retries
        self.depth_limit = depth_limit
        self.delay = delay
        self.discovered_urls_file = discovered_urls_file
        self.only_same_base = only_same_base
        self.shared_discovered_urls = shared_discovered_urls
        self.processed_urls = processed_urls
        self.validated_proxies = validated_proxies
        self.concurrent_requests = concurrent_requests
        self.mode = mode
        self.scraped_urls = load_scraped_urls(scraped_urls_file)
        self.scraped_urls_file = scraped_urls_file
        self.discovered_urls = load_discovered_urls(discovered_urls_file)

    def start_requests(self):
        all_urls_to_scrape = set(self.start_urls) | self.discovered_urls
        for url in all_urls_to_scrape:
            if url not in self.scraped_urls:
                yield self.make_request(url, 0)

    def make_request(self, url, retries, depth=0):
        if depth > self.depth_limit:
            print(f"Reached depth limit for {url}")
            return
        if retries >= self.max_retries:
            print(f"Exceeded max retries for {url}")
            return

        proxy = select_random_proxy_scrapy(self.validated_proxies)
        user_agent = select_random_user_agent(self.user_agent_file)
        if not proxy or not user_agent:
            retries += 1
            return self.make_request(url, retries, depth)

        headers = {
            'User-Agent': user_agent,
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com'
        }

        time.sleep(self.delay)

        try:
            return scrapy.Request(
                url,
                headers=headers,
                callback=self.parse,
                errback=self.handle_failure,
                dont_filter=True,
                meta={'proxy': proxy, 'depth': depth, 'retries': retries}
            )
        except Exception as e:
            retries += 1
            return self.make_request(url, retries, depth)

    def handle_failure(self, failure):
        retries = failure.request.meta.get('retries', 0)
        depth = failure.request.meta.get('depth', 0)
        retries += 1
        if retries < self.max_retries:
            yield self.make_request(failure.request.url, retries, depth)
        else:
            print(f"Failed to retrieve {failure.request.url} after {self.max_retries} retries")

    def parse(self, response):
        depth = response.meta.get('depth', 0)
        if response.status != 403:
            content = response.text

            if self.mode == 'scrape':
                save_content(response, self.folder_path, self.scraped_urls_file)

            elif self.mode == 'full-scrape':
                extracted_items = extract_items(response)
                save_full_data(response, self.folder_path, self.scraped_urls_file, extracted_items)

            else:
                extract_and_share_urls(content, response.url, self.discovered_urls_file, self.only_same_base,
                                       self.shared_discovered_urls, self.processed_urls)
                with lock:
                    self.processed_urls.append(response.url)
                new_urls = set(self.shared_discovered_urls) - set(self.processed_urls)
                for url in new_urls:
                    if url not in self.scraped_urls:
                        yield self.make_request(url, 0, depth + 1)


def run_crawler(start_urls, folder_path, depth_limit, delay, max_retries, discovered_urls_file, only_same_base,
                shared_discovered_urls, processed_urls, user_agent_file, validated_proxies, concurrent_requests, mode,
                scraped_urls_file, obey_robots_txt, autothrottle_enabled, autothrottle_start_delay,
                autothrottle_max_delay,
                autothrottle_target_concurrency):
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')

    # Define the Scrapy settings
    scrapy_settings = {
        'LOG_ENABLED': False,
        'LOG_LEVEL': 'CRITICAL',
        'RETRY_TIMES': max_retries,  # Use the user-defined max retries
        'ROBOTSTXT_OBEY': obey_robots_txt,  # Respect robots.txt based on user choice
        'AUTOTHROTTLE_ENABLED': autothrottle_enabled,  # Enable or disable AutoThrottle
        'AUTOTHROTTLE_START_DELAY': autothrottle_start_delay,
        'AUTOTHROTTLE_MAX_DELAY': autothrottle_max_delay,
        'AUTOTHROTTLE_TARGET_CONCURRENCY': autothrottle_target_concurrency
    }

    # Only include download delay and concurrent requests if AutoThrottle is not enabled
    if not autothrottle_enabled:
        scrapy_settings.update({
            'CONCURRENT_REQUESTS': concurrent_requests,  # Set user-defined concurrent requests
            'DOWNLOAD_DELAY': delay  # Set user-defined download delay
        })

    # Create the crawler process with the specified settings
    process = CrawlerProcess(settings=scrapy_settings)

    process.crawl(
        RecursiveSpider,
        start_urls=start_urls,
        folder_path=folder_path,
        depth_limit=depth_limit,
        user_agent_file=user_agent_file,
        max_retries=max_retries,
        delay=delay,
        discovered_urls_file=discovered_urls_file,
        only_same_base=only_same_base,
        shared_discovered_urls=shared_discovered_urls,
        processed_urls=processed_urls,
        validated_proxies=validated_proxies,
        concurrent_requests=concurrent_requests,
        mode=mode,
        scraped_urls_file=scraped_urls_file
    )
    process.start()


def main(start_urls, folder_path, depth_limit, delay, max_retries, discovered_urls_file, run_hours, run_minutes, only_same_base,
         num_parallel_crawlers, user_agent_file, validated_proxies, concurrent_requests, mode, scraped_urls_file, obey_robots_txt,
         autothrottle_enabled, autothrottle_start_delay, autothrottle_max_delay, autothrottle_target_concurrency):
    # Calculate the total run time in seconds based on hours and minutes
    total_runtime = (run_hours * 3600) + (run_minutes * 60)

    with Manager() as manager:
        shared_discovered_urls = manager.list(start_urls)
        processed_urls = manager.list()

        start_time = time.time()

        while True:
            processes = []

            for _ in range(num_parallel_crawlers):
                p = Process(target=run_crawler, args=(
                    start_urls, folder_path, depth_limit, delay, max_retries, discovered_urls_file, only_same_base,
                    shared_discovered_urls, processed_urls, user_agent_file, validated_proxies, concurrent_requests, mode,
                    scraped_urls_file, obey_robots_txt, autothrottle_enabled, autothrottle_start_delay, autothrottle_max_delay,
                    autothrottle_target_concurrency
                ))
                p.start()
                processes.append(p)

            try:
                while any(p.is_alive() for p in processes):
                    time.sleep(1)

                    # Check if the total runtime has been exceeded
                    if time.time() - start_time >= total_runtime:
                        print(f"Scraping duration of {run_hours} hours and {run_minutes} minutes reached. Stopping processes.")
                        for p in processes:
                            p.terminate()
                            p.join()
                        easygui.msgbox("Scraping or Crawling is complete after reaching the time limit!", title="Process Complete")
                        return

                    # Restart the processes periodically if needed
            except KeyboardInterrupt:
                print("Interrupted by user. Exiting...")
                for p in processes:
                    p.terminate()
                break


if __name__ == "__main__":
    fieldNames = [
        "Action (Crawl/Scrape/Full-Scrape)", "URL to Scrape/Crawl", "Recursion Depth (limit)", "Delay Between Requests (seconds)",
        "Max Retries", "Number of Proxies to Use", "Proxy Timeout (seconds)", "Required Successes for Proxy Validation",
        "Number of Workers", "Run Time (hours)", "Run Time (minutes)", "Only Add URLs from Same Domain (yes/no)",
        "Number of Parallel Crawlers", "Concurrent Requests per Crawler", "Respect robots.txt (yes/no)",
        "Enable AutoThrottle (yes/no)", "AutoThrottle Start Delay (seconds)", "AutoThrottle Max Delay (seconds)", "AutoThrottle Target Concurrency"
    ]

    defaultValues = [
        "Crawl", "https://example.com", "10", "0", "10", "100", "2", "2", "2000", "0", "30", "yes", "100", "100", "yes", "no", "5", "60", "1.0"
    ]

    fieldValues = easygui.multenterbox(
        "Adjust the parameters below:",
        "Action and Parameters",
        fieldNames,
        defaultValues
    )

    if fieldValues:
        action = fieldValues[0].strip().lower()
        url = fieldValues[1]
        depth_limit = int(fieldValues[2])
        delay = float(fieldValues[3])
        max_retries = int(fieldValues[4])
        max_proxies = int(fieldValues[5])
        timeout = float(fieldValues[6])
        required_success = int(fieldValues[7])
        max_workers = int(fieldValues[8])
        run_hours = int(fieldValues[9])
        run_minutes = int(fieldValues[10])
        only_same_base = fieldValues[11].strip().lower() == 'yes'
        num_parallel_crawlers = int(fieldValues[12])
        concurrent_requests = int(fieldValues[13])
        obey_robots_txt = fieldValues[14].strip().lower() == 'yes'
        autothrottle_enabled = fieldValues[15].strip().lower() == 'yes'
        autothrottle_start_delay = float(fieldValues[16])
        autothrottle_max_delay = float(fieldValues[17])
        autothrottle_target_concurrency = float(fieldValues[18])

        if action == "scrape" or action == "full-scrape":
            url_file = filedialog.askopenfilename(title="Select File with URLs", filetypes=[("Text Files", "*.txt")])
            if url_file:
                with open(url_file, "r") as f:
                    start_urls = [line.strip() for line in f if line.strip()]
            else:
                easygui.msgbox("No file selected. Exiting.", title="Error")
                sys.exit(0)
        else:
            start_urls = [url]

        proxy_file = filedialog.askopenfilename(title="Select Proxy File", filetypes=[("Text Files", "*.txt")])
        user_agent_file = filedialog.askopenfilename(title="Select User-Agent File", filetypes=[("Text Files", "*.txt")])

        with open(proxy_file, "r") as file:
            proxy_list = [line.strip() for line in file if line.strip()]

        root = tk.Tk()
        root.withdraw()

        if proxy_list:
            with Manager() as manager:
                validated_proxies = manager.list()
                print("Validating proxies...")
                validate_proxies(proxy_list, max_proxies, timeout, required_success, max_workers, validated_proxies)
                if validated_proxies:
                    print("Done validating proxies. Choose a folder to save results.")
                    sys.stdout = open(os.devnull, 'w')
                    sys.stderr = open(os.devnull, 'w')
                    folder_path = filedialog.askdirectory(title="Select Folder to Save Results")
                    if folder_path:
                        discovered_urls_file = os.path.join(folder_path, "discovered_urls.txt")
                        scraped_urls_file = os.path.join(folder_path, "scraped_urls.txt")
                        try:
                            main(start_urls, folder_path, depth_limit, delay, max_retries, discovered_urls_file,
                                 run_hours, run_minutes, only_same_base, num_parallel_crawlers, user_agent_file,
                                 validated_proxies, concurrent_requests, action, scraped_urls_file, obey_robots_txt,
                                 autothrottle_enabled, autothrottle_start_delay, autothrottle_max_delay, autothrottle_target_concurrency)
                        except KeyboardInterrupt:
                            print("Interrupted by user. Exiting...")
                            sys.exit(0)
                else:
                    print("No valid proxies found. Exiting...")