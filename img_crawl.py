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
import requests

# Configuration
OLLAMA_ENDPOINT = "http://192.168.0.58:11434"
MODEL = "mistral-3.1"
OUTPUT_FILE = r"C:\Users\victo\Desktop\CS\scrap_img\image_data.json"

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def is_valid_image_url(url):
    """Check if the URL points to a valid image."""
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    parsed = urlparse(url.lower())
    return any(parsed.path.endswith(ext) for ext in image_extensions)

async def get_image_content(url):
    """Download image content and return as base64 string."""
    try:
        async with requests.get(url, timeout=10) as response:
            response.raise_for_status()
            content = await response.read()
            img = Image.open(io.BytesIO(content))
            img.verify()  # Verify image integrity
            img = Image.open(io.BytesIO(content))  # Reopen after verify
            buffered = io.BytesIO()
            img.save(buffered, format=img.format if img.format else 'JPEG')
            return base64.b64encode(buffered.getvalue()).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to process image {url}: {e}")
        return None

def generate_image_description(image_base64):
    """Generate image description using Ollama."""
    try:
        prompt = "Describe the content of this image in detail."
        payload = {
            "model": MODEL,
            "prompt": prompt,
            "images": [image_base64]
        }
        response = requests.post(f"{OLLAMA_ENDPOINT}/api/generate", json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get('response', 'No description available')
    except Exception as e:
        logger.error(f"Failed to generate description: {e}")
        return "Error generating description"

def categorize_image_content(image_base64):
    """Categorize the image content (e.g., place, building, art, painting, etc.)."""
    try:
        prompt = """Analyze the image and classify its primary content into one of the following categories: 
        Place, Building, Piece of Art, Painting, Person, Animal, Object, Food, Vehicle, Nature, Event, or Other. 
        Return the result in JSON format with a 'category' field."""
        payload = {
            "model": MODEL,
            "prompt": prompt,
            "images": [image_base64],
            "format": "json"
        }
        response = requests.post(f"{OLLAMA_ENDPOINT}/api/generate", json=payload, timeout=30)
        response.raise_for_status()
        result = json.loads(response.json().get('response', '{}'))
        return result.get('category', 'Unknown')
    except Exception as e:
        logger.error(f"Failed to categorize image: {e}")
        return 'Unknown'

def moderate_image_content(image_base64):
    """Moderate image content and assign category and confidence score."""
    try:
        prompt = """Analyze the image and classify its content as one of the following categories: Violent, Sexual, Sensitive, or Normal. 
        Provide a confidence score (0-1) for your classification. 
        Return the result in JSON format with 'category' and 'confidence' fields."""
        payload = {
            "model": MODEL,
            "prompt": prompt,
            "images": [image_base64],
            "format": "json"
        }
        response = requests.post(f"{OLLAMA_ENDPOINT}/api/generate", json=payload, timeout=30)
        response.raise_for_status()
        result = json.loads(response.json().get('response', '{}'))
        return {
            'category': result.get('category', 'Unknown'),
            'confidence': float(result.get('confidence', 0.0))
        }
    except Exception as e:
        logger.error(f"Failed to moderate image: {e}")
        return {'category': 'Unknown', 'confidence': 0.0}

async def crawl_images(url):
    """Crawl images from the given website URL using Playwright."""
    image_data = []
    visited_urls = set()
    urls_to_visit = {url}
    image_hashes = set()

    async with async_playwright() as p:
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
                img_elements = await page.query_selector_all('img')
                for img in img_elements:
                    img_url = await img.get_attribute('src')
                    if not img_url:
                        continue

                    img_url = urljoin(current_url, img_url)
                    if not is_valid_image_url(img_url):
                        continue

                    # Get image content
                    image_base64 = await get_image_content(img_url)
                    if not image_base64:
                        continue

                    # Generate image hash to avoid duplicates
                    img_hash = hashlib.md5(image_base64.encode()).hexdigest()
                    if img_hash in image_hashes:
                        continue
                    image_hashes.add(img_hash)

                    # Generate description
                    description = generate_image_description(image_base64)

                    # Categorize content
                    content_category = categorize_image_content(image_base64)

                    # Moderate content
                    moderation = moderate_image_content(image_base64)

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