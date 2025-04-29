from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import logging
import warnings

import feedparser
from requests import Session

import civic_scraper
from civic_scraper import base
from civic_scraper.base.asset import Asset, AssetCollection
from civic_scraper.base.cache import Cache

logger = logging.getLogger(__name__)

class Site(base.Site):
    """Granicus platform implementation."""
    
    def __init__(
        self,
        url,
        place=None,
        state_or_province=None,
        cache=None,
        parser_kls=None,
        committee_id=None,
        timezone=None,
        **kwargs
    ):
        """Initialize Granicus site.
        
        Args:
            url (str): RSS feed URL for the Granicus site
            place (str, optional): Name of the place/municipality
            state_or_province (str, optional): State or province
            cache (Cache, optional): Cache instance
            parser_kls (class, optional): Not used for Granicus
            committee_id (str, optional): Not used for Granicus
            timezone (str, optional): Timezone for dates
        """
        # Handle deprecated parameters for backward compatibility
        if 'rss_url' in kwargs:
            warnings.warn(
                "The rss_url parameter is deprecated, use url instead",
                DeprecationWarning,
                stacklevel=2
            )
            url = kwargs.pop('rss_url')
        
        # Initialize base class with standardized parameters
        super().__init__(
            url=url,
            place=place,
            state_or_province=state_or_province,
            cache=cache,
            parser_kls=parser_kls,
            committee_id=committee_id,
            timezone=timezone
        )
        
    def _init_platform_specific(self):
        """Initialize Granicus-specific attributes."""
        self.granicus_instance = urlparse(self.url).netloc.split(".")[0]
        self.session = Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; CrOS x86_64 12871.102.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.141 Safari/537.36"
        })

    def scrape(
        self,
        start_date=None,
        end_date=None,
        download=False,
        cache=False,
        file_size=None,
        asset_list=None
    ):
        """Scrape Granicus site for meeting records.
        
        Args:
            start_date (str, optional): YYYY-MM-DD start date - not used in Granicus
            end_date (str, optional): YYYY-MM-DD end date - not used in Granicus
            download (bool, optional): Download file assets (default: False) 
            cache (bool, optional): Cache source HTML (default: False) - not used in Granicus
            file_size (float, optional): Max size in MB to download (default: None)
            asset_list (list, optional): List of asset types to scrape (default: None)
            
        Returns:
            AssetCollection: Collection of scraped assets
        """
        if start_date or end_date:
            logger.warning("Date filtering is not supported for Granicus platform")
            
        if cache:
            logger.warning("Caching source HTML is not supported for Granicus platform")
        
        response = self.session.get(self.url)
        parsed_rss = feedparser.parse(response.text)
        
        # Cache the raw RSS if requested
        if cache:
            cache_path = f"{self.cache.artifacts_path}/granicus_{self.granicus_instance}_rss.xml"
            self.cache.write(cache_path, response.text)
            logger.info(f"Cached RSS feed: {cache_path}")

        # Create assets from RSS entries
        assets = AssetCollection()
        for entry in parsed_rss["entries"]:
            assets.append(self._create_asset(entry))

        # Download assets if requested
        if download:
            self._download_assets(assets, file_size, asset_list)

        return assets

    def _create_asset(self, entry):
        """Create an asset from an RSS entry.
        
        Args:
            entry: RSS entry
            
        Returns:
            Asset: Created asset
        """
        asset_name = entry["title"]
        committee_name, asset_type, str_datetime = asset_name.split(" - ")
        meeting_datetime = datetime.strptime(str_datetime, "%b %d, %Y %I:%M %p")

        meeting_url = entry["link"]
        query_dict = parse_qs(urlparse(meeting_url).query)

        # entries for a single granicus instance might use different query params
        if "ID" in query_dict.keys():
            meeting_id = f"granicus_{self.granicus_instance}_{query_dict['ID'][0]}"
        else:
            meeting_id = f"granicus_{self.granicus_instance}_{query_dict['MeetingID'][0]}"

        asset_args = {
            "url": meeting_url,
            "asset_name": asset_name,
            "committee_name": committee_name,
            "place": self.place,
            "state_or_province": self.state_or_province,
            "asset_type": asset_type,
            "meeting_date": meeting_datetime.date(),
            "meeting_time": meeting_datetime.time(),
            "meeting_id": meeting_id,
            "scraped_by": f"civic-scraper_{civic_scraper.__version__}",
            "content_type": "text/html",
            "content_length": None,
        }
        return Asset(**asset_args)
