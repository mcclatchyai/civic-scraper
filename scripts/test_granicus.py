# to run all test: python scripts\test_granicus.py
# terminal command to test how platform handles one url: python scripts\test_granicus.py --type platform --url "https://sacramento.granicus.com/viewpublisher.php?view_id=22" --panel "City Council"
# terminal command to test a specific type: python scripts\test_granicus.py --type 3  --url "https://sacramento.granicus.com/viewpublisher.php?view_id=22" --panel "City Council"

import os
import sys
import logging
import argparse
import json
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import Granicus scrapers from the package
try:
    from civic_scraper.platforms.granicus.type1 import GranicusType1Scraper
    from civic_scraper.platforms.granicus.type2 import GranicusType2Scraper
    from civic_scraper.platforms.granicus.type3 import GranicusType3Scraper
    from civic_scraper.platforms.granicus.type4 import GranicusType4Scraper
    from civic_scraper.platforms.granicus.site import scrape_granicus_platform
    logger.info("Successfully imported Granicus scrapers")
except ImportError as e:
    logger.error(f"Failed to import Granicus scrapers: {str(e)}")
    logger.error(f"Current working directory: {os.getcwd()}")
    logger.error(f"Current sys.path: {sys.path}")
    logger.error("Make sure you're running from the project root or the paths are correct")
    sys.exit(1)

# Test URLs for each scraper type
TEST_URLS = {
    "type1": {
        "url": "https://cityofbradenton.granicus.com/ViewPublisher.php?view_id=1",
        "panel": "City Council"
    },
    "type2": {
        "url": "https://marysvilleca.granicus.com/ViewPublisher.php?view_id=1",
        "panel": "City Council"
    },
    "type3": {
        "url": "https://sacramento.granicus.com/viewpublisher.php?view_id=22",
        "panel": "City Council"
    },
    "type4": {
        "url": "https://coralsprings.granicus.com/ViewPublisher.php?view_id=3",
        "panel": "Coral Springs City Commission"
    }
}

def test_specific_scraper(scraper_type, url, panel_name):
    """
    Test a specific Granicus scraper type with a given URL and panel name.
    
    Args:
        scraper_type: The scraper class to use
        url: The URL to scrape
        panel_name: The name of the panel/committee to scrape
    
    Returns:
        bool: True if successful, False otherwise
    """
    logger.info(f"Testing {scraper_type.__name__} with URL: {url} (Panel: {panel_name})")
    
    try:
        # Instantiate the scraper
        scraper = scraper_type()
        
        # Fetch HTML content
        logger.debug(f"Fetching HTML content from {url}")
        html_content = scraper._fetch_html(url)
        
        if not html_content:
            logger.error(f"Failed to fetch HTML content from {url}")
            return False
        
        logger.debug(f"Successfully fetched HTML content ({len(html_content)} bytes)")
        
        # Extract and process meetings
        logger.debug(f"Extracting meetings using {scraper_type.__name__}")
        meetings = scraper.extract_and_process_meetings(html_content, url, panel_name)
        
        if not meetings:
            logger.warning(f"No meetings found using {scraper_type.__name__} for {panel_name}")
            return False
        
        logger.info(f"Successfully extracted {len(meetings)} meetings using {scraper_type.__name__}")
        
        # Create output directory if it doesn't exist
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scraped_data")
        os.makedirs(output_dir, exist_ok=True)
        
        # Save to JSON file
        site_name = scraper._extract_site_name(url)
        safe_panel_name = panel_name.lower().replace(' ', '-') if panel_name else ""
        filename = os.path.join(output_dir, f"{site_name}_{safe_panel_name}_meetings.json")
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(meetings, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved meetings to {filename}")
        return True
    
    except Exception as e:
        logger.error(f"Error testing {scraper_type.__name__}: {str(e)}")
        logger.debug(traceback.format_exc())
        return False

def test_scrape_granicus_platform(url, panel_name):
    """
    Test the main scrape_granicus_platform function with a given URL and panel name.
    
    Args:
        url: The URL to scrape
        panel_name: The name of the panel/committee to scrape
    
    Returns:
        bool: True if successful, False otherwise
    """
    logger.info(f"Testing scrape_granicus_platform with URL: {url} (Panel: {panel_name})")
    
    try:
        # Call the main scraping function
        scrape_granicus_platform(url, panel_name)
        logger.info(f"Successfully tested scrape_granicus_platform for {url}")
        return True
    
    except Exception as e:
        logger.error(f"Error testing scrape_granicus_platform: {str(e)}")
        logger.debug(traceback.format_exc())
        return False

def run_all_tests():
    """Run all scraper tests with their specific URLs."""
    results = {}
    
    # Test Type 1 Scraper
    results["type1"] = test_specific_scraper(
        GranicusType1Scraper,
        TEST_URLS["type1"]["url"],
        TEST_URLS["type1"]["panel"]
    )
    
    # Test Type 2 Scraper
    results["type2"] = test_specific_scraper(
        GranicusType2Scraper,
        TEST_URLS["type2"]["url"],
        TEST_URLS["type2"]["panel"]
    )
    
    # Test Type 3 Scraper
    results["type3"] = test_specific_scraper(
        GranicusType3Scraper,
        TEST_URLS["type3"]["url"],
        TEST_URLS["type3"]["panel"]
    )
    
    # Test Type 4 Scraper
    results["type4"] = test_specific_scraper(
        GranicusType4Scraper,
        TEST_URLS["type4"]["url"],
        TEST_URLS["type4"]["panel"]
    )
    
    # Test the main scrape_granicus_platform function with each URL
    for scraper_type, test_data in TEST_URLS.items():
        results[f"platform_{scraper_type}"] = test_scrape_granicus_platform(
            test_data["url"],
            test_data["panel"]
        )
    
    # Print summary of results
    logger.info("Test Results Summary:")
    for test_name, result in results.items():
        status = "PASSED" if result else "FAILED"
        logger.info(f"  {test_name}: {status}")
    
    # Return True if all tests passed
    return all(results.values())

def run_specific_test(scraper_type, url, panel_name=None):
    """
    Run a test for a specific scraper type and URL.
    
    Args:
        scraper_type: The type of scraper to use (1, 2, 3, 4, or 'platform')
        url: The URL to scrape
        panel_name: The name of the panel/committee to scrape
    
    Returns:
        bool: True if successful, False otherwise
    """
    if scraper_type == "platform":
        return test_scrape_granicus_platform(url, panel_name)
    
    scraper_map = {
        "1": GranicusType1Scraper,
        "2": GranicusType2Scraper,
        "3": GranicusType3Scraper,
        "4": GranicusType4Scraper
    }
    
    if scraper_type not in scraper_map:
        logger.error(f"Invalid scraper type: {scraper_type}")
        return False
    
    return test_specific_scraper(scraper_map[scraper_type], url, panel_name)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Test Granicus scrapers")
    parser.add_argument(
        "--type", 
        choices=["1", "2", "3", "4", "platform", "all"],
        default="all",
        help="Scraper type to test (1-4, platform, or all)"
    )
    parser.add_argument(
        "--url", 
        help="URL to scrape (required if type is not 'all')"
    )
    parser.add_argument(
        "--panel", 
        help="Panel/committee name to scrape"
    )
    parser.add_argument(
        "--debug", 
        action="store_true",
        help="Enable debug mode with verbose logging"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.type != "all" and not args.url:
        parser.error("--url is required when --type is not 'all'")
    
    return args

if __name__ == "__main__":
    args = parse_arguments()
    
    # Set logging level based on debug flag
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug mode enabled")
    
    # Print system information
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Script location: {os.path.abspath(__file__)}")
    
    # Create directories for output if they don't exist
    os.makedirs("scraped_data", exist_ok=True)
    
    try:
        if args.type == "all":
            success = run_all_tests()
        else:
            success = run_specific_test(args.type, args.url, args.panel)
        
        # Exit with appropriate status code
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        if args.debug:
            logger.error(traceback.format_exc())
        sys.exit(1)

