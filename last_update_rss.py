import csv
import json
import xml.etree.ElementTree as ET
import requests
from io import StringIO
import os

def get_sitemap_urls(url):
    """
    Retrieves sitemap URLs from a given URL. Handles both sitemap index files
    and regular sitemap files.

    Args:
        url (str): The URL to check for sitemaps.

    Returns:
        list: A list of sitemap URLs.  Returns an empty list on error
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
            print(f"Error: {url} does not appear to be a sitemap or sitemap index.")
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

def get_lastmod_from_sitemap(sitemap_url):
    """
    Retrieves URLs and their lastmod dates from a sitemap URL.

    Args:
        sitemap_url (str): The URL of the sitemap.

    Returns:
        list: A list of dictionaries, where each dictionary contains 'url' and 'lastmod'.
                Returns an empty list on error.
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
            url_lastmod_list.append({'url': loc, 'lastmod': lastmod_text})

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

def process_urls_from_csv(csv_file_path, output_format="json", output_file_path="output"):
    """
    Processes URLs from a CSV file, retrieves sitemap data, and outputs it to a file.

    Args:
        csv_file_path (str): Path to the CSV file containing URLs.
        output_format (str, optional):  "json" or "csv". Defaults to "json".
        output_file_path (str, optional): Path to the output file (without extension).
    """
    all_results = []
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            # Skip the header row, if it exists
            next(reader, None)
            for row in reader:
                if row: # Make sure the row is not empty
                    url = row[0]  # Assuming URL is the first column
                    print(f"Processing URL: {url}")
                    sitemap_urls = get_sitemap_urls(url)
                    if sitemap_urls: # Check if sitemap urls were found
                        for sitemap_url in sitemap_urls:
                            print(f"  Processing sitemap: {sitemap_url}")
                            results = get_lastmod_from_sitemap(sitemap_url)
                            all_results.extend(results)
                    else:
                         all_results.append({'url': url, 'lastmod': 'No sitemap found'})

    except FileNotFoundError:
        print(f"Error: CSV file not found at {csv_file_path}")
        return
    except Exception as e:
        print(f"An error occurred while reading the CSV file: {e}")
        return

    # Output the results
    if all_results:
        if output_format.lower() == "json":
            with open(f"{output_file_path}.json", 'w', encoding='utf-8') as jsonfile:
                json.dump(all_results, jsonfile, indent=4)
            print(f"Results written to {output_file_path}.json")
        elif output_format.lower() == "csv":
            with open(f"{output_file_path}.csv", 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=['url', 'lastmod'])
                writer.writeheader()
                writer.writerows(all_results)
            print(f"Results written to {output_file_path}.csv")
        else:
            print("Error: Invalid output format. Please choose 'json' or 'csv'.")
    else:
        print("No results to output.")

if __name__ == "__main__":
    # Get user inputs
    csv_file_path = input("Enter the path to the CSV file containing URLs: ")
    output_format = input("Enter the output format (json or csv): ").lower()
    output_file_path = input("Enter the path to the output file (without extension): ")

    # Validate user inputs
    if not os.path.exists(csv_file_path):
        print(f"Error: CSV file not found at {csv_file_path}")
        exit()

    if output_format not in ["json", "csv"]:
        print("Error: Invalid output format. Please choose 'json' or 'csv'.")
        exit()
    
    # Process URLs and generate output
    process_urls_from_csv(csv_file_path, output_format, output_file_path)
