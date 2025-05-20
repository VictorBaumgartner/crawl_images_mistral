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
from pathlib import Path # Import Path for easier path manipulation

# Configuration
OLLAMA_ENDPOINT = "http://192.168.0.58:11434"
MODEL = "llava"  # Vision-capable model
API_PATHS = ["/api/generate", "/v1/generate", "/api/v1/generate"]  # Try these endpoints
OUTPUT_FILE = r"C:\Users\victo\Desktop\CS\scrap_img\image_data.json"
TIMEOUT = 15
RETRY_ATTEMPTS = 3
IMAGE_SAVE_DIR_BASE = Path("./scraped_images") # Base directory for saving images

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def check_ollama_server(session: ClientSession):
    """Check if the Ollama server is running and find a working API endpoint."""
    try:
        async with session.get(OLLAMA_ENDPOINT, timeout=5) as response:
            if response.status != 200:
                logger.error(f"Ollama server returned status {response.status}")
                return None
            logger.info("Ollama server is accessible")

        # Try each API path
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
    # Check if the path ends with a known image extension
    if any(parsed.path.endswith(ext) for ext in image_extensions):
        return True
    # Also check content type if available (though not directly here, but could be added if needed)
    return False

# MODIFIED FUNCTION
async def get_image_content(session: ClientSession, url: str, save_path: Path):
    """Download image content, save it, and return as base64 string."""
    try:
        async with session.get(url, timeout=TIMEOUT) as response:
            response.raise_for_status()
            content = await response.read()

            # Generate a unique filename (e.g., using hash and original extension)
            # Use a more robust way to get extension, considering URLs without explicit extensions
            original_extension = Path(urlparse(url).path).suffix
            if not original_extension or original_extension.lower() not in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}:
                # Try to guess format from content for cases like /image?id=123
                try:
                    img_test = Image.open(io.BytesIO(content))
                    original_extension = f".{img_test.format.lower()}" if img_test.format else '.jpg' # Default to jpg
                except Exception:
                    original_extension = '.jpg' # Fallback if content isn't a valid image format

            image_hash = hashlib.md5(content).hexdigest()
            filename = save_path / f"{image_hash}{original_extension}"

            # Save the image to the local folder
            with open(filename, 'wb') as f:
                f.write(content)
            logger.info(f"Saved image to: {filename}")

            # Verify image integrity and convert to base64 for LLM
            img = Image.open(io.BytesIO(content))
            img.verify()  # Verify image integrity
            img = Image.open(io.BytesIO(content))  # Reopen after verify
            buffered = io.BytesIO()
            img_format = img.format if img.format else 'PNG' # Use PNG as a default if format is unknown
            img.save(buffered, format=img_format)
            
            return base64.b64encode(buffered.getvalue()).decode('utf-8'), str(filename) # Return base64 and local path

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
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
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

# MODIFIED FUNCTION
async def crawl_images(url: str):
    """Crawl images from the given website URL using Playwright and save them locally."""
    image_data = []
    visited_urls = set()
    urls_to_visit = {url}
    image_hashes = set() # To prevent duplicate image files
    api_path = None

    # Create a clean directory name from the URL
    parsed_root_url = urlparse(url)
    # Sanitize the hostname to be a valid folder name
    # Replace invalid characters (e.g., :, /, ?) with underscores or remove them
    sanitized_url_name = re.sub(r'[^\w\-_\. ]', '_', parsed_root_url.netloc)
    if not sanitized_url_name: # Fallback for URLs like 'example.com' without scheme
        sanitized_url_name = re.sub(r'[^\w\-_\. ]', '_', urlparse(f"http://{url}").netloc)

    current_site_images_dir = IMAGE_SAVE_DIR_BASE / sanitized_url_name
    current_site_images_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Images will be saved to: {current_site_images_dir.resolve()}")


    async with aiohttp.ClientSession() as session:
        # Find a working Ollama API endpoint
        api_path = await check_ollama_server(session)
        if not api_path:
            logger.warning("No valid Ollama API endpoint found. Crawling images without descriptions or moderation.")

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
                    img_elements = await page.query_selector_all('img[src]')
                    for img in img_elements:
                        img_url = await img.get_attribute('src')
                        if not img_url:
                            continue

                        img_url = urljoin(current_url, img_url)
                        if not is_valid_image_url(img_url):
                             # Often, images are background-images or loaded via JS, not directly in <img> src
                             # For now, stick to img src, but this is a potential area for enhancement
                            # logger.debug(f"Skipping non-image URL or unsupported extension: {img_url}")
                            continue

                        # Get image content and save it
                        image_base64, local_file_path = await get_image_content(session, img_url, current_site_images_dir)
                        if not image_base64:
                            continue

                        # Generate image hash from the *content* to avoid duplicates in the JSON and on disk
                        img_hash = hashlib.md5(image_base64.encode()).hexdigest()
                        if img_hash in image_hashes:
                            logger.info(f"Skipping duplicate image (hash {img_hash}): {img_url}")
                            continue
                        image_hashes.add(img_hash)

                        # Initialize image data
                        image_entry = {
                            'original_url': img_url,
                            'local_path': local_file_path # Add the local path here
                        }

                        # Process API-dependent fields only if API is available
                        if api_path:
                            # Generate description
                            description = await generate_image_description(session, api_path, image_base64)
                            image_entry['description'] = description

                            # Categorize content
                            content_category = await categorize_image_content(session, api_path, image_base64)
                            image_entry['content_category'] = content_category

                            # Moderate content
                            moderation = await moderate_image_content(session, api_path, image_base64)
                            image_entry['moderation'] = moderation

                            # Skip if all API calls failed
                            if (description == "Description unavailable due to API failure" and
                                content_category == 'Unknown' and
                                moderation['category'] == 'Unknown'):
                                logger.warning(f"Skipping image {img_url} due to complete API failure")
                                continue
                        else:
                            # Fallback data when Ollama API is unavailable
                            image_entry['description'] = "Description unavailable (Ollama API not accessible)"
                            image_entry['content_category'] = "Unknown"
                            image_entry['moderation'] = {'category': 'Unknown', 'confidence': 0.0}

                        # Collect image data
                        image_data.append(image_entry)
                        logger.info(f"Processed image: {img_url} and saved to {local_file_path}")

                    # Find all links to continue crawling within the same domain
                    links = await page.query_selector_all('a[href]')
                    for link in links:
                        href = await link.get_attribute('href')
                        if href:
                            absolute_url = urljoin(current_url, href)
                            parsed_target_url = urlparse(absolute_url)
                            # Ensure the link is within the same domain and not already visited
                            if parsed_target_url.netloc == parsed_root_url.netloc and absolute_url not in visited_urls:
                                urls_to_visit.add(absolute_url)

                    await page.close()
                    await asyncio.sleep(1)  # Respectful crawling

                except Exception as e:
                    logger.error(f"Error crawling {current_url}: {str(e)}")
                    # Ensure page is closed even if an error occurs
                    if 'page' in locals() and not page.is_closed():
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
        logger.error(f"Failed to save JSON: {str(e)}")

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