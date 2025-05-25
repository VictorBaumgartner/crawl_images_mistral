# playwright_img_crawler.py
# Scrapes the single most likely logo image from websites listed in unique_links_providers.csv
# Saves one logo image per website to a folder named after the URL's domain in the CWD
# Uses Playwright for dynamic content scraping and requests for image downloading

import asyncio
import csv
import logging
import os
import requests
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
from mimetypes import guess_extension

# Configure logging for debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def score_image(element, url: str) -> tuple:
    """Score an image based on likelihood of being the website's logo.
    
    Args:
        element: Playwright element handle for the image.
        url (str): The URL of the website for context.
    
    Returns:
        tuple: (score, element, src, alt, class_name, id_name) where score is a float.
    """
    try:
        src = await element.get_attribute('src') or ''
        alt = await element.get_attribute('alt') or ''
        class_name = await element.get_attribute('class') or ''
        id_name = await element.get_attribute('id') or ''
        
        # Get image dimensions
        dimensions = await element.evaluate('(img) => ({ width: img.naturalWidth, height: img.naturalHeight })')
        width = dimensions['width']
        height = dimensions['height']
        
        score = 0.0
        
        # Scoring based on attributes
        if 'logo' in alt.lower():
            score += 50
        if 'brand' in alt.lower() or urlparse(url).netloc.replace('www.', '').split('.')[0].lower() in alt.lower():
            score += 30
        if 'logo' in class_name.lower() or 'brand' in class_name.lower() or 'site-logo' in class_name.lower():
            score += 40
        if 'logo' in id_name.lower():
            score += 40
        if 'logo' in src.lower():
            score += 20
        
        # Prefer images in header or nav
        parent_selector = await element.evaluate('(img) => img.closest("header, nav") ? true : false')
        if parent_selector:
            score += 30
        
        # Prefer typical logo dimensions (50-300px width)
        if 50 <= width <= 300 and 20 <= height <= 200:
            score += 20
        elif width > 500 or height > 500:
            score -= 20  # Penalize large images (likely banners)
        
        # Penalize decorative or placeholder images
        if 'spacer' in src.lower() or 'placeholder' in src.lower() or not alt:
            score -= 30
        
        return (score, element, src, alt, class_name, id_name)
    except Exception as e:
        logger.error(f"Error scoring image: {e}")
        return (0, element, src, alt, class_name, id_name)

async def scrape_and_download_images(url: str, cwd: str):
    """Scrape and download the most likely logo image from a website.
    
    Args:
        url (str): The URL of the website to scrape.
        cwd (str): Current working directory to store the folder.
    """
    # Extract domain for folder name (e.g., example.com)
    parsed_url = urlparse(url)
    domain = parsed_url.netloc or parsed_url.path.split('/')[0]
    if not domain:
        domain = 'unknown'
    folder_path = os.path.join(cwd, domain)
    
    # Create folder if it doesn't exist
    os.makedirs(folder_path, exist_ok=True)
    
    async with async_playwright() as p:
        try:
            # Launch headless Chromium browser
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Navigate to the URL and wait for content to load
            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Target images in header, nav, or first section, or with logo-related attributes
            image_selector = (
                'header img, nav img, section:first-of-type img, '
                'div:first-of-type img, [class*="logo"], [id*="logo"], '
                '[class*="brand"], [id*="brand"], [class*="site-logo"]'
            )
            image_elements = await page.query_selector_all(image_selector)
            
            if not image_elements:
                logger.info(f"No potential logo images found on {url}")
                await browser.close()
                return
            
            # Score all images to find the most likely logo
            scored_images = []
            for element in image_elements:
                score_data = await score_image(element, url)
                scored_images.append(score_data)
            
            # Select the image with the highest score
            scored_images.sort(key=lambda x: x[0], reverse=True)
            best_score, best_element, src, alt, class_name, id_name = scored_images[0]
            
            if best_score <= 0:
                logger.info(f"No suitable logo image found on {url} (best score: {best_score})")
                await browser.close()
                return
            
            if src:
                absolute_url = urljoin(url, src)
                try:
                    # Download the logo image
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    response = requests.get(absolute_url, headers=headers, timeout=10)
                    response.raise_for_status()
                    
                    # Determine file extension from content type
                    content_type = response.headers.get('content-type', '')
                    extension = guess_extension(content_type) or '.jpg'
                    
                    # Save image with a fixed filename
                    filename = f"logo{extension}"
                    file_path = os.path.join(folder_path, filename)
                    with open(file_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"Saved logo image: {file_path} (score: {best_score}, alt: {alt}, class: {class_name}, id: {id_name})")
                except Exception as e:
                    logger.error(f"Error downloading {absolute_url}: {e}")
            
            await browser.close()
            logger.info(f"Scraping completed for {url}")
            
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            if 'browser' in locals():
                await browser.close()

def read_urls_from_csv(csv_file: str) -> list:
    """Read URLs from a CSV file.
    
    Args:
        csv_file (str): Path to the CSV file.
    
    Returns:
        list: List of URLs from the 'url' column.
    """
    urls = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if 'url' not in reader.fieldnames:
                logger.error("CSV file must contain a 'url' column")
                return urls
            for row in reader:
                url = row['url'].strip()
                if url:
                    urls.append(url)
        logger.info(f"Read {len(urls)} URLs from {csv_file}")
    except Exception as e:
        logger.error(f"Error reading CSV {csv_file}: {e}")
    return urls

async def main():
    """Main function to process URLs from unique_links_providers.csv and scrape logo images."""
    # Get current working directory
    cwd = os.getcwd()
    
    # Hardcode CSV file path
    csv_file = 'unique_links_providers.csv'
    
    # Verify CSV exists
    if not os.path.exists(csv_file):
        logger.error(f"CSV file {csv_file} not found in {cwd}")
        return
    
    # Read URLs from CSV
    urls = read_urls_from_csv(csv_file)
    if not urls:
        logger.error("No valid URLs found in CSV. Exiting.")
        return
    
    # Scrape and download logo image for each URL
    for url in urls:
        try:
            await scrape_and_download_images(url, cwd)
        except Exception as e:
            logger.error(f"Error processing {url}: {e}")

if __name__ == "__main__":
    asyncio.run(main())