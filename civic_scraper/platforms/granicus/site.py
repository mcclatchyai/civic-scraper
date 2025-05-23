"""
Granicus Platform Scraper - Site Module

This module provides a unified interface for scraping Granicus-based civic meeting platforms.
It automatically detects and uses the appropriate scraper type (Type1-Type4) for different
Granicus site layouts.

=== QUICK START ===

1. Using the Site class (recommended for integration):
   ```python
   from civic_scraper.platforms.granicus.site import Site
   
   # Initialize site
   site = Site("https://cityofbradenton.granicus.com/ViewPublisher.php?view_id=1", 
               panel_name="City Council")
   
   # Get meetings data
   meetings = site.get_meetings()
   ```

2. Using scrape_granicus_platform() directly:
   ```python
   from civic_scraper.platforms.granicus.site import scrape_granicus_platform
   
   # Scrape and save to JSON automatically
   scrape_granicus_platform(
       url="https://marysvilleca.granicus.com/ViewPublisher.php?view_id=1",
       panel_name="City Council"
   )
   ```

=== KEY FEATURES ===

- Auto-detection of Granicus site types (Type1, Type2, Type3, Type4)
- Automatic fallback between scraper types until one succeeds
- Standardized output format across all site types
- Built-in JSON export with organized filenames

=== PARAMETERS ===

- url (str): Granicus ViewPublisher.php URL with view_id parameter
- panel_name (str, optional): Committee/panel name for targeted scraping
  * Required for some scraper types
  * Used in output filename if provided
  * Defaults to "Unknown" for Type3 scrapers when not provided

=== OUTPUT ===

Scraped data is saved as JSON files in ./scraped_data/ with format:
{site_name}_{panel_name}_meetings.json

"""

import logging
import os
import sys
from civic_scraper.base.site import Site as BaseSite

try:
    from .type1 import GranicusType1Scraper
    from .type2 import GranicusType2Scraper
    from .type3 import GranicusType3Scraper
    from .type4 import GranicusType4Scraper
 
except ImportError:
    from type1 import GranicusType1Scraper
    from type2 import GranicusType2Scraper
    from type3 import GranicusType3Scraper
    from type4 import GranicusType4Scraper

# Define the Site class for Granicus
class Site(BaseSite):
    """
    Site class for Granicus platforms.
    This class is a wrapper around the scrape_granicus_platform function.
    """
    
    def __init__(self, url, panel_name=None):
        """
        Initialize the Granicus site.
        
        Args:
            url (str): The URL of the site
            panel_name (str, optional): The name of the panel/committee to scrape
        """
        super().__init__(url)
        self.panel_name = panel_name
        
    def get_meetings(self):
        """
        Get meetings from the Granicus site using the appropriate scraper.
        
        Returns:
            list: A list of meetings in standardized format
        """
        return scrape_granicus_platform(self.url, self.panel_name)


# Configure logging for the application
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout) # Ensure logs go to stdout
    ]
)
logger = logging.getLogger(__name__)


def scrape_granicus_platform(url: str, panel_name: str | None = None):
    """
    Tries to scrape a Granicus URL using different scraper types.
    Saves the data from the first successful scraper.
    """
    logger.info(f"Starting scrape for URL: {url} (Panel: {panel_name if panel_name else 'N/A'})")
    
    # Instantiate all scraper types
    scraper_instances = [
        GranicusType1Scraper(),
        GranicusType2Scraper(),
        GranicusType4Scraper(), # Type 4 is often list-based, try before Type 3 if it's more specific
        GranicusType3Scraper(), # Type 3 is often more general / table-based without strict paneling
    ]

    if not scraper_instances: 
        logger.error("No scraper types have been defined. Aborting.")
        return

    temp_fetcher = scraper_instances[0] 
    html_content = temp_fetcher._fetch_html(url) 

    if not html_content:
        logger.error(f"Failed to fetch HTML content from {url}. Aborting.")
        return

    success = False
    for scraper in scraper_instances:
        # Check if the scraper type requires a panel name for its primary parsing logic
        if scraper.requires_panel_name() and not panel_name:
            logger.info(f"{scraper.__class__.__name__} requires a panel name for its primary parsing logic, but none was provided. Skipping this scraper for this URL/panel combination.")
            continue
            
        standardized_data = scraper.extract_and_process_meetings(html_content, url, panel_name)
        
        if standardized_data:

            site_name_for_saving = scraper._extract_site_name(url) 

            output_filename_panel_segment = panel_name
            if isinstance(scraper, GranicusType3Scraper) and not panel_name:
                 output_filename_panel_segment = None # Type 3 doesn't use panel for filename if not given for parsing

            scraper._save_to_json(standardized_data, site_name_for_saving, output_filename_panel_segment)
            logger.info(f"Successfully scraped and saved data using {scraper.__class__.__name__}.")
            success = True
            break 
        else:
            # extract_and_process_meetings returns None if it fails or finds no data that passes its checks.
            logger.info(f"{scraper.__class__.__name__} did not yield data or failed its internal checks for URL: {url} (Panel: {panel_name if panel_name else 'N/A'}). Trying next scraper if available.")

    if not success:
        logger.warning(f"No scraper was successful for URL: {url} (Panel: {panel_name if panel_name else 'N/A'})")

if __name__ == '__main__':


    # Test cases based on provided examples
    test_urls = [
        {
            "url": "https://cityofbradenton.granicus.com/ViewPublisher.php?view_id=1",  
            "panel": "City Council",  
            "comment": "Type 1: Bradenton City Council"
        },
        {
            "url": "https://marysvilleca.granicus.com/ViewPublisher.php?view_id=1",
            "panel": "City Council",  
            "comment": "Type 2: Marysville City Council"
        },
        {
            "url": "https://sacramento.granicus.com/ViewPublisher.php?view_id=22",  
            "panel": "City Council",
            "comment": "Type 3: Sacramento (e.g. City Council)"
        },
        {  
            "url": "https://rocklin-ca.granicus.com/ViewPublisher.php?view_id=1",  
            "panel": "Civil Service Commission",
            "comment": "Type 3: Rocklin Civil Service Commission"
        },
        {
            "url": "https://coralsprings.granicus.com/ViewPublisher.php?view_id=3",
            "panel": "Coral Springs City Commission",  
            "comment": "Type 4: Coral Springs City Commission"
        }
    ]

    for test_case in test_urls:
        logger.info(f"\n--- Running test for: {test_case['comment']} ---")
        scrape_granicus_platform(test_case["url"], test_case.get("panel"))
        logger.info("---------------------------------------------------\n")
