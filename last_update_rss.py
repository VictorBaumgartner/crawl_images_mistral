import csv
import json
import xml.etree.ElementTree as ET
import requests
from io import StringIO
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, HttpUrl

app = FastAPI()

class URLInfo(BaseModel):
    """
    Represents a URL and its last modification date.
    """
    url: str
    lastmod: Optional[str]

class SitemapResult(BaseModel):
    """
    Represents the result of processing a URL, including any sitemap URLs found
    and the extracted URL information.
    """
    input_url: str
    sitemap_urls: List[str] = []
    results: List[URLInfo] = []
    error: Optional[str] = None  # Add an error field

def get_sitemap_urls(url: str) -> List[str]:
    """
    Retrieves sitemap URLs from a given URL. Handles both sitemap index files
    and regular sitemap files.

    Args:
        url (str): The URL to check for sitemaps.

    Returns:
        List[str]: A list of sitemap URLs.
    """
    sitemap_urls = []
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        content = response.text

        # Check if it's a sitemap index
        if "<sitemapindex" in content:
            root = ET.fromstring(content)
            for sitemap in root.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap'):
                loc = sitemap.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc').text
                sitemap_urls.append(loc)
        # Check if it is a regular sitemap
        elif "<urlset" in content:
            sitemap_urls.append(url)
        else:
            # Not a sitemap, but don't raise an exception here, return empty list
            return []

    except requests.exceptions.RequestException as e:
        # Log the error and return an empty list
        print(f"Error fetching sitemap(s) from {url}: {e}")
        return []
    except ET.ParseError as e:
        # Log the error and return an empty list
        print(f"Error parsing XML from {url}: {e}")
        return []
    except Exception as e:
        # Log the error and return an empty list
        print(f"An unexpected error occurred while processing {url}: {e}")
        return []
    return sitemap_urls


def get_lastmod_from_sitemap(sitemap_url: str) -> List[URLInfo]:
    """
    Retrieves URLs and their lastmod dates from a sitemap URL.

    Args:
        sitemap_url (str): The URL of the sitemap.

    Returns:
        List[URLInfo]: A list of URLInfo objects.
    """
    url_lastmod_list = []
    try:
        response = requests.get(sitemap_url)
        response.raise_for_status()
        content = response.text

        root = ET.fromstring(content)
        for url_element in root.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}url'):
            loc = url_element.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc').text
            lastmod = url_element.find('{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod')
            lastmod_text = lastmod.text if lastmod is not None else None  # Handle missing lastmod
            url_lastmod_list.append(URLInfo(url=loc, lastmod=lastmod_text))

    except requests.exceptions.RequestException as e:
        print(f"Error fetching sitemap content from {sitemap_url}: {e}")
        return []
    except ET.ParseError as e:
        print(f"Error parsing XML from {sitemap_url}: {e}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred while processing {sitemap_url}: {e}")
        return []
    return url_lastmod_list


@app.get("/process_url/", response_model=SitemapResult)
async def process_url(url: HttpUrl = Query(..., description="The URL to process")):
    """
    Processes a given URL to retrieve sitemap URLs and their last modification dates.

    Args:
        url (HttpUrl): The URL to process.  It uses Pydantic's HttpUrl for validation.

    Returns:
        SitemapResult: A JSON response containing the input URL, sitemap URLs,
        and the extracted URL information with last modification dates.  Will also
        return error information, if any.
    """
import csv
import json
import xml.etree.ElementTree as ET
import requests
from io import StringIO
from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, HttpUrl, ValidationError
from fastapi.responses import JSONResponse

app = FastAPI()

class URLInfo(BaseModel):
    """
    Represents a URL and its last modification date.
    """
    url: str
    lastmod: Optional[str]

class SitemapResult(BaseModel):
    """
    Represents the result of processing a URL, including any sitemap URLs found
    and the extracted URL information.
    """
    input_url: str
    sitemap_urls: List[str] = []
    results: List[URLInfo] = []
    error: Optional[str] = None

def get_sitemap_urls(url: str) -> List[str]:
    """
    Retrieves sitemap URLs from a given URL. Handles both sitemap index files
    and regular sitemap files.

    Args:
        url (str): The URL to check for sitemaps.

    Returns:
        List[str]: A list of sitemap URLs.
    """
    sitemap_urls = []
    try:
        response = requests.get(url)
        response.raise_for_status()
        content = response.text

        # Check if it's a sitemap index
        if "<sitemapindex" in content:
            root = ET.fromstring(content)
            for sitemap in root.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap'):
                loc = sitemap.find('{http://www.w3.org/2005/Atom}loc').text if "{http://www.w3.org/2005/Atom}loc" in sitemap.tag else sitemap.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc').text
                sitemap_urls.append(loc)
        # Check if it is a regular sitemap
        elif "<urlset" in content:
            sitemap_urls.append(url)
        else:
            return []

    except requests.exceptions.RequestException as e:
        print(f"Error fetching sitemap(s) from {url}: {e}")
        return []
    except ET.ParseError as e:
        print(f"Error parsing XML from {url}: {e}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred while processing {url}: {e}")
        return []
    return sitemap_urls


def get_lastmod_from_sitemap(sitemap_url: str) -> List[URLInfo]:
    """
    Retrieves URLs and their lastmod dates from a sitemap URL.

    Args:
        sitemap_url (str): The URL of the sitemap.

    Returns:
        List[URLInfo]: A list of URLInfo objects.
    """
    url_lastmod_list = []
    try:
        response = requests.get(sitemap_url)
        response.raise_for_status()
        content = response.text

        root = ET.fromstring(content)
        for url_element in root.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}url'):
            loc = url_element.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc').text
            lastmod = url_element.find('{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod')
            lastmod_text = lastmod.text if lastmod is not None else None
            url_lastmod_list.append(URLInfo(url=loc, lastmod=lastmod_text))

    except requests.exceptions.RequestException as e:
        print(f"Error fetching sitemap content from {sitemap_url}: {e}")
        return []
    except ET.ParseError as e:
        print(f"Error parsing XML from {sitemap_url}: {e}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred while processing {sitemap_url}: {e}")
        return []
    return url_lastmod_list

def process_url(url: str) -> SitemapResult:
    """
    Processes a single URL to retrieve sitemap data.  This function is
    called by the endpoint.

    Args:
        url (str): The URL to process.

    Returns:
        SitemapResult: A SitemapResult object.
    """
    result = SitemapResult(input_url=url)
    sitemap_urls = get_sitemap_urls(url)

    if not sitemap_urls:
        result.error = "No sitemap found"
        return result

    result.sitemap_urls = sitemap_urls
    for sitemap_url in sitemap_urls:
        print(f"  Processing sitemap: {sitemap_url}")
        lastmod_results = get_lastmod_from_sitemap(sitemap_url)
        result.results.extend(lastmod_results)
    return result



@app.post("/process_csv/", response_model=List[SitemapResult])
async def process_csv(
    file: UploadFile = File(..., description="Upload a CSV file containing URLs in the first column.")
) -> List[SitemapResult]:
    """
    Processes a CSV file to retrieve sitemap URLs and their last modification dates for each URL.

    Args:
        file (UploadFile): The CSV file containing URLs.

    Returns:
        List[SitemapResult]: A list of SitemapResult objects, one for each URL in the CSV file.
    """
    results: List[SitemapResult] = []
    try:
        contents = await file.read()
        # Decode the bytes to a string, using a robust encoding
        text_content = contents.decode('utf-8', errors='replace')
        reader = csv.DictReader(StringIO(text_content))

        if not reader.fieldnames or reader.fieldnames[0] != 'url':
            raise HTTPException(status_code=400, detail="CSV file must have a 'url' column in the header.")

        for row in reader:
            try:
                url = row['url']  # Access the URL from the 'url' column
                if not url:
                    raise ValueError("URL is empty")
                # Pydantic validation
                HttpUrl(url)  # Validate the URL using Pydantic
                print(f"Processing URL from CSV: {url}")
                result = process_url(url) # Reuse the process_url function
                results.append(result)
            except ValueError as e:
                results.append(SitemapResult(input_url=row['url'], error=str(e)))
            except ValidationError as e:
                results.append(SitemapResult(input_url=row['url'], error=str(e)))

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing CSV file: {e}")

    return results

    result = SitemapResult(input_url=url) # Initialize the result object
    sitemap_urls = get_sitemap_urls(url)

    if not sitemap_urls:
        result.error = "No sitemap found"
        return result

    result.sitemap_urls = sitemap_urls  # Store the found sitemap URLs
    for sitemap_url in sitemap_urls:
        print(f"  Processing sitemap: {sitemap_url}")
        lastmod_results = get_lastmod_from_sitemap(sitemap_url)
        result.results.extend(lastmod_results)  # Extend the list

    return result

