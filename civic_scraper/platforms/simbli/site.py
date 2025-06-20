import time
import re
from datetime import datetime

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

from civic_scraper import base
from civic_scraper.base.asset import Asset, AssetCollection
from civic_scraper.base.cache import Cache


class SimbliSite(base.Site):
    """
    Scraper for Simbli eBoardSolutions sites.
    """

    def __init__(self, url, place=None, state_or_province=None, cache=Cache()):
        """
        Initialize SimbliSite.

        Args:
            url (str): The base URL for the Simbli portal.
            place (str): Name of place associated with the asset.
            state_or_province (str):  Two-letter abbreviation for state or province.
            cache (Cache): Optional cache object.
        """
        self.url = url
        self.cache = cache
        # Simbli URLs don't typically encode place/state in the domain
        # so they may need to be provided.
        self.place = place
        self.state_or_province = state_or_province

    def _get_page_source(self):
        """
        Fetches the HTML source of a page after it has been fully rendered
        by a headless browser (Selenium with Chrome).
        """
        html_content = None
        try:
            # Set up Chrome options for headless mode
            chrome_options = Options()
            # chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            # Set a realistic User-Agent
            user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            chrome_options.add_argument(f'user-agent={user_agent}')

            # Automatically download and manage the Chrome WebDriver
            service = ChromeService(ChromeDriverManager().install())
            
            # Initialize the WebDriver
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            driver.get(self.url)

            # Wait for the page and its JavaScript to load.
            time.sleep(20) 

            # Now get the page source after JavaScript has executed
            html_content = driver.page_source

        except Exception as e:
            print(f"An error occurred: {e}")
            
        finally:
            # Always close the driver to free up resources
            if 'driver' in locals() and driver:
                driver.quit()
                
        return html_content

    def _extract_site_details(self, soup):
        """
        Extracts place and state from the page source if not already set.
        """
        if self.place and self.state_or_province:
            return

        # Attempt 1: From the <title> tag
        title_tag = soup.find('title')
        if title_tag and title_tag.string:
            title_text = title_tag.string.strip()
            # Example: "Glynn County School System - Meeting Listing"
            parts = re.split(r'\s*-\s*', title_text)
            if parts and not self.place:
                entity_name = parts[0].strip()
                self.place = entity_name.lower().replace(' ', '_').replace('.', '')

    def _parse_meetings(self, soup):
        """
        Parses the HTML content of a Simbli meetings page to extract meeting assets.
        """
        meetings = AssetCollection()
        table = soup.find('table', id='ContentPlaceHolder1_MeetingGrid')
        if not table:
            return meetings

        base_url = "https://simbli.eboardsolutions.com/SB_Meetings/"
        rows = table.find('tbody').find_all('tr')

        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 4:
                continue

            # Extract date and time
            date_time_str = cells[0].find('span').get('title', '').strip()
            dt_obj = None
            if date_time_str:
                try:
                    dt_obj = datetime.strptime(date_time_str, '%m/%d/%Y - %I:%M %p')
                except ValueError:
                    pass

            # Extract meeting type
            meeting_type = cells[3].find('span').get('title', '').strip()

            # Extract agenda info
            agenda_link = cells[1].find('a')
            agenda_url = None
            meeting_id_part = None
            asset_name = None
            if agenda_link:
                asset_name = agenda_link.text.strip()
                agenda_onclick = agenda_link.get('onclick', '')
                
                if 'ViewMeeting' in agenda_onclick:
                    params_match = re.search(r"ViewMeeting\s*\((.*)\)", agenda_onclick)
                    if params_match:
                        params = params_match.group(1).split(',')
                        if len(params) >= 2:
                            s_param = params[0].strip().strip(' "')
                            meeting_id_part = params[1].strip().strip(' "') # MID
                            agenda_url = f"{base_url}ViewMeeting.aspx?S={s_param}&MID={meeting_id_part}"

            # Extract minutes info
            minutes_link = cells[2].find('a')
            minutes_url = None
            if minutes_link:
                minutes_onclick = minutes_link.get('onclick', '')
                if 'ViewMinutes' in minutes_onclick:
                    params_match = re.search(r"ViewMinutes\s*\((.*)\)", minutes_onclick)
                    if params_match:
                        params = params_match.group(1).split(',')
                        if len(params) >= 6:
                            s_param = params[0].strip().strip(' "')
                            # If we didn't get meeting_id from agenda, get it from here
                            if not meeting_id_part:
                                meeting_id_part = params[1].strip().strip(' "')
                            t_param = params[5].strip().strip(' "')
                            minutes_url = f"{base_url}ViewMeeting.aspx?S={s_param}&MID={meeting_id_part}&T={t_param}"

            place_name = self.place.replace('-', ' ').title() if self.place else None
            meeting_id = f"simbli-{self.place}-{meeting_id_part}" if self.place and meeting_id_part else None

            if agenda_url:
                asset = Asset(
                    url=agenda_url,
                    asset_name=asset_name,
                    committee_name=meeting_type,
                    place=self.place,
                    place_name=place_name,
                    state_or_province=self.state_or_province,
                    asset_type="agenda",
                    meeting_date=dt_obj,
                    meeting_time=dt_obj.time() if dt_obj else None,
                    meeting_id=meeting_id,
                    scraped_by="civic-scraper",
                )
                meetings.append(asset)

            if minutes_url:
                minutes_asset_name = f"Minutes for {meeting_type} on {dt_obj.date()}" if meeting_type and dt_obj else "Minutes"
                asset = Asset(
                    url=minutes_url,
                    asset_name=minutes_asset_name,
                    committee_name=meeting_type,
                    place=self.place,
                    place_name=place_name,
                    state_or_province=self.state_or_province,
                    asset_type="minutes",
                    meeting_date=dt_obj,
                    meeting_time=dt_obj.time() if dt_obj else None,
                    meeting_id=meeting_id,
                    scraped_by="civic-scraper",
                )
                meetings.append(asset)

        return meetings

    def scrape(self, download=False, start_date=None, end_date=None):
        """
        Scrape meetings and their assets from the Simbli site.
        
        Note: start_date and end_date are not yet implemented for Simbli
              as the interface doesn't easily support date-based filtering
              without more complex UI interaction.
        """
        html_content = self._get_page_source()
        if not html_content:
            return AssetCollection()
        
        soup = BeautifulSoup(html_content, 'html.parser')
        self._extract_site_details(soup)
        
        assets = self._parse_meetings(soup)
        
        return assets
