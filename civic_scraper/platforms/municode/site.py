"""
This module provides functionality to scrape meeting information and assets from Municode Meetings and similar CivicPlus-style websites.

Supported features:
- Scraping meeting data (date, title, committee, etc.) and associated assets (agenda, packet, minutes, video, details) from both classic Municode and new CivicPlus-style meeting portals.
- Normalizing and formatting meeting and asset data for downstream use.
- Extensible support for additional domains and asset types.

Supported site patterns include (but are not limited to):
    - https://bluffton-sc.municodemeetings.com/
    - https://tumwater-wa.municodemeetings.com/
    - https://columbus-ga.municodemeetings.com/
    - https://hillsborough-nc.municodemeetings.com/
    - https://www.cityofannamaria.com/meetings
    - https://www.staridaho.org/meetings
    - https://www.baystlouis-ms.gov/meetings
    - https://www.cityoflivingston.org/meetings

Only sites in the supported patterns list are officially tested and supported for scraping with this code.
"""
import os
import sys
import datetime
import logging
import re
import json
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests
from dateutil import parser
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import civic_scraper  # noqa: E402
from civic_scraper import base  # noqa: E402
from civic_scraper.base.cache import Cache  # noqa: E402
from civic_scraper.base.asset import Asset, AssetCollection

logger = logging.getLogger(__name__)

HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/114.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Connection": "keep-alive",
        }


class MunicodeSite(base.Site):
    def __init__(self, url, place=None, state_or_province=None, cache=Cache()):
        self.url = url
        self.base_url = "https://" + urlparse(url).netloc
        self.place = place
        self.state_or_province = state_or_province
        self.cache = cache

        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (X11; CrOS x86_64 12871.102.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.141 Safari/537.36"
        )
        self.session.hooks = {
            "response": lambda r, *args, **kwargs: r.raise_for_status()
        }

    def get_site_raw_data(self):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(self.url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.error(f"Error fetching {self.url}: {e}")
            return None

    def get_particular_outer_html(self, html, class_name, uid):
        soup = BeautifulSoup(html.text if hasattr(html, "text") else html, "html.parser")
        elements = soup.find_all(class_name, class_=uid)

        if not elements:
            return None

        # Select the tag with the longest outer HTML
        largest = max(elements, key=lambda el: len(str(el)))
        return str(largest)

    def extract_meetings_from_html(self, html_content, base_url="https://www.cityofannamaria.com"):

        soup = BeautifulSoup(html_content, "html.parser")
        results = []

        for item in soup.select(".views-row"):
            date_time = item.select_one(".views-field-field-smart-date .field-content")
            title = item.select_one(".views-field-title .field-content")
            agenda_tag = item.select_one(".views-field-nothing-1 .field-content a")
            detail_tag = item.select_one(".views-field-view-node .field-content a")

            meeting_info = {
                "date_time": date_time.text.strip() if date_time else None,
                "title": title.text.strip() if title else None,
                "agenda_url": urljoin(base_url, agenda_tag["href"]) if agenda_tag else None,
                "details_url": urljoin(base_url, detail_tag["href"]) if detail_tag else None,
                "website_url": base_url,
            }

            results.append(meeting_info)

        return results

    def extract_meetings_from_table2(self, html_content, base_url="https://www.staridaho.org"):
        """
        Extract structured meeting data from a table-based HTML content.

        Args:
            html_content (str): HTML content with a table of meetings.
            base_url (str): To resolve relative links.

        Returns:
            List of dictionaries with meeting info.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        results = []

        for row in soup.select("tbody tr"):
            date_time_tag = row.select_one(".views-field-field-calendar-date .date-display-single")
            title_tag = row.select_one(".views-field-title")
            agenda_links = row.select(".views-field-field-agendas a")
            packet_links = row.select(".views-field-field-packets a")
            minutes_links = row.select(".views-field-field-minutes a")
            video_links = row.select(".views-field-field-video-link a")
            view_link_tag = row.select_one(".views-field-view-node a")

            meeting = {
                "date_time": date_time_tag.text.strip() if date_time_tag else None,
                "title": title_tag.text.strip() if title_tag else None,
                "agenda_urls": [a["href"] for a in agenda_links if a.has_attr("href")],
                "packet_urls": [a["href"] for a in packet_links if a.has_attr("href")],
                "minutes_urls": [a["href"] for a in minutes_links if a.has_attr("href")],
                "video_urls": [a["href"] for a in video_links if a.has_attr("href")],
                "details_url": urljoin(base_url, view_link_tag["href"]) if view_link_tag else None,
                "website_url": base_url,
            }

            results.append(meeting)

        return results

    def parse_meetings(self, html_content, base_url):
        if not html_content:
            raise ValueError("HTML content is empty or None")
        soup = BeautifulSoup(html_content, "html.parser")

        if soup.select(".views-row"):
            return self.extract_meetings_from_html(html_content, base_url)
        elif soup.select("table.views-table"):
            return self.extract_meetings_from_table2(html_content, base_url)
        else:
            raise ValueError("Unsupported HTML structure")

    def generate_meeting_id(self, scraper_type, subdomain, date=None):
        """meeting_id (str): Unique meeting ID. For example, cominbation of scraper type,
                subdomain and numeric ID or date. Ex: civicplus-nc-nashcounty-05052020-382""""#load clients.py"

        if date:
            return f"{scraper_type}-{subdomain}-{date}"
        else:
            raise ValueError("Either numeric_id or date must be provided to generate meeting ID")

    def append_assets(self, final_list, asset_type, urls, i_meeting, committee_name, place, place_name,
                      state_or_province, meeting_date, meeting_time, meeting_id, scraped_by, content_type, content_length):
        for url in urls:
            final_list.append({
                "url": url,
                "asset_name": i_meeting.get("title", f"Unknown {asset_type.title()}"),
                "committee_name": committee_name,
                "place": place,
                "place_name": place_name,
                "state_or_province": state_or_province,
                "asset_type": asset_type,
                "meeting_date": meeting_date,
                "meeting_time": meeting_time,
                "meeting_id": meeting_id,
                "scraped_by": scraped_by,
                "content_type": content_type,
                "content_length": content_length
            })

    def normalize_output_format(self, meetings_data):
        final_meet_list = []
        for i_meeting in meetings_data:
            meeting_date = i_meeting.get("date_time")
            if meeting_date:
                try:
                    i_meeting["meeting_date"] = parser.parse(meeting_date.replace('|', '').strip()).date()
                    i_meeting["meeting_time"] = parser.parse(meeting_date.replace('|', '').strip()).time()
                except ValueError:
                    i_meeting["meeting_date"] = None
                    i_meeting["meeting_time"] = None
            if meeting_date is None:
                logger.warning("Meeting date is None, skipping this meeting")
                continue
            meeting_date = i_meeting.get("meeting_date")
            # if meeting_date < datetime.datetime.today().date() or meeting_date is None:
            #     logger.warning(f"Skipping past meeting date: {meeting_date} or None issue")
            #     continue
            meeting_time = i_meeting.get("meeting_time")
            committee_name = i_meeting.get("title", "Unknown Committee")
            website_url = i_meeting.get("website_url", None)
            meeting_id = self.generate_meeting_id(scraper_type="civic-scraper",
                                                  subdomain=committee_name,
                                                  date=meeting_date)
            scraped_by = f"civic-scraper_{civic_scraper.__version__}"
            content_type = None
            content_length = None
            place = urlparse(website_url).netloc.lower().replace(".", "") if website_url else "unknown_place"

            place_name = urlparse(website_url).netloc.split(".")[0].replace("-", " ").title() if website_url else "Unknown Place"
            state_or_province = "us"  # Default to 'us' if not specified

            # Use the helper function for each asset type
            if i_meeting.get("agenda_urls"):
                self.append_assets(final_meet_list, "agenda", i_meeting.get("agenda_urls"), i_meeting, committee_name, place, place_name, state_or_province, meeting_date, meeting_time, meeting_id, scraped_by, content_type, content_length)
            if i_meeting.get("packet_urls"):
                self.append_assets(final_meet_list, "packet", i_meeting.get("packet_urls"), i_meeting, committee_name, place, place_name, state_or_province, meeting_date, meeting_time, meeting_id, scraped_by, content_type, content_length)
            if i_meeting.get("minutes_urls"):
                self.append_assets(final_meet_list, "minutes", i_meeting.get("minutes_urls"), i_meeting, committee_name, place, place_name, state_or_province, meeting_date, meeting_time, meeting_id, scraped_by, content_type, content_length)
            if i_meeting.get("video_urls"):
                self.append_assets(final_meet_list, "video", i_meeting.get("video_urls"), i_meeting, committee_name, place, place_name, state_or_province, meeting_date, meeting_time, meeting_id, scraped_by, content_type, content_length)
            if i_meeting.get("details_url"):
                self.append_assets(final_meet_list, "details", [i_meeting.get("details_url")], i_meeting, committee_name, place, place_name, state_or_province, meeting_date, meeting_time, meeting_id, scraped_by, content_type, content_length)
        return [Asset(**item) for item in final_meet_list]

    def fetch_meeting_data(self, url):
        """Fetch and parse meeting data from a given Municode Meetings URL."""
        logger.info(f"Fetching data from: {url}")

        response = self.get_site_raw_data()

        try:
            view_content = self.get_particular_outer_html(response, "div", "view-content")
            if not view_content:
                logger.warning(f"No content with class 'view-content' found at {url}")
                return []
            table_soup = BeautifulSoup(view_content, "html.parser")

            meeting_info = []
            for row in table_soup.find_all("tr"):
                temp = {}

                # Extract Date
                date_td = row.find("td", attrs={"data-th": "Date"})
                if date_td:
                    span = date_td.find("span", class_="date-display-single")
                    temp["date"] = span["content"] if span and span.has_attr("content") else date_td.get_text(strip=True)
                    if isinstance(temp["date"], str):
                        try:
                            temp["date"] = parser.parse(temp["date"]).date()
                        except ValueError:
                            logger.warning(f"Could not parse date: {temp['date']}")
                else:
                    logger.warning(f"No 'Date' column found in row: {row}")
                    continue
                # Extract Meeting Title
                meeting_td = row.find("td", attrs={"data-th": "Meeting"})
                # if temp.get("date") < datetime.datetime.today().date():
                #     logger.warning(f"Skipping past meeting date: {temp['date']}")
                #     continue
                if meeting_td:
                    temp["Meeting Title"] = meeting_td.get_text(strip=True)

                # Generate unique meeting_id
                print("Date:", temp.get("date", ""),
                      "sub-domain", urlparse(url).netloc.lower().replace(".", ""))
                temp["meeting_id"] = self.generate_meeting_id(scraper_type="civic-scraper",
                                                              subdomain=urlparse(url).netloc.lower().replace(".", ""),
                                                              date=temp.get("date", "") if temp.get("date") else None)

                # Agenda & Packet keys
                agenda_keys = ["Agenda", "Agendas"]
                packet_keys = ["Packet", "Packets", "Agenda Packets", "Agenda Packet"]

                # Agenda links
                temp["Agenda Links"] = []
                for key in agenda_keys:
                    td = row.find("td", attrs={"data-th": key})
                    if td:
                        temp["Agenda Links"] = [a["href"] for a in td.find_all("a", href=True)]
                        break

                # Packet links
                temp["Packet Links"] = []
                for key in packet_keys:
                    td = row.find("td", attrs={"data-th": key})
                    if td:
                        temp["Packet Links"] = [a["href"] for a in td.find_all("a", href=True)]
                        break
                # video links
                temp["video Links"] = []
                video_td = row.find("td", attrs={"data-th": "Video"})
                if video_td:
                    temp["video Links"] = [a["href"] for a in video_td.find_all("a", href=True)]
                temp["website_url"] = url
                if temp:
                    meeting_info.append(temp)

            return meeting_info

        except Exception as e:
            logger.error(f"Error parsing HTML for {url}: {e}")
            return []
        
    import requests
    from bs4 import BeautifulSoup

    def scrape_apex_meetings(self,url):
        """
        Scrape meeting data from Apex Town Council website.
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find the meeting table
            table = soup.find('table', class_='div-table mcm')
            
            if not table:
                print("Table not found in the HTML")
                # Try to find any table
                all_tables = soup.find_all('table')
                print(f"Found {len(all_tables)} tables total")
                soup = BeautifulSoup(response.text, 'html.parser')
        
                # Check for iframe that might contain the meeting data
                iframe = soup.find('iframe')
                if iframe and iframe.get('src'):
                    iframe_url = iframe['src']
                    if not iframe_url.startswith('http'):
                        # Handle relative URLs
                        from urllib.parse import urljoin
                        iframe_url = urljoin(url, iframe_url)
                    
                    print(f"Found iframe: {iframe_url}")
                    print("Fetching iframe content...")
                    
                    iframe_response = requests.get(iframe_url, headers=headers, timeout=30)
                    iframe_response.raise_for_status()
                    #iframe_soup = BeautifulSoup(iframe_response.text, 'html.parser')
                    return iframe_response.text
            
            
            else:
                return response.text
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching URL: {e}")
            return []

    
        
    def extract_meeting_data_for_lydia_apex(self,html_content: str, website_url: str):
        """
        Extract meeting data from municode.com meeting tables.
        Returns data in format compatible with normalize_output_format.
        
        Args:
            html_content: HTML string containing the meeting table
            website_url: The source URL where this data was scraped from
        
        Returns:
            List of meeting dictionaries with keys matching normalize_output_format expectations
        """
        html_content=self.scrape_apex_meetings(website_url)
        soup = BeautifulSoup(html_content, 'html.parser')
        meetings = []

        
        table = soup.find('table', class_='div-table mcm')
        if not table:
            return meetings
        
        tbody = table.find('tbody')
        if not tbody:
            rows = table.find_all('tr')
            rows = [row for row in rows if not row.find('th')]
            if not rows:
                 return meetings
        
        #rows = tbody.find_all('tr')
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 3:
                continue
            
            meeting_name = cols[0].text.strip()
            date_str = cols[1].text.strip()
            time_str = cols[2].text.strip()
            
            # Combine date and time for date_time field
            date_time_str = f"{date_str} {time_str}"
            
            meeting_data = {
                'title': meeting_name,  # Maps to committee_name
                'date_time': date_time_str,  # Will be parsed by normalize_output_format
                'website_url': website_url,
                'agenda_urls': [],
                'packet_urls': [],
                'minutes_urls': [],
                'video_urls': [],
                'details_url': None
            }
            
            # Extract document links based on column classes
            for col in cols[3:]:
                link = col.find('a')
                if not link or 'href' not in link.attrs:
                    continue
                
                url = link['href']
                col_classes = col.get('class', [])
                
                # Determine if it's PDF or HTML
                is_html = 'adahtml' in ' '.join(col_classes).lower()
                
                # Route to appropriate list based on document type
                if 'packet' in col_classes:
                    # This could be "Agenda Packet" (Apex) or "Packet" (Lynden)
                    meeting_data['packet_urls'].append(url)
                elif 'agenda' in col_classes:
                    # Separate "Agenda" (Lynden only)
                    meeting_data['agenda_urls'].append(url)
                elif 'minutes' in col_classes:
                    meeting_data['minutes_urls'].append(url)
            
            # For Apex structure where "Agenda Packet" should be treated as agenda
            # If packet_urls exist but agenda_urls is empty, copy packet to agenda
            if meeting_data['packet_urls'] and not meeting_data['agenda_urls']:
                meeting_data['agenda_urls'] = meeting_data['packet_urls'].copy()
            
            meetings.append(meeting_data)
        
        return meetings


    def build_asset_data(self, meeting_info, place=None, state_or_province=None):
        """
        Build asset data from parsed meeting info.

        Args:
            meeting_info (list): List of dicts from fetch_meeting_data.
            place (str): Place name.
            state_or_province (str): State or province.

        Returns:
            list: List of asset dicts.
        """
        assets = []
        for row in meeting_info:
            if "CANCELED" in row.get("Meeting Title", "").upper():
                logger.info(f"Skipping cancelled meeting: {row.get('Meeting Title')}")
                continue
            meeting_date = row.get("date")
            meeting_title = row.get("Meeting Title", "")
            meeting_id = row.get("meeting_id")

            # Remove 'meeting' at the end of the title for committee_name
            committee_name = re.sub(r"\s*meeting\s*$", "", meeting_title, flags=re.IGNORECASE)

            scraped_by = f"civic-scraper_{civic_scraper.__version__}"

            # adding meeting_info first
            assets.append({
                "meeting_id": meeting_id,
                "state_or_province": state_or_province,
                "place": place,
                "committee_name": committee_name,
                "asset_name": meeting_title,
                "meeting_date": meeting_date,
                "asset_type": "meeting_info",
                "scraped_by": scraped_by,
                "url": None,  # No URL for meeting info
            })
            # Agenda Links
            for url in row.get("Agenda Links", []):
                assets.append({
                    "meeting_id": meeting_id,
                    "state_or_province": state_or_province,
                    "place": place,
                    "committee_name": committee_name,
                    "asset_name": meeting_title,
                    "meeting_date": meeting_date,
                    "asset_type": "agenda",
                    "scraped_by": scraped_by,
                    "url": url,
                })

            # Packet Links
            for url in row.get("Packet Links", []):
                assets.append({
                    "meeting_id": meeting_id,
                    "state_or_province": state_or_province,
                    "place": place,
                    "committee_name": committee_name,
                    "asset_name": meeting_title,
                    "meeting_date": meeting_date,
                    "asset_type": "packet",
                    "scraped_by": scraped_by,
                    "url": url,
                })

            # Video Links
            for url in row.get("video Links", []):
                assets.append({
                    "meeting_id": meeting_id,
                    "state_or_province": state_or_province,
                    "place": place,
                    "committee_name": committee_name,
                    "asset_name": meeting_title,
                    "meeting_date": meeting_date,
                    "asset_type": "video",
                    "scraped_by": scraped_by,
                    "url": url,
                })
        return [Asset(**item) for item in assets]

    def scrape(self, start_date=None, end_date=None):
        url = self.url
        if is_new_pattern_url(url):
            # Use new logic
            response = self.get_site_raw_data()
            outer_html = self.get_particular_outer_html(response, "div", "view-content")
            if not outer_html:
                print("No 'view-content' found, skipping.")
                return None
            meeting_data = self.parse_meetings(outer_html, base_url=url)
            meeting_data = self.normalize_output_format(meeting_data)
            print(f"Found {len(meeting_data)} meetings (new style).")
            return meeting_data
        elif "lyndenwa.org" in url or "apexnc.org" in url or "meridiancity.org" in url or "staridaho.org" in url:
            meeting_data=self.extract_meeting_data_for_lydia_apex(self.get_site_raw_data().text,url)
            meeting_data=self.normalize_output_format(meeting_data)
            return meeting_data
        
        else:
            # Use classic logic
            meeting_info = self.fetch_meeting_data(url)
            print(f"Found {len(meeting_info)} meetings (classic style).")
            assets = self.build_asset_data(meeting_info, place=self.place, state_or_province=self.state_or_province)
            print(f"Extracted {len(assets)} assets.")
            return assets


def is_new_pattern_url(url):
    # Add all new-style domains here
    new_domains = [
        "cityofannamaria.com",
        #"staridaho.org",
        "baystlouis-ms.gov",
        "cityoflivingston.org",
    ]
    return any(domain in url for domain in new_domains)


# if __name__ == "__main__":
#     test_urls = [
        # Classic Municode Meetings
        #"https://www.cityofannamaria.com/AgendaCenter",
        #"https://www.staridaho.org/1305/Meetings-Agendas",
        #"https://www.folsom.ca.us/government/city-council-and-commissions/council-meetings-agendas-and-minutes",
        #"https://apps.meridiancity.org/CLERKSCONTENT/meridian_agenda_minutes.aspx#COUNCILAM",
        #"https://bluffton-sc.municodemeetings.com/",
        #"https://www.apexnc.org/838/Agendas-Minutes",
        #"https://www.lyndenwa.org/319/Council-Agendas-Minutes",
        #"https://tumwater-wa.municodemeetings.com/",
        #"https://apps.meridiancity.org/CLERKSCONTENT/meridian_agenda_minutes.aspx#PLANZONEAM"
        #"https://columbus-ga.municodemeetings.com/",
        #"https://hillsborough-nc.municodemeetings.com/",
        # #"https://www.cityofannamaria.com/meetings?field_smart_date_value_1=2025-04-01&field_smart_date_end_value=2025-07-01&combine=&boards-commissions=All",
        # "https://www.staridaho.org/meetings?date_filter%255Bvalue%255D%255Bmonth%255D=1&date_filter%255Bvalue%255D%255Bday%255D=1&date_filter%255Bvalue%255D%255Byear%255D=2022&date_filter_1%255Bvalue%255D%255Bmonth%255D=12&date_filter_1%255Bvalue%255D%255Bday%255D=31&date_filter_1%255Bvalue%255D%255Byear%25=",
        # "https://www.baystlouis-ms.gov/meetings?field_smart_date_value_1=2025-06-01&field_smart_date_end_value=&combine=&boards-commissions=All",
        # "https://www.cityoflivingston.org/meetings?field_smart_date_value_1=2025-06-01&field_smart_date_end_value=2025-07-30&combine=&department=All&boards-commissions=125",
    # ]
    # for url in test_urls:
    #     print(f"\nTesting MunicodeSite for: {url}")
    #     site = MunicodeSite(url)
    #     scrapped_meetings_info=site.scrape()
    #     print(scrapped_meetings_info)
    #     if not scrapped_meetings_info:
    #         print("Got no data")
    #     else:
    #         for i in scrapped_meetings_info:
    #             print("asset_name",i.asset_name,"\n meeting_date",i.meeting_date,"\n meeting_time",i.meeting_time,"\n meeting_id",i.meeting_id,"\n scraped_by",i.scraped_by,"\n url",i.url)
    #             print("="*50)

# #         # if is_new_pattern_url(url):
# #         #     # Use new logic
# #         #     response = site.get_site_raw_data()
# #         #     outer_html = site.get_particular_outer_html(response, "div", "view-content")
# #         #     if not outer_html:
# #         #         print("No 'view-content' found, skipping.")
# #         #         continue
# #         #     meeting_data = site.parse_meetings(outer_html, base_url=url)
# #         #     meeting_data = site.normalize_output_format(meeting_data)
# #         #     print(f"Found {len(meeting_data)} meetings (new style).")
# #         #     for i in meeting_data:
# #         #         print(url,"-->working")
# #         #         print("Asset:", json.dumps(i, indent=4, default=str))
                
# #         # else:
# #         #     # Use classic logic
# #         #     meeting_info = site.fetch_meeting_data(url)
# #         #     print(f"Found {len(meeting_info)} meetings (classic style).")
# #         #     assets = site.build_asset_data(meeting_info, place=site.place, state_or_province=site.state_or_province)
# #         #     print(f"Extracted {len(assets)} assets.")
# #         #     if assets:
# #         #         for i in assets:
# #         #             print("Asset:", json.dumps(i, indent=4, default=str))
# #         #         print(url,"-->working")
