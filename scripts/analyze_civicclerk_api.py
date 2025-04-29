import sys
import os
import json
import re
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def analyze_site(url):
    """Analyze a CivicClerk site to discover API endpoints"""
    print(f"Analyzing CivicClerk site: {url}")
    
    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
    
    # First, fetch the main page to examine the structure
    try:
        response = session.get(url)
        response.raise_for_status()  # Check for HTTP errors
        html = response.text
        
        # Look for JavaScript files that might contain API references
        js_files = []
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup.find_all('script', src=True):
            if script['src'].endswith('.js'):
                js_files.append(urljoin(url, script['src']))
        
        print(f"Found {len(js_files)} JavaScript files")
        
        # Look for common API patterns in JavaScript files
        api_patterns = [
            r'api/meetings',
            r'api/events',
            r'api/v\d+/meetings',
            r'api/organizations',
            r'graphql',
            r'https://[^"]*?api\.civicclerk\.com/v\d+'  # Added tenant API pattern
        ]
        
        api_endpoints = set()
        
        # Check first 2 JS files (usually the main bundle contains API endpoints)
        for js_url in js_files[:2]:
            print(f"Analyzing JavaScript file: {js_url}")
            try:
                js_response = session.get(js_url)
                js_response.raise_for_status()
                js_content = js_response.text
                
                # Look for API patterns
                for pattern in api_patterns:
                    matches = re.findall(pattern, js_content)
                    for match in matches:
                        api_endpoints.add(match)
                
                # Also try to find complete URLs
                url_pattern = r'"(https://[^"]*?api[^"]*?)"'
                url_matches = re.findall(url_pattern, js_content)
                for url_match in url_matches:
                    api_endpoints.add(url_match)
                
                # Look for tenant-specific API endpoints
                tenant_pattern = r'"(https://[^"]*?\.api\.civicclerk\.com/v\d+)"'
                tenant_matches = re.findall(tenant_pattern, js_content)
                for tenant_match in tenant_matches:
                    api_endpoints.add(tenant_match)
                
            except Exception as e:
                print(f"Error analyzing JS file {js_url}: {e}")
        
        # Try some known GraphQL patterns if present
        if 'graphql' in api_endpoints:
            print("Found GraphQL API reference, this might be a GraphQL-based API")
        
        # Remove duplicates and print discovered endpoints
        domain = urlparse(url).netloc
        base_url = f"https://{domain}"
        tenant_name = domain.split('.')[0]
        
        print("\nDiscovered potential API endpoints:")
        for endpoint in sorted(api_endpoints):
            if endpoint.startswith('http'):
                print(f"  {endpoint}")
            else:
                # Check different variations of the endpoint
                full_endpoint = f"{base_url}/{endpoint}"
                print(f"  {full_endpoint}")
                
                # Try with different HTTP methods
                try:
                    get_response = session.get(full_endpoint)
                    print(f"    GET: Status {get_response.status_code}")
                    if get_response.status_code == 200:
                        try:
                            data = get_response.json()
                            print(f"      Response contains: {list(data.keys()) if isinstance(data, dict) else f'{len(data)} items'}")
                        except:
                            print("      Response is not JSON")
                except Exception as e:
                    print(f"    GET: Error - {e}")
        
        # Try direct API endpoints with different parameters
        print("\nTesting common API endpoints directly:")
        test_endpoints = [
            f"{base_url}/graphql",
            f"{base_url}/api/meetings?pageSize=10",
            f"{base_url}/api/events?pageSize=10",
            f"{base_url}/api/v1/meetings?pageSize=10",
            f"{base_url}/api/organization/meetings?pageSize=10"
        ]
        
        # Add tenant-specific API endpoints
        tenant_endpoints = [
            f"https://{tenant_name}.api.civicclerk.com/v1/meetings?pageSize=10",
            f"https://{tenant_name}.api.civicclerk.com/v1/events?pageSize=10",
            f"https://api.civicclerk.com/v1/organizations/{tenant_name}/meetings?pageSize=10"
        ]
        test_endpoints.extend(tenant_endpoints)
        
        for test_endpoint in test_endpoints:
            try:
                print(f"  Testing: {test_endpoint}")
                test_response = session.get(test_endpoint)
                print(f"    Status: {test_response.status_code}")
                if test_response.status_code == 200:
                    try:
                        data = test_response.json()
                        print(f"      Response contains: {list(data.keys()) if isinstance(data, dict) else f'{len(data)} items'}")
                    except:
                        print("      Response is not JSON")
            except Exception as e:
                print(f"    Error: {e}")
                
    except Exception as e:
        print(f"Error analyzing site {url}: {e}")
        return False
    
    return True

# Test with multiple CivicClerk sites
test_sites = [
    "https://jacksonmi.civicclerk.com",
    "https://alpharettaga.civicclerk.com",
    "https://ranchocordovaca.portal.civicclerk.com"
]

success = False
for site in test_sites:
    print("\n" + "="*50)
    if analyze_site(site):
        success = True
    print("="*50)

if not success:
    print("Failed to analyze any CivicClerk sites.")