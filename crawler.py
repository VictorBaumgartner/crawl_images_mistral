import asyncio
import json
import logging
import re
import base64
import hashlib
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
from PIL import Image
import io
import aiohttp
from aiohttp import ClientSession
from pathlib import Path
import csv # New import for CSV reading

# Configuration for the crawler
OLLAMA_ENDPOINT = "http://192.168.0.58:11434"
MODEL = "llava"  # Vision-capable model
API_PATHS = ["/api/generate", "/v1/generate", "/api/v1/generate"]
TIMEOUT = 15
RETRY_ATTEMPTS = 3

# Setup logging (ensure this doesn't conflict with Flask's logging)
# For a Flask app, it's often better to let Flask manage logging or configure a separate logger.
# For now, keep it as is, but be aware.
logger = logging.getLogger(__name__)
# Add a handler if not running via Flask's main logging system
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def check_ollama_server(session: ClientSession):
    """Check if the Ollama server is running and find a working API endpoint."""
    try:
        async with session.get(OLLAMA_ENDPOINT, timeout=5) as response:
            if response.status != 200:
                logger.error(f"Ollama server returned status {response.status}")
                return None
            logger.info("Ollama server is accessible")

        for api_path in API_PATHS:
            payload = {"model": MODEL, "prompt": "Test connectivity", "stream": False}
            try:
                async with session.post(f"{OLLAMA_ENDPOINT}{api_path}", json=payload, timeout=5) as api_response:
                    if api_response.status == 200:
                        logger.info(f"Ollama API endpoint {api_path} is functional")
                        return api_path
                    else:
                        logger.warning(f"Ollama API {api_path} returned status {api_response.status}")
            except Exception as e:
                logger.warning(f"Failed to test API {api_path}: {str(e)}")
        logger.error("No valid Ollama API endpoint found")
        return None
    except Exception as e:
        logger.error(f"Failed to connect to Ollama server: {str(e)}")
        return None

def is_valid_image_url(url):
    """Check if the URL points to a valid image."""
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    parsed = urlparse(url.lower())
    if any(parsed.path.endswith(ext) for ext in image_extensions):
        return True
    return False

async def get_image_content(session: ClientSession, url: str, save_path: Path):
    """Download image content, save it, and return as base64 string."""
    try:
        async with session.get(url, timeout=TIMEOUT) as response:
            response.raise_for_status()
            content = await response.read()

            original_extension = Path(urlparse(url).path).suffix
            if not original_extension or original_extension.lower() not in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}:
                try:
                    img_test = Image.open(io.BytesIO(content))
                    original_extension = f".{img_test.format.lower()}" if img_test.format else '.jpg'
                except Exception:
                    original_extension = '.jpg'

            image_hash = hashlib.md5(content).hexdigest()
            filename = save_path / f"{image_hash}{original_extension}"

            with open(filename, 'wb') as f:
                f.write(content)
            logger.info(f"Saved image to: {filename}")

            img = Image.open(io.BytesIO(content))
            img.verify()
            img = Image.open(io.BytesIO(content))
            buffered = io.BytesIO()
            img_format = img.format if img.format else 'PNG'
            img.save(buffered, format=img_format)

            return base64.b64encode(buffered.getvalue()).decode('utf-8'), str(filename)

    except Exception as e:
        logger.error(f"Failed to process image {url}: {str(e)}")
        return None, None

async def ollama_api_call(session: ClientSession, api_path: str, prompt: str, image_base64: str = None, format_type: str = None):
    """Make a call to the Ollama API with retries."""
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False
    }
    if image_base64:
        payload["images"] = [image_base64]
    if format_type:
        payload["format"] = format_type

    for attempt in range(RETRY_ATTEMPTS):
        try:
            async with session.post(f"{OLLAMA_ENDPOINT}{api_path}", json=payload, timeout=TIMEOUT) as response:
                if response.status == 404:
                    logger.error(f"Ollama API endpoint not found: {OLLAMA_ENDPOINT}{api_path}")
                    return None
                response.raise_for_status()
                result = await response.json()
                return result.get('response', 'No response')
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed for Ollama API {api_path}: {str(e)}")
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                logger.error(f"All attempts failed for Ollama API {api_path}: {str(e)}")
                return None
    return None

async def generate_image_description(session: ClientSession, api_path: str, image_base64: str):
    """Generate image description using Ollama."""
    prompt = "Describe the content of this image in detail."
    response = await ollama_api_call(session, api_path, prompt, image_base64)
    return response if response else "Description unavailable due to API failure"

async def categorize_image_content(session: ClientSession, api_path: str, image_base64: str):
    """Categorize the image content (e.g., place, building, art, painting, etc.)."""
    prompt = """Analyze the image and classify its primary content into one of the following categories:
    Place, Building, Piece of Art, Painting, Person, Animal, Object, Food, Vehicle, Nature, Event, or Other.
    Return the result in JSON format with a 'category' field."""
    response = await ollama_api_call(session, api_path, prompt, image_base64, format_type="json")
    if response:
        try:
            result = json.loads(response)
            return result.get('category', 'Unknown')
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse category JSON: {str(e)}")
    return 'Unknown'

async def moderate_image_content(session: ClientSession, api_path: str, image_base64: str):
    """Moderate image content and assign category and confidence score."""
    prompt = """Analyze the image and classify its content as one of the following categories: Violent, Sexual, Sensitive, or Normal.
    Provide a confidence score (0-1) for your classification.
    Return the result in JSON format with 'category' and 'confidence' fields."""
    response = await ollama_api_call(session, api_path, prompt, image_base64, format_type="json")
    if response:
        try:
            result = json.loads(response)
            return {
                'category': result.get('category', 'Unknown'),
                'confidence': float(result.get('confidence', 0.0))
            }
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse moderation JSON: {str(e)}")
    return {'category': 'Unknown', 'confidence': 0.0}

# MODIFIED: crawl_website_images to process a single URL
async def crawl_website_images(url: str, job_output_dir: Path):
    """Crawl images from the given website URL, save them locally, and analyze."""
    site_image_data = [] # Data for this single website
    visited_urls = set()
    urls_to_visit = {url}
    image_hashes = set()

    # Create a clean directory name from the URL for this specific website
    parsed_root_url = urlparse(url)
    sanitized_url_name = re.sub(r'[^\w\-_\. ]', '_', parsed_root_url.netloc)
    if not sanitized_url_name:
        sanitized_url_name = re.sub(r'[^\w\-_\. ]', '_', urlparse(f"http://{url}").netloc)

    current_site_images_dir = job_output_dir / sanitized_url_name
    current_site_images_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Images for {url} will be saved to: {current_site_images_dir.resolve()}")

    api_path = None # Ollama API path will be checked once per session in run_crawler_job

    async with aiohttp.ClientSession() as session:
        # Check Ollama server once per session if not already done
        api_path = await check_ollama_server(session)


        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

            while urls_to_visit:
                current_page_url = urls_to_visit.pop()
                if current_page_url in visited_urls:
                    continue

                visited_urls.add(current_page_url)
                logger.info(f"Crawling page: {current_page_url}")

                try:
                    page = await context.new_page()
                    await page.goto(current_page_url, wait_until='networkidle', timeout=30000)

                    img_elements = await page.query_selector_all('img[src]')
                    for img in img_elements:
                        img_url = await img.get_attribute('src')
                        if not img_url:
                            continue

                        img_url = urljoin(current_page_url, img_url)
                        if not is_valid_image_url(img_url):
                            continue

                        image_base64, local_file_path = await get_image_content(session, img_url, current_site_images_dir)
                        if not image_base64:
                            continue

                        img_hash = hashlib.md5(image_base64.encode()).hexdigest()
                        if img_hash in image_hashes:
                            logger.info(f"Skipping duplicate image (hash {img_hash}): {img_url}")
                            continue
                        image_hashes.add(img_hash)

                        image_entry = {
                            'source_url': current_page_url, # The page this image was found on
                            'original_image_url': img_url,
                            'local_path': local_file_path
                        }

                        if api_path:
                            description = await generate_image_description(session, api_path, image_base64)
                            image_entry['description'] = description
                            content_category = await categorize_image_content(session, api_path, image_base64)
                            image_entry['content_category'] = content_category
                            moderation = await moderate_image_content(session, api_path, image_base64)
                            image_entry['moderation'] = moderation

                            if (description == "Description unavailable due to API failure" and
                                content_category == 'Unknown' and
                                moderation['category']['category'] == 'Unknown'): # Nested category
                                logger.warning(f"Skipping image {img_url} due to complete API failure")
                                continue
                        else:
                            image_entry['description'] = "Description unavailable (Ollama API not accessible)"
                            image_entry['content_category'] = "Unknown"
                            image_entry['moderation'] = {'category': 'Unknown', 'confidence': 0.0}

                        site_image_data.append(image_entry)
                        logger.info(f"Processed image: {img_url} and saved to {local_file_path}")

                    links = await page.query_selector_all('a[href]')
                    for link in links:
                        href = await link.get_attribute('href')
                        if href:
                            absolute_url = urljoin(current_page_url, href)
                            parsed_target_url = urlparse(absolute_url)
                            if parsed_target_url.netloc == parsed_root_url.netloc and absolute_url not in visited_urls:
                                urls_to_visit.add(absolute_url)

                    await page.close()
                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(f"Error crawling page {current_page_url}: {str(e)}")
                    if 'page' in locals() and not page.is_closed():
                        await page.close()

            await browser.close()
    return site_image_data


# NEW FUNCTION: Orchestrates the entire job
async def run_crawler_job_async(csv_file_path: Path, job_output_dir: Path):
    """
    Reads URLs from a CSV and crawls each one to retrieve and analyze images.
    Results are saved in the job_output_dir.
    """
    all_job_results = []
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            urls_to_crawl = [row[0].strip() for row in reader if row and row[0].strip()]

        if not urls_to_crawl:
            logger.warning(f"No URLs found in CSV: {csv_file_path}")
            return False

        logger.info(f"Starting job in {job_output_dir}. Found {len(urls_to_crawl)} URLs to process.")

        for i, url in enumerate(urls_to_crawl):
            logger.info(f"Processing URL {i+1}/{len(urls_to_crawl)}: {url}")
            if not re.match(r'^https?://', url):
                url = 'https://' + url # Ensure valid scheme

            try:
                site_results = await crawl_website_images(url, job_output_dir)
                all_job_results.extend(site_results)
            except Exception as e:
                logger.error(f"Failed to crawl {url}: {e}")

        output_json_path = job_output_dir / "analysis_results.json"
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(all_job_results, f, indent=4, ensure_ascii=False)
        logger.info(f"All analysis results saved to {output_json_path}")
        return True

    except Exception as e:
        logger.critical(f"Critical error during job processing for {csv_file_path}: {e}")
        return False

# Wrapper for running the async job from a non-async context (like ThreadPoolExecutor)
def run_crawler_job_sync(csv_file_path: Path, job_output_dir: Path):
    """Synchronous wrapper to run the async crawler job."""
    return asyncio.run(run_crawler_job_async(csv_file_path, job_output_dir))