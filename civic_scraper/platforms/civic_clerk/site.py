import html
import re
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin
import logging
import requests

import lxml.html
from bs4 import BeautifulSoup
from requests import Session

import civic_scraper
from civic_scraper import base
from civic_scraper.base.asset import Asset, AssetCollection
from civic_scraper.base.cache import Cache

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CivicClerkSite(base.Site):
    def __init__(self, url, place=None, state_or_province=None, cache=Cache()):
        self.url = url
        self.base_url = "https://" + urlparse(url).netloc
        
        # Extract the tenant/organization name from the URL
        parsed_url = urlparse(url)
        domain_parts = parsed_url.netloc.split(".")
        
        # Determine tenant name based on URL structure
        if len(domain_parts) >= 3 and domain_parts[1] == "portal":
            # For portal.civicclerk.com style URLs
            self.civicclerk_instance = domain_parts[0]
            self.is_portal = True
            self.org_id = None  # Will be discovered later
        else:
            # For direct civicclerk.com URLs
            self.civicclerk_instance = domain_parts[0]
            self.is_portal = False
            self.org_id = None  # Will be discovered later
        
        logger.info(f"Detected tenant name: {self.civicclerk_instance}")
        
        self.place = place
        self.state_or_province = state_or_province
        self.cache = cache

        # Set up session with browser-like headers
        self.session = Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": self.url,
            "Origin": self.base_url,
            "DNT": "1",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin"
        })

        # Don't automatically raise exception on error status
        self.session.hooks = {}
        
        # Initialize API endpoints
        self.api_base = None
        self.api_endpoints = {}
        
        # Try to discover the API endpoints and other configuration
        self._discover_api_configuration()

    def _extract_js_urls_from_html(self, html_content):
        """Extract JavaScript URLs from HTML content"""
        js_files = []
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for script in soup.find_all('script', src=True):
                if script['src'].endswith('.js'):
                    js_url = urljoin(self.url, script['src'])
                    js_files.append(js_url)
                    logger.info(f"Found JS file: {js_url}")
        except Exception as e:
            logger.error(f"Error extracting JS URLs: {e}")
        
        return js_files

    def _discover_api_configuration(self):
        """Discover API configuration by analyzing the page and JS files"""
        logger.info(f"Discovering API configuration for {self.url}")
        
        try:
            # First fetch the main page
            response = self.session.get(self.url)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch main page: {response.status_code}")
                return
                
            # Extract JavaScript URLs
            js_files = self._extract_js_urls_from_html(response.text)
            
            # Try to find config in window object
            window_config = self._extract_window_config(response.text)
            if window_config:
                logger.info(f"Found window configuration: {window_config}")
                
                # Extract organization ID if present
                if 'organizationId' in window_config:
                    self.org_id = window_config['organizationId']
                    logger.info(f"Found organization ID: {self.org_id}")
                
                # Extract API URLs if present
                if 'apiUrl' in window_config:
                    api_url = window_config['apiUrl']
                    # Replace tenant placeholder if present
                    if '[TENANT]' in api_url:
                        api_url = api_url.replace('[TENANT]', self.civicclerk_instance)
                    self.api_base = api_url
                    logger.info(f"Found API base URL: {self.api_base}")
            
            # Analyze JS files for more configuration
            for js_url in js_files:
                js_config = self._analyze_js_file(js_url)
                if js_config:
                    logger.info(f"Found configuration in JS file: {js_config}")
                    
                    # Extract organization ID if present
                    if 'organizationId' in js_config and not self.org_id:
                        self.org_id = js_config['organizationId']
                        logger.info(f"Found organization ID: {self.org_id}")
                    
                    # Extract API URLs if present
                    if 'apiUrl' in js_config and not self.api_base:
                        api_url = js_config['apiUrl']
                        # Replace tenant placeholder if present
                        if '[TENANT]' in api_url:
                            api_url = api_url.replace('[TENANT]', self.civicclerk_instance)
                        self.api_base = api_url
                        logger.info(f"Found API base URL: {self.api_base}")
                        
                    # If we found endpoints list, save them
                    if 'endpoints' in js_config:
                        for endpoint in js_config['endpoints']:
                            # Replace tenant placeholder if present
                            if '[TENANT]' in endpoint:
                                endpoint = endpoint.replace('[TENANT]', self.civicclerk_instance)
                            
                            # Determine endpoint type by URL path
                            if '/meetings' in endpoint:
                                self.api_endpoints['meetings'] = endpoint
                                logger.info(f"Found meetings endpoint: {endpoint}")
                            elif '/documents' in endpoint or '/attachments' in endpoint:
                                self.api_endpoints['documents'] = endpoint
                                logger.info(f"Found documents endpoint: {endpoint}")
                            elif '/events' in endpoint:
                                self.api_endpoints['events'] = endpoint
                                logger.info(f"Found events endpoint: {endpoint}")
            
            # If we still don't have endpoints, try to detect from network activity
            if not self.api_endpoints:
                self._detect_api_from_network()
                
            # If we still don't have endpoints, construct them from what we know
            if not self.api_base and self.api_endpoints.get('meetings') is None:
                self._construct_api_endpoints()
                
        except Exception as e:
            logger.error(f"Error discovering API configuration: {e}")
            # If discovery fails, construct endpoints anyway
            self._construct_api_endpoints()

    def _extract_window_config(self, html_content):
        """Extract configuration from window object in HTML"""
        config = {}
        
        # Look for window.__INITIAL_CONFIG__ or similar objects
        patterns = [
            r'window\.__INITIAL_CONFIG__\s*=\s*({.*?});',
            r'window\.APP_CONFIG\s*=\s*({.*?});',
            r'window\.config\s*=\s*({.*?});'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html_content, re.DOTALL)
            if match:
                try:
                    # Extract the JSON-like config object
                    config_str = match.group(1)
                    # Clean up the string to make it valid JSON
                    config_str = re.sub(r'([{,])\s*(\w+):', r'\1"\2":', config_str)
                    # Replace javascript true/false with JSON true/false
                    config_str = config_str.replace('true', 'true').replace('false', 'false')
                    # Parse as JSON
                    config_data = json.loads(config_str)
                    config.update(config_data)
                except Exception as e:
                    logger.debug(f"Error parsing window config: {e}")
                    
        return config

    def _analyze_js_file(self, js_url):
        """Analyze JavaScript file for API configuration"""
        config = {}
        endpoints = []
        
        try:
            response = self.session.get(js_url)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch JS file: {response.status_code}")
                return config
                
            js_content = response.text
            
            # Look for API URL patterns
            api_patterns = [
                # API base URLs
                (r'baseUrl:\s*["\']([^"\']+)["\']', 'apiUrl'),
                (r'apiUrl:\s*["\']([^"\']+)["\']', 'apiUrl'),
                (r'API_URL:\s*["\']([^"\']+)["\']', 'apiUrl'),
                (r'API_BASE_URL:\s*["\']([^"\']+)["\']', 'apiUrl'),
                
                # Organization/tenant identifiers
                (r'organizationId:\s*["\']([^"\']+)["\']', 'organizationId'),
                (r'ORGANIZATION_ID:\s*["\']([^"\']+)["\']', 'organizationId'),
                (r'tenantId:\s*["\']([^"\']+)["\']', 'tenantId'),
                (r'TENANT_ID:\s*["\']([^"\']+)["\']', 'tenantId'),
                (r'clientId:\s*["\']([^"\']+)["\']', 'clientId')
            ]
            
            # Extract API configuration
            for pattern, key in api_patterns:
                match = re.search(pattern, js_content)
                if match:
                    config[key] = match.group(1)
            
            # Look for API endpoint patterns
            endpoint_patterns = [
                r'["\']([^"\']*?/api/[^"\']+)["\']',
                r'["\']([^"\']*?/meetings[^"\']*?)["\']',
                r'["\']([^"\']*?/events[^"\']*?)["\']',
                r'["\'](https://[^"\']*?\.api\.civicclerk\.com[^"\']*?)["\']'
            ]
            
            # Extract endpoint URLs
            for pattern in endpoint_patterns:
                matches = re.findall(pattern, js_content)
                for match in matches:
                    # Skip duplicates and obviously not API routes
                    if match not in endpoints and not any(skip in match for skip in ['fonts', 'static', '.js', '.css']):
                        endpoints.append(match)
            
            if endpoints:
                config['endpoints'] = endpoints
                
            # Check for service worker or API interceptor patterns
            api_url_pattern = r'fetch\(["\']([^"\']+)["\']'
            for match in re.findall(api_url_pattern, js_content):
                if '/api/' in match and match not in endpoints:
                    endpoints.append(match)
                    
            # Look for template API URLs
            template_patterns = [
                r'["\']https://\[TENANT\]\.api\.civicclerk\.com([^"\']*)["\']',
                r'["\']https://([^"\']*)\[organizationId\]([^"\']*)["\']'
            ]
            
            for pattern in template_patterns:
                for match in re.findall(pattern, js_content):
                    if isinstance(match, tuple):
                        # For patterns with multiple capture groups
                        template_url = f"https://{self.civicclerk_instance}.api.civicclerk.com{match[0]}{match[1]}"
                    else:
                        # For patterns with a single capture group
                        template_url = f"https://{self.civicclerk_instance}.api.civicclerk.com{match}"
                        
                    if template_url not in endpoints:
                        endpoints.append(template_url)
            
            if endpoints:
                config['endpoints'] = endpoints
                
        except Exception as e:
            logger.error(f"Error analyzing JS file {js_url}: {e}")
            
        return config

    def _detect_api_from_network(self):
        """
        Detect API endpoints by analyzing network traffic.
        This is a simple implementation without a headless browser.
        """
        logger.info("Attempting to detect API from network requests")
        
        try:
            # Make a request to the page with developer tools open
            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Dest": "empty"
            }
            
            # Try common API paths by directly requesting them
            api_paths = [
                "/api/meetings",
                "/api/v1/meetings",
                "/v1/meetings",
                "/api/events",
                "/meetings"
            ]
            
            # Try common API hosts
            api_hosts = [
                self.base_url,
                f"https://{self.civicclerk_instance}.api.civicclerk.com",
                "https://api.civicclerk.com"
            ]
            
            # Add query parameters for each request
            params = {
                "pageSize": "10",
                "page": "0",
                "sortBy": "date",
                "sortDirection": "desc"
            }
            
            for host in api_hosts:
                for path in api_paths:
                    endpoint = f"{host}{path}"
                    try:
                        logger.info(f"Testing API endpoint: {endpoint}")
                        response = self.session.get(endpoint, headers=headers, params=params)
                        
                        if response.status_code == 200:
                            try:
                                data = response.json()
                                # Check if the response looks like meetings data
                                if self._validate_meetings_response(data):
                                    logger.info(f"Found working meetings API: {endpoint}")
                                    self.api_endpoints['meetings'] = endpoint
                                    return
                            except ValueError:
                                # Not JSON response
                                pass
                    except Exception as e:
                        logger.debug(f"Error testing endpoint {endpoint}: {e}")
            
            # If we get here, try special-case endpoints for Rancho Cordova
            if 'portal.civicclerk.com' in self.base_url:
                # Try with tenant-specific public API
                special_endpoint = f"https://{self.civicclerk_instance}.api.civicclerk.com/v1/meetings"
                logger.info(f"Testing special API endpoint: {special_endpoint}")
                try:
                    response = self.session.get(special_endpoint, headers=headers, params=params)
                    if response.status_code == 200:
                        try:
                            data = response.json()
                            if self._validate_meetings_response(data):
                                logger.info(f"Found working meetings API: {special_endpoint}")
                                self.api_endpoints['meetings'] = special_endpoint
                                return
                        except ValueError:
                            pass
                except Exception as e:
                    logger.debug(f"Error testing special endpoint: {e}")
                    
        except Exception as e:
            logger.error(f"Error detecting API from network: {e}")

    def _construct_api_endpoints(self):
        """Construct API endpoints based on detected tenant name"""
        logger.info("Constructing API endpoints from tenant name")
        
        # For portal sites, use a different endpoint pattern
        if self.is_portal:
            self.api_base = f"https://{self.civicclerk_instance}.api.civicclerk.com/v1"
            logger.info(f"Constructed API base for portal: {self.api_base}")
        else:
            # Try both tenant-specific and shared API patterns
            self.api_base = f"https://{self.civicclerk_instance}.api.civicclerk.com/v1"
            logger.info(f"Constructed API base for regular site: {self.api_base}")
            
        # Set up common endpoints
        self.api_endpoints = {
            'meetings': f"{self.api_base}/meetings",
            'events': f"{self.api_base}/events",
            'documents': f"{self.api_base}/documents"
        }

    def _validate_meetings_response(self, data):
        """Validate if the API response contains meeting data"""
        if data is None:
            return False
            
        if isinstance(data, list) and len(data) > 0:
            # Check if the list items look like meetings
            if any('name' in item or 'date' in item or 'id' in item for item in data):
                return True
                
        if isinstance(data, dict):
            # Check for common response patterns
            if 'items' in data and isinstance(data['items'], list) and len(data['items']) > 0:
                return True
            if 'meetings' in data and isinstance(data['meetings'], list) and len(data['meetings']) > 0:
                return True
            if 'data' in data and isinstance(data['data'], dict) and 'meetings' in data['data']:
                return True
            if 'data' in data and isinstance(data['data'], list) and len(data['data']) > 0:
                return True
                
        return False

    def create_asset(self, asset, committee_name, meeting_datetime, meeting_id):
        """Create an Asset object from raw asset data"""
        asset_url, asset_name = asset
        asset_type = "Meeting"

        e = {
            "url": asset_url,
            "asset_name": asset_name,
            "committee_name": committee_name,
            "place": self.place,
            "state_or_province": self.state_or_province,
            "asset_type": asset_type,
            "meeting_date": meeting_datetime.date(),
            "meeting_time": meeting_datetime.time(),
            "meeting_id": meeting_id,
            "scraped_by": f"civic-scraper_{civic_scraper.__version__}",
            "content_type": "txt",
            "content_length": None,
        }
        return Asset(**e)

    def _fetch_meetings_from_api(self):
        """Fetch meetings from the CivicClerk API using multiple approaches"""
        meetings = []
        
        if not self.api_endpoints.get('meetings'):
            logger.warning("No API endpoint for meetings available")
            return meetings
            
        endpoint = self.api_endpoints['meetings']
        logger.info(f"Fetching meetings from API: {endpoint}")
        
        # Define headers for API request
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.url,
            "Origin": self.base_url
        }
        
        # Define query parameters for meetings
        params = {
            "page": 0,
            "pageSize": 50,  # Get more meetings at once
            "sortBy": "date",
            "sortDirection": "desc"
        }
        
        try:
            # Make the API request
            response = self.session.get(endpoint, headers=headers, params=params)
            
            # Handle different status codes
            if response.status_code == 200:
                try:
                    data = response.json()
                    logger.info(f"API response status code: {response.status_code}")
                    
                    # Extract meetings from the response based on its structure
                    if isinstance(data, list):
                        meetings = data
                        logger.info(f"Found {len(meetings)} meetings in list format")
                    elif isinstance(data, dict):
                        # Check different possible response structures
                        if 'items' in data and isinstance(data['items'], list):
                            meetings = data['items']
                            logger.info(f"Found {len(meetings)} meetings in 'items' key")
                        elif 'meetings' in data and isinstance(data['meetings'], list):
                            meetings = data['meetings']
                            logger.info(f"Found {len(meetings)} meetings in 'meetings' key")
                        elif 'data' in data:
                            if isinstance(data['data'], list):
                                meetings = data['data']
                                logger.info(f"Found {len(meetings)} meetings in 'data' key (list)")
                            elif isinstance(data['data'], dict) and 'meetings' in data['data']:
                                meetings = data['data']['meetings']
                                logger.info(f"Found {len(meetings)} meetings in 'data.meetings' key")
                        else:
                            logger.warning("Unknown API response structure:")
                            logger.warning(f"Response keys: {list(data.keys())}")
                            
                except ValueError:
                    logger.warning("Invalid JSON response from API")
            else:
                logger.warning(f"API request failed with status code: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error fetching meetings from API: {e}")
            
        # If the first endpoint didn't work, try alternatives
        if not meetings and 'events' in self.api_endpoints:
            try:
                endpoint = self.api_endpoints['events']
                logger.info(f"Trying alternate endpoint: {endpoint}")
                
                response = self.session.get(endpoint, headers=headers, params=params)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        # Process the data similar to above
                        if isinstance(data, list):
                            meetings = data
                        elif isinstance(data, dict):
                            for key in ['items', 'events', 'data', 'meetings']:
                                if key in data and (isinstance(data[key], list) or 
                                                   (isinstance(data[key], dict) and 'items' in data[key])):
                                    meetings = data[key] if isinstance(data[key], list) else data[key]['items']
                                    break
                                    
                        logger.info(f"Found {len(meetings)} meetings from alternate endpoint")
                    except ValueError:
                        logger.warning("Invalid JSON from alternate endpoint")
            except Exception as e:
                logger.error(f"Error with alternate endpoint: {e}")
        
        return meetings

    def _get_documents_from_api(self, meeting_id):
        """Fetch documents for a meeting from the API"""
        assets = []
        
        # If we have no API endpoints, we can't get documents
        if not self.api_endpoints.get('meetings'):
            logger.warning("No API endpoint available to fetch documents")
            return assets
            
        # Try different document endpoint patterns
        if 'documents' in self.api_endpoints:
            document_endpoint = self.api_endpoints['documents']
        else:
            # Construct document endpoint from meetings endpoint
            base_api_path = "/".join(self.api_endpoints['meetings'].split("/")[:-1])
            document_endpoint = f"{base_api_path}/documents"
            
        # Try different document patterns
        document_patterns = [
            f"{self.api_endpoints['meetings']}/{meeting_id}/documents",
            f"{self.api_endpoints['meetings']}/{meeting_id}/attachments",
            f"{document_endpoint}?meetingId={meeting_id}"
        ]
        
        # Try each document endpoint
        for endpoint in document_patterns:
            try:
                logger.info(f"Fetching documents from: {endpoint}")
                
                # Define headers for API request
                headers = {
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.url,
                    "Origin": self.base_url
                }
                
                response = self.session.get(endpoint, headers=headers)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        
                        # Extract documents based on response structure
                        documents = []
                        
                        if isinstance(data, list):
                            documents = data
                        elif isinstance(data, dict):
                            for key in ['items', 'documents', 'attachments', 'data']:
                                if key in data and data[key]:
                                    documents = data[key] if isinstance(data[key], list) else [data[key]]
                                    break
                        
                        # Process documents
                        for doc in documents:
                            if isinstance(doc, dict):
                                doc_id = doc.get('id')
                                doc_name = doc.get('name') or doc.get('fileName') or doc.get('title', 'Agenda Document')
                                
                                # Try different document URL patterns
                                doc_url = None
                                for url_field in ['url', 'downloadUrl', 'fileUrl', 'path', 'link']:
                                    if url_field in doc and doc[url_field]:
                                        doc_url = doc[url_field]
                                        if not doc_url.startswith('http'):
                                            doc_url = urljoin(self.base_url, doc_url)
                                        break
                                
                                # If no URL found but we have an ID, construct one
                                if not doc_url and doc_id:
                                    doc_url = f"{self.base_url}/documents/{doc_id}"
                                
                                if doc_url:
                                    assets.append((doc_url, doc_name))
                        
                        if assets:
                            logger.info(f"Found {len(assets)} documents for meeting {meeting_id}")
                            return assets
                            
                    except ValueError:
                        logger.debug("Invalid JSON response for documents")
                        
            except Exception as e:
                logger.debug(f"Error fetching documents: {e}")
                
        # If no documents were found, try one more approach with meeting details
        try:
            meeting_details_endpoint = f"{self.api_endpoints['meetings']}/{meeting_id}"
            logger.info(f"Trying meeting details endpoint: {meeting_details_endpoint}")
            
            response = self.session.get(meeting_details_endpoint)
            if response.status_code == 200:
                try:
                    details = response.json()
                    
                    # Look for documents in meeting details
                    if isinstance(details, dict):
                        for doc_field in ['documents', 'attachments', 'agendaDocuments', 'minutesDocuments']:
                            if doc_field in details and details[doc_field]:
                                docs = details[doc_field] if isinstance(details[doc_field], list) else [details[doc_field]]
                                
                                for doc in docs:
                                    if isinstance(doc, dict):
                                        doc_id = doc.get('id')
                                        doc_name = doc.get('name') or doc.get('fileName') or doc.get('title', 'Document')
                                        
                                        # Try different URL fields
                                        doc_url = None
                                        for url_field in ['url', 'downloadUrl', 'fileUrl', 'path']:
                                            if url_field in doc and doc[url_field]:
                                                doc_url = doc[url_field]
                                                if not doc_url.startswith('http'):
                                                    doc_url = urljoin(self.base_url, doc_url)
                                                break
                                        
                                        if not doc_url and doc_id:
                                            doc_url = f"{self.base_url}/documents/{doc_id}"
                                            
                                        if doc_url:
                                            assets.append((doc_url, doc_name))
                except ValueError:
                    pass
                    
        except Exception as e:
            logger.debug(f"Error with meeting details: {e}")
            
        # If still no documents found, include the meeting URL as an asset
        if not assets:
            meeting_url = f"{self.base_url}/meetings/{meeting_id}"
            assets.append((meeting_url, "Meeting Information"))
            
        return assets

    def _fetch_meetings_from_dom(self):
        """Attempt to extract meeting information from the DOM when API fails"""
        meetings = []
        logger.info("Attempting to extract meetings from DOM")
        
        try:
            # Make request with additional headers to mimic browser
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache"
            }
            
            response = self.session.get(self.url, headers=headers)
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch page: {response.status_code}")
                return meetings
                
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # First look for meeting cards or similar structures
            meeting_elements = soup.select('.meeting-card, .meeting-row, .event-card, [data-meeting-id]')
            
            if not meeting_elements:
                # Try more general selectors
                meeting_elements = soup.select('[id*="meeting"], [class*="meeting"], [class*="event"], [data-type="meeting"]')
            
            # If still no elements, try finding elements with date information
            if not meeting_elements:
                meeting_elements = soup.select('time, [datetime], [class*="date"]')
                
            # Process found elements
            for element in meeting_elements:
                # Try to determine if this is actually a meeting element
                parent = element
                for _ in range(3):  # Check up to 3 levels up
                    if parent.name == 'div' or parent.name == 'li' or parent.name == 'article':
                        # This might be a container for a meeting
                        break
                    parent = parent.parent
                
                # Extract meeting details
                meeting = {}
                
                # Get meeting ID
                meeting_id = parent.get('data-meeting-id', '') or parent.get('id', '')
                if not meeting_id:
                    # Generate a random ID
                    import uuid
                    meeting_id = str(uuid.uuid4())
                meeting['id'] = meeting_id
                
                # Get meeting name
                name_element = parent.select_one('h2, h3, h4, [class*="title"], [class*="name"]')
                if name_element:
                    meeting['name'] = name_element.get_text(strip=True)
                else:
                    meeting['name'] = "Meeting"
                
                # Get meeting date
                date_element = parent.select_one('time, [datetime], [class*="date"], [class*="time"]')
                if date_element:
                    if date_element.has_attr('datetime'):
                        meeting['date'] = date_element['datetime']
                    else:
                        meeting['date'] = date_element.get_text(strip=True)
                
                # Get committee/group name
                group_element = parent.select_one('[class*="committee"], [class*="board"], [class*="group"]')
                if group_element:
                    meeting['groupName'] = group_element.get_text(strip=True)
                else:
                    meeting['groupName'] = "Committee"
                    
                # Only add if we have at least an ID and name
                if meeting['id'] and meeting['name']:
                    meetings.append(meeting)
            
            logger.info(f"Found {len(meetings)} meetings from DOM")
            
        except Exception as e:
            logger.error(f"Error extracting meetings from DOM: {e}")
            
        return meetings

    def _parse_meeting_datetime(self, meeting):
        """Parse meeting datetime from various formats"""
        meeting_datetime = None
        
        # Look for date in various fields
        date_str = None
        for field in ['date', 'dateTime', 'startTime', 'startDate', 'meetingDate', 'datetime']:
            if field in meeting and meeting[field]:
                date_str = meeting[field]
                break
                
        if not date_str:
            logger.warning(f"No date found for meeting {meeting.get('id')}")
            return datetime.now()  # Default to current datetime
            
        # Try different datetime formats
        formats = [
            None,  # Try ISO format
            "%Y-%m-%dT%H:%M:%S", 
            "%Y-%m-%dT%H:%M:%S.%fZ", 
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y",
            "%B %d, %Y",
            "%b %d, %Y %I:%M %p"
        ]
        
        for fmt in formats:
            try:
                if fmt is None:
                    # Try ISO format first (handles most date formats)
                    meeting_datetime = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    meeting_datetime = datetime.strptime(date_str, fmt)
                break
            except (ValueError, TypeError):
                continue
        else:
            # If all formats fail, try a more permissive approach
            logger.warning(f"Could not parse date '{date_str}' with standard formats, using fallbacks")
            
            # Remove any timezone info that might be causing problems
            clean_date = re.sub(r'[+-]\d{2}:\d{2}$', '', date_str)
            clean_date = clean_date.replace('Z', '')
            
            try:
                meeting_datetime = datetime.fromisoformat(clean_date)
            except ValueError:
                # Last resort - use current datetime
                logger.warning(f"Using fallback datetime for '{date_str}'")
                meeting_datetime = datetime.now()
                
        return meeting_datetime

    def events(self):
        """Get events from the CivicClerk site using API or DOM parsing as a fallback"""
        # First try the API approach
        api_meetings = self._fetch_meetings_from_api()
        if api_meetings:
            logger.info(f"Yielding {len(api_meetings)} meetings from API")
            yield api_meetings
            return
            
        # If API failed, try DOM parsing
        dom_meetings = self._fetch_meetings_from_dom()
        if dom_meetings:
            logger.info(f"Yielding {len(dom_meetings)} meetings from DOM")
            yield dom_meetings
            return
            
        # If all else failed, try a direct fetch for a calendar page
        calendar_url = f"{self.base_url}/calendar"
        try:
            logger.info(f"Trying calendar page: {calendar_url}")
            response = self.session.get(calendar_url)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                calendar_meetings = []
                
                # Look for meeting elements in calendar view
                calendar_elements = soup.select('[class*="event"], [class*="meeting"], .calendar-item')
                
                for element in calendar_elements:
                    meeting = {}
                    
                    # Generate an ID
                    import uuid
                    meeting['id'] = str(uuid.uuid4())
                    
                    # Get title/name
                    title_element = element.select_one('[class*="title"], [class*="name"], h3, h4')
                    if title_element:
                        meeting['name'] = title_element.get_text(strip=True)
                    else:
                        meeting['name'] = "Calendar Meeting"
                        
                    # Get date
                    date_element = element.select_one('[class*="date"], time, [datetime]')
                    if date_element:
                        if date_element.has_attr('datetime'):
                            meeting['date'] = date_element['datetime']
                        else:
                            meeting['date'] = date_element.get_text(strip=True)
                    else:
                        # Skip items without dates
                        continue
                        
                    # Get committee name
                    committee_element = element.select_one('[class*="committee"], [class*="group"]')
                    if committee_element:
                        meeting['groupName'] = committee_element.get_text(strip=True)
                    else:
                        meeting['groupName'] = "Committee"
                        
                    calendar_meetings.append(meeting)
                    
                if calendar_meetings:
                    logger.info(f"Yielding {len(calendar_meetings)} meetings from calendar page")
                    yield calendar_meetings
                    return
                    
        except Exception as e:
            logger.error(f"Error with calendar page: {e}")
            
        logger.warning("Could not retrieve any meetings via API or DOM parsing")
        yield []  # Return empty list as last resort

    def _get_agenda_items_api(self, meeting_id):
        """Fetch agenda items for a meeting, using API or DOM as needed."""
        # Try to get documents from API first
        assets = self._get_documents_from_api(meeting_id)
            
        # If no assets found via API, try a fallback
        if not assets:
            # Just add the meeting URL as an asset
            meeting_url = f"{self.base_url}/meetings/{meeting_id}"
            assets.append((meeting_url, "Meeting Information"))
            
        return assets

    def scrape(self, download=True):
        """Scrape meetings and their assets from the CivicClerk site."""
        ac = AssetCollection()
        logger.info(f"Starting to scrape meetings from {self.url}")

        # Iterate through events
        meeting_count = 0
        for events_batch in self.events():
            if not events_batch:
                continue
                
            for event in events_batch:
                try:
                    # Extract meeting details
                    logger.info(f"Processing event: {event.get('name', 'Unknown')}")
                    
                    committee_name = event.get('groupName', event.get('name', 'Unknown Committee'))
                    meeting_datetime = self._parse_meeting_datetime(event)
                    
                    # Get the meeting ID
                    meeting_id_raw = event.get('id')
                    if not meeting_id_raw:
                        logger.warning("Meeting has no ID, skipping")
                        continue
                        
                    meeting_id = f"civicclerk_{self.civicclerk_instance}_{meeting_id_raw}"
                    
                    # Get agenda items and documents
                    agenda_items = self._get_agenda_items_api(meeting_id_raw)
                    
                    if agenda_items:
                        assets = [
                            self.create_asset(a, committee_name, meeting_datetime, meeting_id)
                            for a in agenda_items
                        ]
                        for a in assets:
                            ac.append(a)
                            logger.info(f"Added asset: {a.asset_name}")
                            meeting_count += 1
                    else:
                        logger.warning(f"No agenda items found for meeting {meeting_id_raw}")
                        
                except Exception as e:
                    logger.error(f"Error processing meeting: {e}")
                    continue

        logger.info(f"Found {meeting_count} total assets across all meetings")
        
        if download and len(ac) > 0:
            asset_dir = Path(self.cache.path, "assets")
            asset_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Downloading {len(ac)} assets to {asset_dir}")
            for asset in ac:
                if asset.url:
                    dir_str = str(asset_dir)
                    asset.download(target_dir=dir_str, session=self.session)

        return ac
