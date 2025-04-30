import logging
import re
from datetime import datetime, time
from urllib.parse import urlparse, parse_qs, urljoin
import feedparser
import requests
from bs4 import BeautifulSoup  # Import BeautifulSoup

from civic_scraper.base.asset import Asset, AssetCollection
import civic_scraper.base.constants as Constants  # Import module as Constants
from civic_scraper.base.site import Site as BaseSite  # Import Site and alias it as BaseSite
from civic_scraper.utils import (
    asset_generated_id,
    parse_datetime_formats,
    standardize_committee_name,
)

logger = logging.getLogger(__name__)


class Site(BaseSite):
    """
    Handles Granicus site scraping, supporting both RSS feeds and direct HTML pages.
    """

    def __init__(
        self,
        url,
        *,
        place=None,
        state_or_province=None,
        timezone="America/New_York",
        **kwargs,
    ):
        super().__init__(url, place=place, state_or_province=state_or_province, timezone=timezone, **kwargs)
        # Attempt to extract place from hostname if not provided
        if not self.place:
            try:
                hostname_parts = urlparse(url).hostname.split('.')
                if len(hostname_parts) > 1 and hostname_parts[1] == 'granicus':
                    self.place = hostname_parts[0]
                    logger.info(f"Extracted place '{self.place}' from URL hostname.")
            except Exception as e:
                logger.warning(f"Could not automatically extract place from URL '{url}': {e}")
        # State/Province is harder to guess, defaults to None if not provided

    def scrape(self, **kwargs):
        """
        Scrapes meeting assets from the Granicus site.
        Detects whether the URL is an RSS feed or an HTML page.
        """
        parsed_url = urlparse(self.url)
        if "ViewPublisherRSS.php" in parsed_url.path:
            logger.info(f"Detected RSS feed URL: {self.url}")
            return self._scrape_rss(**kwargs)
        elif "ViewPublisher.php" in parsed_url.path:
            logger.info(f"Detected HTML page URL: {self.url}")
            return self._scrape_html(**kwargs)
        else:
            logger.warning(
                f"URL type not recognized for Granicus scraper: {self.url}. "
                "Expected 'ViewPublisherRSS.php' or 'ViewPublisher.php' in path."
            )
            return AssetCollection([])

    def _scrape_rss(self, **kwargs):
        """Scrapes meeting assets from a Granicus RSS feed."""
        try:
            feed = feedparser.parse(self.url)
        except Exception as e:
            logger.error(f"Error fetching or parsing RSS feed {self.url}: {e}")
            return AssetCollection([])

        if feed.bozo:
            logger.warning(
                f"Warning: feedparser encountered issues parsing {self.url}. "
                f"Reason: {feed.bozo_exception}"
            )
            # Continue processing even if there are minor issues

        assets = []
        for entry in feed.entries:
            try:
                asset = self._create_asset_from_rss_entry(entry)
                if asset:
                    assets.append(asset)
            except Exception as e:
                logger.error(f"Error processing RSS entry '{entry.get('title', 'N/A')}': {e}", exc_info=True)

        logger.info(f"Finished RSS loop. Total assets created: {len(assets)}")
        return AssetCollection(assets)

    
    def _scrape_html(self, **kwargs):
        """Scrapes meeting assets from a Granicus HTML page (like Coral Springs)."""
        try:
            response = requests.get(self.url, timeout=Constants.REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching HTML page {self.url}: {e}")
            return AssetCollection([])

        soup = BeautifulSoup(response.content, 'html.parser')
        assets = []

        # Find list items that represent meetings.
        # Look for <li> elements containing a <div data-label="Meeting:">
        # This seems more robust than relying on specific IDs like #panel-content...
        meeting_list_items = soup.select('li:has(> div.table-cell[data-label="Meeting:"])')

        if not meeting_list_items:
            logger.warning(f"No meeting list items found on HTML page using selector 'li:has(> div.table-cell[data-label=\"Meeting:\"])': {self.url}")
            # Fallback: Try finding divs with class 'archive-item' which might wrap the li or be the li itself
            meeting_list_items = soup.select('.archive-item')
            if not meeting_list_items:
                 logger.warning(f"No meeting list items found using fallback selector '.archive-item' either: {self.url}")
                 return AssetCollection([])
            else:
                 logger.info(f"Found {len(meeting_list_items)} potential meeting items using fallback selector '.archive-item'.")


        logger.info(f"Found {len(meeting_list_items)} potential meeting list items.")

        for item in meeting_list_items:
            try:
                # Extract data directly from the list item structure
                asset = self._create_asset_from_html_li(item)
                if asset:
                    assets.append(asset)
            except Exception as e:
                logger.error(f"Error processing HTML meeting item: {e}", exc_info=True)


        logger.info(f"Finished HTML processing. Total assets created: {len(assets)}")
        return AssetCollection(assets)

    def _create_asset_from_html_li(self, meeting_li_tag):
        """Creates an Asset object from a meeting list item (<li> tag) found in HTML."""
        logger.debug(f"Processing HTML list item tag:\n{meeting_li_tag.prettify()}") # Log the tag being processed

        cells = meeting_li_tag.find_all('div', class_='table-cell')
        data_map = {}
        for cell in cells:
            label = cell.get('data-label')
            if label:
                # Remove trailing ':' from label if present
                clean_label = label.replace(':', '').strip()
                data_map[clean_label] = cell

        logger.debug(f"Constructed data_map keys: {list(data_map.keys())}") # Log the keys found in data_map

        meeting_event_cell = data_map.get("Meeting")
        # Try both "Date/Time" and "Date" as keys for the datetime cell
        datetime_cell = data_map.get("Date/Time") or data_map.get("Date")
        agenda_cell = data_map.get("Agenda") # Check for 'Agenda' first
        if not agenda_cell:
            agenda_cell = data_map.get("Public Notice/Agenda") # Fallback label
        packet_cell = data_map.get("Agenda Packet")

        if not meeting_event_cell or not datetime_cell:
            # Log the specific missing keys for clarity
            missing_keys = []
            if not meeting_event_cell:
                missing_keys.append("Meeting")
            if not datetime_cell:
                # Indicate that we checked for both date keys
                missing_keys.append("Date/Time or Date")
            logger.warning(f"HTML list item missing required cell(s): {', '.join(missing_keys)}. Data map keys found: {list(data_map.keys())}. Skipping.")
            return None

        asset_name = meeting_event_cell.get_text(strip=True)
        datetime_str = datetime_cell.get_text(strip=True) # e.g., "Apr 23, 2025"

        # Clean up extra spaces in date string
        datetime_str = re.sub(r'\s+', ' ', datetime_str).strip()

        meeting_datetime = None
        meeting_time = None # Initialize meeting_time
        try:
            # Add date-only formats
            meeting_datetime = parse_datetime_formats(
                datetime_str,
                [
                    "%B %d, %Y - %I:%M %p", # Full datetime
                    "%b %d, %Y - %I:%M %p", # Abbreviated month datetime
                    "%B %d, %Y",          # Date only
                    "%b %d, %Y"           # Abbreviated month date only
                ],
                self.timezone
            )
            # Check if only date was parsed (time is midnight)
            if meeting_datetime and meeting_datetime.time() == time(0, 0):
                meeting_time = None # Set time to None if only date was present
            elif meeting_datetime:
                meeting_time = meeting_datetime.time()

        except ValueError as e:
            logger.error(f"Could not parse datetime string '{datetime_str}' from HTML for meeting '{asset_name}': {e}")
            return None # Cannot proceed without a valid date/time

        # Find the primary link (Agenda or Packet)
        primary_link = None
        asset_type = "Unknown"
        content_type = "application/octet-stream"

        agenda_link_tag = agenda_cell.find('a') if agenda_cell else None
        packet_link_tag = packet_cell.find('a') if packet_cell else None

        # Prefer Agenda Packet if available, then Agenda
        if packet_link_tag and packet_link_tag.get('href'):
            primary_link = packet_link_tag['href']
            asset_type = "Agenda Packet"
            content_type = "application/pdf" # Assume PDF
            logger.debug(f"Found Agenda Packet link for '{asset_name}'")
        elif agenda_link_tag and agenda_link_tag.get('href'):
            primary_link = agenda_link_tag['href']
            asset_type = "Agenda"
            content_type = "application/pdf" # Assume PDF
            logger.debug(f"Found Agenda link for '{asset_name}'")
        else:
             # Check for other potential links like Minutes or Video if no Agenda/Packet
             minutes_cell = data_map.get("Minutes")
             video_cell = data_map.get("Video") # Or 'Media' depending on site
             minutes_link_tag = minutes_cell.find('a') if minutes_cell else None
             video_link_tag = video_cell.find('a') if video_cell else None

             if minutes_link_tag and minutes_link_tag.get('href'):
                 primary_link = minutes_link_tag['href']
                 asset_type = "Minutes"
                 content_type = "application/pdf" # Assume PDF
                 logger.debug(f"Found Minutes link for '{asset_name}'")
             elif video_link_tag and video_link_tag.get('href'):
                 primary_link = video_link_tag['href']
                 asset_type = "Video"
                 # Try to infer video type, default to generic video
                 content_type = "video/mp4" # A common default
                 if 'granicus.com/MediaPlayer.php' in primary_link:
                     content_type = "text/html" # Link to player page
                 logger.debug(f"Found Video link for '{asset_name}'")


        if not primary_link:
            logger.warning(f"No suitable primary link (Agenda, Packet, Minutes, Video) found for meeting '{asset_name}'. Skipping.")
            return None

        # Ensure the link is absolute
        meeting_url = urljoin(self.url, primary_link) # Use urljoin from urllib.parse

        # Extract meeting ID if possible (might need adjustment based on link structure)
        meeting_id = self._extract_meeting_id(meeting_url)
        if not meeting_id:
             # Fallback: generate ID from key details if URL doesn't have one
             id_input = f"{self.place}-{asset_name}-{meeting_datetime.isoformat()}"
             meeting_id = asset_generated_id(id_input)


        asset_args = {
            "url": meeting_url,
            "asset_name": asset_name,
            "committee_name": standardize_committee_name(asset_name), # Use full name for now, might need refinement
            "place": self.place,
            "state_or_province": self.state_or_province,
            "asset_type": asset_type,
            "meeting_date": meeting_datetime.date() if meeting_datetime else None,
            "meeting_time": meeting_time, # Use the determined meeting_time
            "meeting_id": meeting_id,
            "scraped_by": Constants.SCRAPED_BY,
            "content_type": content_type,
            "content_length": None, # Cannot easily get length from HTML link
        }
        logger.debug(f"HTML Asset args: {asset_args}")
        return Asset(**asset_args)


    def _extract_meeting_id(self, url):
        """Extracts a potential meeting ID from Granicus URLs."""
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        # Common Granicus ID parameters
        id_keys = ['clip_id', 'meta_id', 'event_id', 'id', 'meeting_id']
        for key in id_keys:
            if key in query_params:
                # Take the first value if multiple are present
                return query_params[key][0]
        # Fallback: Check path segments for potential IDs (e.g., /AgendaViewer.php?view_id=3&event_id=1234)
        # This part might need more specific patterns if IDs appear elsewhere
        logger.debug(f"No standard ID key found in query params for URL: {url}")
        return None


    def _create_asset_from_rss_entry(self, entry):
        """Creates an Asset object from a feedparser entry (RSS)."""
        logger.debug(f"Processing RSS entry: {entry.title}")

        asset_name = entry.title.strip()
        meeting_url = entry.link

        # Attempt to parse date/time from title first, then fallback to published date
        committee_name = asset_name
        asset_type = "Unknown"
        meeting_datetime_str = None
        meeting_datetime = None

        # Try splitting title like "Committee Name - Type - Date Time"
        title_parts = [p.strip() for p in asset_name.split(" - ")]
        if len(title_parts) >= 3:
            committee_name = title_parts[0]
            asset_type = title_parts[1]
            meeting_datetime_str = title_parts[-1] # Assume last part is datetime
            logger.debug(f"Split successful: committee='{committee_name}', type='{asset_type}', datetime='{meeting_datetime_str}'")
            try:
                # Granicus RSS titles often lack time, add a default if needed or rely on pubDate
                # Common formats: '%b %d, %Y' or '%B %d, %Y'
                meeting_datetime = parse_datetime_formats(
                    meeting_datetime_str,
                    ["%b %d, %Y", "%B %d, %Y"], # Add more formats if needed
                    self.timezone
                )
                if meeting_datetime:
                     # Use pubDate's time if title only has date
                     if meeting_datetime.time() == datetime.min.time() and hasattr(entry, 'published_parsed'):
                         pub_dt = datetime(*entry.published_parsed[:6])
                         meeting_datetime = meeting_datetime.replace(hour=pub_dt.hour, minute=pub_dt.minute, second=pub_dt.second)

            except ValueError as e:
                logger.debug(f"Error parsing str_datetime '{meeting_datetime_str}' from title: {e}. Trying pubDate.")
                meeting_datetime = None # Fallback below
        else:
            logger.debug(f"Error splitting asset_name '{asset_name}': Expected at least 3 parts separated by ' - ', got {len(title_parts)}. Attempting fallback.")
            # Use the full title as committee name if split fails

        # Fallback to published date if title parsing fails or yields no date
        if not meeting_datetime and hasattr(entry, 'published_parsed'):
            try:
                # published_parsed is a time.struct_time in UTC
                meeting_datetime = datetime(*entry.published_parsed[:6])
                logger.debug(f"Using parsed pubDate: {meeting_datetime}")
            except Exception as e:
                logger.error(f"Could not parse published_parsed time struct {entry.published_parsed}: {e}")
                meeting_datetime = datetime.now() # Final fallback

        meeting_id = self._extract_meeting_id(meeting_url)

        # Determine content type (often video for RSS links)
        content_type = entry.get("type", "application/octet-stream") # Default if not specified
        if "video" in content_type or "wmv" in content_type: # Common Granicus video types
             content_type = "video/x-ms-wmv" # Standardize common video type
        elif "pdf" in entry.get("summary", "").lower() or "pdf" in meeting_url.lower():
             content_type = "application/pdf"
        elif "agenda" in asset_type.lower() or "agenda" in asset_name.lower():
             content_type = "application/pdf" # Assume PDF if 'agenda' mentioned
        elif "minutes" in asset_type.lower() or "minutes" in asset_name.lower():
             content_type = "application/pdf" # Assume PDF if 'minutes' mentioned


        asset_args = {
            "url": meeting_url,
            "asset_name": asset_name,
            "committee_name": standardize_committee_name(committee_name),
            "place": self.place,
            "state_or_province": self.state_or_province,
            "asset_type": asset_type,
            "meeting_date": meeting_datetime.date() if meeting_datetime else None,
            "meeting_time": meeting_datetime.time() if meeting_datetime else None,
            "meeting_id": meeting_id,
            "scraped_by": Constants.SCRAPED_BY,
            "content_type": content_type,
            "content_length": int(entry.get("length", 0)), # Often 0 or missing in RSS
        }
        logger.debug(f"Asset args: {asset_args}")
        return Asset(**asset_args)
