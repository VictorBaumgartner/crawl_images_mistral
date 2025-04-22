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

# Configuration
OLLAMA_ENDPOINT = "http://192.168.0.58:11434"
MODEL = "mistral-3.1"
OUTPUT_FILE = "image_data.json"
TIMEOUT = 30
RETRY_ATTEMPTS = 3

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def is_valid_image_url(url):
    """Check if the URL points to a valid image."""
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    parsed = urlparse(url.lower())
    return any(parsed.path.endswith(ext) for ext in image_extensions)

async def get_image_content(session: ClientSession, url: str):
    """Download image content and return as base64 string."""
    try:
        async with session.get(url, timeout=TIMEOUT) as response:
            response.raise_for_status()
            content = await response.read()
            img = Image.open(io.BytesIO(content))
            img.verify()  # Verify image integrity
            img = Image.open(io.BytesIO(content))  # Reopen after verify
            buffered = io.BytesIO()
            img_format = img.format if img.format else 'JPEG'
            img.save(buffered, format=img_format)
            return base64.b64encode(buffered.getvalue()).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to process image {url}: {e}")
        return None

async def ollama_api_call(session: ClientSession, prompt: str, image_base64: str, format_type: str = None):
    """Make a call to the Ollama API with retries."""
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "images": [image_base64]
    }
    if format_type:
        payload["format"] = format_type

    for attempt in range(RETRY_ATTEMPTS):
        try:
            async with session.post(f"{OLLAMA_ENDPOINT}/api/generate", json=payload, timeout=TIMEOUT) as response:
                response.raise_for_status()
                result = await response.json()
                return result.get('response', 'No response')
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed for Ollama API: {e}")
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"All attempts failed for Ollama API: {e}")
                return None
    return None

async def generate_image_description(session: ClientSession, image_base64: str):
    """Generate image description using Ollama."""
    prompt = "Describe the content of this image in detail."
    response = await ollama_api_call(session, prompt, image_base64)
    return response if response else "Error generating description"

async def categorize_image_content(session: ClientSession, image_base64: str):
    """Categorize the image content (e.g., place, building, art, painting, etc.)."""
    prompt = """Analyze the image and classify its primary content into one of the following categories: 
    Place, Building, Piece of Art, Painting, Person, Animal, Object, Food, Vehicle, Nature, Event, or Other. 
    Return the result in JSON format with a 'category' field."""
    response = await ollama_api_call(session, prompt, image_base64, format_type="json")
    if response:
        try:
            result = json.loads(response)
            return result.get('category', 'Unknown')
        except json.JSONDecodeError:
            logger.error("Failed to parse category JSON")
    return 'Unknown'

async def moderate_image_content(session: ClientSession, image_base64: str):
    """Moderate image content and assign category and confidence score."""
    prompt = """Analyze the image and classify its content as one of the following categories: Violent, Sexual, Sensitive, or Normal. 
    Provide a confidence score (0-1) for your classification. 
    Return the result in JSON format with 'category' and 'confidence' fields."""
    response = await ollama_api_call(session, prompt, image_base64, format_type="json")
    if response:
        try:
            result = json.loads(response)
            return {
                'category': result.get('category', 'Unknown'),
                'confidence': float(result.get('confidence', 0.0))
            }
        except (json.JSONDecodeError, ValueError):
            logger.error("Failed to parse moderation JSON")
    return {'category': 'Unknown', 'confidence': 0.0}

async def crawl_images(url: str):
    """Crawl images from the given website URL using Playwright."""
    image_data = []
    visited_urls = set()
    urls_to_visit = {url}
    image_hashes = set()

    async with async_playwright() as p, aiohttp.ClientSession() as session:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

        while urls_to_visit:
            current_url = urls_to_visit.pop()
            if current_url in visited_urls:
                continue

            visited_urls.add(current_url)
            logger.info(f"Crawling: {current_url}")

            try:
                page = await context.new_page()
                await page.goto(current_url, wait_until='networkidle', timeout=30000)

                # Get all image elements
                img_elements = await page.query_selector_all('img[src]')
                for img in img_elements:
                    img_url = await img.get_attribute('src')
                    if not img_url:
                        continue

                    img_url = urljoin(current_url, img_url)
                    if not is_valid_image_url(img_url):
                        continue

                    # Get image content
                    image_base64 = await get_image_content(session, img_url)
                    if not image_base64:
                        continue

                    # Generate image hash to avoid duplicates
                    img_hash = hashlib.md5(image_base64.encode()).hexdigest()
                    if img_hash in image_hashes:
                        continue
                    image_hashes.add(img_hash)

                    # Generate description
                    description = await generate_image_description(session, image_base64)
                    if "Error" in description:
                        continue  # Skip if description fails

                    # Categorize content
                    content_category = await categorize_image_content(session, image_base64)
                    if content_category == 'Unknown':
                        continue  # Skip if categorization fails

                    # Moderate content
                    moderation = await moderate_image_content(session, image_base64)
                    if moderation['category'] == 'Unknown':
                        continue  # Skip if moderation fails

                    # Collect image data
                    image_data.append({
                        'url': img_url,
                        'description': description,
                        'content_category': content_category,
                        'moderation': moderation
                    })
                    logger.info(f"Processed image: {img_url}")

                # Find all links to continue crawling
                links = await page.query_selector_all('a[href]')
                for link in links:
                    href = await link.get_attribute('href')
                    if href:
                        absolute_url = urljoin(current_url, href)
                        parsed_url = urlparse(absolute_url)
                        if parsed_url.netloc == urlparse(url).netloc and absolute_url not in visited_urls:
                            urls_to_visit.add(absolute_url)

                await page.close()
                await asyncio.sleep(1)  # Respectful crawling

            except Exception as e:
                logger.error(f"Error crawling {current_url}: {e}")
                await page.close()

        await browser.close()

    return image_data

def save_to_json(data, filename):
    """Save data to a JSON file."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(f"Data saved to {filename}")
    except Exception as e:
        logger.error(f"Failed to save JSON: {e}")

async def main():
    website_url = input("Enter the website URL to crawl (e.g., https://example.com): ")
    if not re.match(r'^https?://', website_url):
        website_url = 'https://' + website_url

    logger.info(f"Starting crawl for {website_url}")
    image_data = await crawl_images(website_url)
    save_to_json(image_data, OUTPUT_FILE)
    logger.info(f"Crawling complete. Found {len(image_data)} images.")

if __name__ == "__main__":
    asyncio.run(main())