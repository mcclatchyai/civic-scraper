import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime
from urllib.parse import urljoin, urlparse
import os
from abc import ABC, abstractmethod
import logging

# Configure logging - Basic configuration, can be overridden by the main script
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GranicusBaseScraper(ABC):
    """
    Abstract base class for scraping Granicus platforms.
    """
    def __init__(self):
        self.base_url = None # Will be set from the input URL

    def _fetch_html(self, url: str) -> str | None:
        """
        Fetches HTML content from a specified URL.
        Saves HTML to a local file for debugging if enabled.
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching URL {url}: {e}")
            return None

    def _make_absolute_url(self, link_url: str | None) -> str | None:
        """
        Ensures a URL is absolute.
        """
        if not link_url or not self.base_url:
            return None
        if link_url.startswith(('http://', 'https://')):
            return link_url
        return urljoin(self.base_url, link_url)

    def _extract_site_name(self, url: str) -> str:
        """
        Extracts the site name from the URL (e.g., "cityofbradenton" from "cityofbradenton.granicus.com").
        """
        parsed_url = urlparse(url)
        domain_parts = parsed_url.netloc.split('.')
        # More robust check for granicus domains like city.state.granicus.com or city.granicus.com
        if 'granicus' in domain_parts:
            try:
                granicus_index = domain_parts.index('granicus')
                if granicus_index > 0:
                    return domain_parts[granicus_index -1] # Return the part before 'granicus'
            except ValueError:
                pass # 'granicus' not in domain_parts, should not happen if pre-checked
        # Fallback for other structures or if the above fails
        if len(domain_parts) > 1 and domain_parts[-2] == 'granicus' and domain_parts[-1] in ['com', 'org', 'us', 'gov', 'ca', 'gov.uk']:
            return domain_parts[0]
        return parsed_url.netloc.replace('.', '_')


    def _normalize_meeting_id(self, name: str) -> str:
        """
        Normalizes a meeting name to create a meeting ID.
        Example: "Regular City Commission Meeting" -> "Regular-City-Commission-Meeting"
        """
        if not name:
            return "unknown-meeting"
        name = re.sub(r'[^\w\s-]', '', name)  
        name = re.sub(r'\s+', '-', name.strip())
        return name
    
    def _parse_date_time(self, date_str: str | None, time_str: str | None) -> tuple[str, str]:
        """
        Parses date and time strings and formats them.
        Returns (formatted_date, formatted_time)
        """
        parsed_date_str = ""
        parsed_time_str = "00:00:00" # Default time

        if date_str:
            clean_date_str = date_str.replace('\xa0', ' ').strip()
            clean_date_str = re.sub(r'\s*-\s*', ' ', clean_date_str) # Normalize dashes
            clean_date_str = re.sub(r'\s+', ' ', clean_date_str)     # Normalize whitespace
            
            # Attempt to extract time if it's embedded in the date string and time_str is not provided
            if not time_str:
                time_in_date_match = re.search(r'(\d{1,2}[:\.]\d{2}\s*(?:AM|PM|am|pm)?)', clean_date_str)
                if time_in_date_match:
                    time_str = time_in_date_match.group(1)
                    # Remove the extracted time from the date string to avoid parsing issues
                    clean_date_str = clean_date_str.replace(time_in_date_match.group(1), '').strip()
            
            try:
                # python-dateutil is highly recommended for robust date parsing
                import dateutil.parser
                # Ignore timezone information if present, parse as naive datetime
                dt_obj = dateutil.parser.parse(clean_date_str, ignoretz=True)
                parsed_date_str = dt_obj.strftime("%Y-%m-%d")
            except (ValueError, ImportError, OverflowError): # Added OverflowError for very old dates
                logger.debug(f"dateutil.parser failed for '{clean_date_str}', trying manual formats.")
                # Fallback to manual parsing if dateutil fails or isn't available
                # Common date formats observed on Granicus sites
                date_formats_to_try = [
                    "%B %d, %Y",        # January 01, 2023
                    "%b %d, %Y",         # Jan 01, 2023
                    "%m/%d/%Y",          # 01/01/2023
                    "%Y-%m-%d",          # 2023-01-01
                    "%A, %B %d, %Y",   # Tuesday, January 01, 2023
                    "%b. %d, %Y",        # Jan. 01, 2023
                    "%B %d %Y",          # January 1 2023 (no comma)
                    "%b %d %Y",          # Jan 1 2023 (no comma)
                    "%m-%d-%y",          # 01-01-23 (short year)
                    "%m/%d/%y",          # 01/01/23 (short year)
                ]
                for fmt in date_formats_to_try:
                    try:
                        dt_obj = datetime.strptime(clean_date_str, fmt)
                        parsed_date_str = dt_obj.strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
            
            if not parsed_date_str:
                logger.warning(f"Could not parse date: '{date_str}' (cleaned: '{clean_date_str}')")

        if time_str:
            time_str_cleaned = time_str.replace('.', '').replace('\xa0', ' ').strip()
            
            time_formats_to_try = [
                "%I:%M %p", "%H:%M %p", "%I:%M%p", "%H:%M%p",  
                "%H:%M:%S", "%H:%M",
                "%I:%M %p", # For "1:00 PM"
                "%I%M %p",  # For "100 PM" (less common but possible)
            ]
            for fmt in time_formats_to_try:
                try:
                    dt_obj = datetime.strptime(time_str_cleaned, fmt)
                    parsed_time_str = dt_obj.strftime("%H:%M:%S")
                    break
                except ValueError:
                    continue
                    
            if parsed_time_str == "00:00:00" and time_str_cleaned: # If standard parsing failed but there was a time string
                # More aggressive parsing for formats like "1 PM" or "1300"
                time_match_aggressive = re.match(r'(\d{1,2})(?:[:\.]?(\d{2}))?\s*(AM|PM|am|pm)?', time_str_cleaned)
                if time_match_aggressive:
                    hour_str, minute_str, ampm_str = time_match_aggressive.groups()
                    hour = int(hour_str)
                    minute = int(minute_str) if minute_str else 0

                    if ampm_str:
                        ampm = ampm_str.lower()
                        if ampm == 'pm' and hour < 12:
                            hour += 12
                        elif ampm == 'am' and hour == 12: # Midnight case
                            hour = 0
                    # Basic validation for 24-hour format without AM/PM
                    elif hour_str and len(hour_str) == 4 and not minute_str and not ampm_str: # e.g. 1300
                        try:
                            hour = int(hour_str[0:2])
                            minute = int(hour_str[2:4])
                        except ValueError:
                            logger.warning(f"Could not parse military time '{hour_str}'")


                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        parsed_time_str = f"{hour:02d}:{minute:02d}:00"
                    else:
                        logger.warning(f"Aggressively parsed time '{time_str_cleaned}' resulted in invalid hour/minute. Using default.")
                else:
                    logger.warning(f"Could not parse time: '{time_str}', using default 00:00:00.")

        return parsed_date_str, parsed_time_str

    def _get_state_by_site(self, site_name: str) -> str:
        """
        Placeholder for mapping site names to state codes.
        This would require a comprehensive list or a more sophisticated lookup.
        """
        # This map should be expanded or managed externally for a real application
        site_to_state_map = {
            "sacramento": "CA",
            "cityofbradenton": "FL",
            "marysvilleca": "CA",
            "coralsprings": "FL",
            "sibfl": "FL",
            "rocklin-ca": "CA", # Added from test cases
            # Add more mappings as needed
        }
        return site_to_state_map.get(site_name.lower(), "")

    def _transform_to_standard_format(self, extracted_items: list[dict], site_url: str, committee_name_input: str | None) -> list[dict]:
        """
        Transforms raw extracted data into the standardized JSON format.
        """
        standardized_meetings = []
        site_name = self._extract_site_name(site_url)
        
        for item in extracted_items:
            meeting_name = item.get('name')
            meeting_date_str, meeting_time_str = self._parse_date_time(item.get('date'), item.get('time'))

            if not meeting_name or not meeting_date_str: # Date must be successfully parsed
                logger.warning(f"Skipping item due to missing name or unparsable/empty date: Name='{meeting_name}', Date='{item.get('date')}'")
                continue

            committee = committee_name_input if committee_name_input else item.get('committee', "Unknown Committee")

            # Create a more unique meeting ID
            unique_id_str = f"{meeting_date_str}-{meeting_name}-{committee}-{item.get('meeting_id_source','')}"
            meeting_id = self._normalize_meeting_id(unique_id_str)

            standard_item = {
                "asset_name": meeting_name,
                "committee_name": committee,
                "place": site_name,
                "state_or_province": self._get_state_by_site(site_name),
                "meeting_date": meeting_date_str,
                "meeting_time": meeting_time_str,
                "meeting_id": meeting_id,
                "scraped_by": "civic-scraper", # As per civic-scraper standard
                "content_type": "application/octet-stream", # Default, can be overridden
                "agenda_url": self._make_absolute_url(item.get('agenda_url')),
                "video_url": self._make_absolute_url(item.get('video_url')),
                "asset_type": "Agenda", # Default, can be overridden
                "minutes_url": self._make_absolute_url(item.get('minutes_url')),
                "agenda_packet_url": self._make_absolute_url(item.get('packet_url')) # 'packet_url' from item
            }
            standardized_meetings.append(standard_item)
        return standardized_meetings

    def _save_to_json(self, data: list[dict], site_name: str, panel_name: str | None = None) -> None:
        """
        Saves extracted data to a JSON file.
        """
        if not data:
            logger.info(f"No data to save for {site_name} {panel_name if panel_name else ''}")
            return

        output_dir = "scraped_data"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # Sanitize panel_name for filename
        safe_panel_name = re.sub(r'[^\w\-_\.]', '_', panel_name.lower().replace(' ', '-')) if panel_name else ""
        filename_panel = f"_{safe_panel_name}" if safe_panel_name else ""
        filename = os.path.join(output_dir, f"{site_name}{filename_panel}_meetings.json")
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Successfully saved data to {filename}")
        except IOError as e:
            logger.error(f"Error saving data to JSON file {filename}: {e}")

    @abstractmethod
    def _extract_meeting_details_internal(self, soup: BeautifulSoup, panel_name: str | None) -> list[dict]:
        """
        Abstract method to be implemented by subclasses for specific HTML structures.
        Should parse the BeautifulSoup object and return a list of dictionaries,
        each containing raw meeting details like:
        {'name': str, 'date': str, 'time': str, 'agenda_url': str, 'meeting_id_source': str ...}
        'meeting_id_source' is used for creating a more unique internal ID.
        """
        pass

    def extract_and_process_meetings(self, html_content: str, url: str, panel_name: str | None = None) -> list[dict] | None:
        """
        Orchestrates the extraction and processing for this scraper type.
        Returns standardized data if successful, None otherwise.
        """
        self.base_url = url # Set base_url for _make_absolute_url
        soup = BeautifulSoup(html_content, 'html.parser')
        
        try:
            logger.info(f"Attempting extraction with {self.__class__.__name__} for panel: {panel_name if panel_name else 'N/A'}")
            raw_meetings = self._extract_meeting_details_internal(soup, panel_name)
            
            if not raw_meetings: # Handles None or empty list
                logger.info(f"{self.__class__.__name__} found no meeting data or failed pre-checks for panel: {panel_name if panel_name else 'N/A'}.")
                return None # Explicitly return None if no raw meetings
            
            logger.info(f"{self.__class__.__name__} extracted {len(raw_meetings)} raw meeting items.")
            
            standardized_data = self._transform_to_standard_format(raw_meetings, url, panel_name)
            
            if standardized_data:
                logger.info(f"{self.__class__.__name__} successfully processed data into {len(standardized_data)} items.")
                return standardized_data
            else:
                logger.info(f"{self.__class__.__name__} processed data but result is empty after standardization.")
                return None # Return None if standardization results in empty
        except Exception as e:
            logger.error(f"Error during extraction with {self.__class__.__name__}: {e}", exc_info=True)
            return None

    def requires_panel_name(self) -> bool:
        """
        Indicates if a scraper type strictly requires a panel name for parsing.
        Subclasses can override this if they behave differently.
        Type 3, for example, might not strictly need it for parsing but uses it for metadata.
        """
        # Default to True for scrapers that usually filter by a panel on the page.
        # GranicusType3Scraper will override this.
        return True

