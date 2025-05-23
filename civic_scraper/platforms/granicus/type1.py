from bs4 import BeautifulSoup
import re
import logging
from .base import GranicusBaseScraper 

logger = logging.getLogger(__name__)

class GranicusType1Scraper(GranicusBaseScraper):
    """
    Scraper for Granicus Type 1 URLs.
    - Year selector TabbedPanel is INSIDE the div with class CollapsiblePanelTab's content.
    - Multiple CollapsiblePanelTabs for different committees.
    Example: "https://cityofbradenton.granicus.com/ViewPublisher.php?view_id=1" with CollapsiblePanelTab = "City Council"
    """
    def _extract_meeting_details_internal(self, soup: BeautifulSoup, panel_name: str | None) -> list[dict]:
        if not panel_name:
            logger.warning(f"{self.__class__.__name__}: This scraper type requires a panel_name to identify the correct committee section.")
            return []

        meetings = []
        
        panel_found = False
        target_panel_content_div = None # This will be the CollapsiblePanelContent
        
        # Find all panel headers
        panels_headers = soup.find_all('div', class_=['CollapsiblePanelTab', 'CollapsiblePanelTabNotSelected'])
        
        if not panels_headers:
            logger.info(f"{self.__class__.__name__}: No 'CollapsiblePanelTab' or 'CollapsiblePanelTabNotSelected' divs found on the page for panel '{panel_name}'.")
            return []

        for panel_header_div in panels_headers:
            # Try to find a more specific text container within the header
            text_container = panel_header_div.find(['a', 'h3', 'span', 'div']) # Added div for cases like Marysville
            current_panel_name_text = panel_header_div.get_text(strip=True)
            if text_container: # Prefer text from specific inner tag if present
                current_panel_name_text = text_container.get_text(strip=True)

            if current_panel_name_text == panel_name:
                panel_found = True
                # The content div is the next sibling of the header div
                content_div = panel_header_div.find_next_sibling('div', class_='CollapsiblePanelContent')
                if content_div:
                    target_panel_content_div = content_div
                else:
                    logger.warning(f"{self.__class__.__name__}: Panel '{panel_name}' header found, but its 'CollapsiblePanelContent' sibling is missing.")
                break
        
        if not panel_found:
            logger.warning(f"{self.__class__.__name__}: Panel '{panel_name}' not found.")
            available_panels = []
            for p_header in panels_headers:
                text_c = p_header.find(['a', 'h3', 'span', 'div'])
                available_panels.append(text_c.get_text(strip=True) if text_c else p_header.get_text(strip=True))
            if available_panels: logger.info(f"{self.__class__.__name__}: Available panels: {available_panels}")
            else: logger.info(f"{self.__class__.__name__}: No CollapsiblePanelTab elements found on the page.")
            return [] # Panel not found
        
        if not target_panel_content_div:
            logger.warning(f"{self.__class__.__name__}: Panel '{panel_name}' found but its content div (CollapsiblePanelContent) is missing or could not be identified.")
            return [] # Panel content missing.

        # Type 1 STRICTLY requires year tabs (a 'TabbedPanels' div) INSIDE the panel's content div.
        tabbed_panels_container_div = target_panel_content_div.find('div', class_='TabbedPanels')
        
        if not tabbed_panels_container_div:
            logger.info(f"{self.__class__.__name__}: Panel '{panel_name}' content found, but the characteristic 'TabbedPanels' div (for year selection) was NOT found *within* this panel's content. This structure does not match Type 1 for this panel.")
            # Check for a single table directly within target_panel_content_div as a fallback if no TabbedPanels
            table = target_panel_content_div.find('table', class_='listingTable')
            if table:
                logger.info(f"{self.__class__.__name__}: No 'TabbedPanels' div in panel '{panel_name}', but found a direct listingTable. Processing it.")
                for row in table.find_all('tr', class_=['listingRow', 'listingRowAlt']):
                    meeting = self._extract_meeting_from_row(row, "DefaultYear")  
                    if meeting: meetings.append(meeting)
                return meetings
            return [] # If no TabbedPanels div inside the panel's content, and no direct table, it's not Type 1.

        # Process the TabbedPanels structure found within tabbed_panels_container_div
        year_tabs_ul = tabbed_panels_container_div.find('ul', class_='TabbedPanelsTabGroup')
        year_contents_group_div = tabbed_panels_container_div.find('div', class_='TabbedPanelsContentGroup')
        
        if year_tabs_ul and year_contents_group_div:
            year_tabs_li_elements = year_tabs_ul.find_all('li', class_='TabbedPanelsTab', recursive=False)
            year_content_divs = year_contents_group_div.find_all('div', class_='TabbedPanelsContent', recursive=False)

            if not year_tabs_li_elements or not year_content_divs:
                logger.warning(f"{self.__class__.__name__}: Panel '{panel_name}' - 'TabbedPanels' structure has TabGroup/ContentGroup but they are empty or missing <li> tabs / content divs.")
                # Fallback: Check for a single table directly within tabbed_panels_container_div
                table = tabbed_panels_container_div.find('table', class_='listingTable')
                if table:
                    logger.info(f"{self.__class__.__name__}: Processing single listingTable found directly within 'TabbedPanels' div of panel '{panel_name}'.")
                    for row in table.find_all('tr', class_=['listingRow', 'listingRowAlt']):
                        meeting = self._extract_meeting_from_row(row, "DefaultYear")  
                        if meeting: meetings.append(meeting)
                    return meetings # Return if this fallback table is processed
                return [] # No valid structure found

            if len(year_tabs_li_elements) != len(year_content_divs):
                logger.warning(f"{self.__class__.__name__}: Mismatch between number of year tabs ({len(year_tabs_li_elements)}) and content sections ({len(year_content_divs)}) in panel '{panel_name}'. Processing based on shorter list.")
            
            for i in range(min(len(year_tabs_li_elements), len(year_content_divs))):
                year_tab_li = year_tabs_li_elements[i]
                content_for_year_div = year_content_divs[i]
                year_text = year_tab_li.get_text(strip=True)
                logger.info(f"{self.__class__.__name__}: Processing year tab '{year_text}' for panel '{panel_name}'")
                
                table = content_for_year_div.find('table', class_='listingTable')
                if table:
                    for row in table.find_all('tr', class_=['listingRow', 'listingRowAlt']):
                        meeting = self._extract_meeting_from_row(row, year_text)
                        if meeting: meetings.append(meeting)
                else:
                    logger.warning(f"{self.__class__.__name__}: No listingTable found in content for year '{year_text}' in panel '{panel_name}'.")
        else:
            # Case: 'TabbedPanels' div exists, but no TabGroup/ContentGroup.
            # This might mean a single listingTable directly within 'TabbedPanels'.
            table = tabbed_panels_container_div.find('table', class_='listingTable')
            if table:
                logger.info(f"{self.__class__.__name__}: Panel '{panel_name}' has 'TabbedPanels' div but no distinct year groups (TabGroup/ContentGroup). Processing single listingTable found directly within 'TabbedPanels' div.")
                for row in table.find_all('tr', class_=['listingRow', 'listingRowAlt']):
                    meeting = self._extract_meeting_from_row(row, "DefaultYear")  
                    if meeting: meetings.append(meeting)
            else:
                logger.warning(f"{self.__class__.__name__}: Panel '{panel_name}' - 'TabbedPanels' div found, but no TabGroup/ContentGroup and no direct listingTable within it. Structure not recognized.")
                return [] 
        
        logger.info(f"{self.__class__.__name__}: Extracted {len(meetings)} meetings for panel '{panel_name}'.")
        return meetings

    def _extract_meeting_from_row(self, row_element, year_context: str) -> dict | None:
        """
        Helper to extract meeting details from a table row (<tr> element).
        'year_context' is the year from the tab, used for logging/context if needed.
        """
        cells = row_element.find_all('td') # listItem class might not always be on td
        if not cells or len(cells) < 2: # Need at least name and date
            logger.debug(f"Skipping row, not enough cells: {row_element.prettify()}")
            return None
        
        meeting_data = {}
        # Name is usually in the first cell
        meeting_data['name'] = cells[0].get_text(separator=' ', strip=True).replace('\xa0', ' ')
        # Date is usually in the second cell
        meeting_data['date'] = cells[1].get_text(strip=True).replace('\xa0', ' ')
        
        # Try to get a source for meeting_id (e.g. clip_id, event_id)
        meeting_id_source = ""
        all_links_in_row = row_element.find_all('a', href=True)
        for link_tag in all_links_in_row:
            href = link_tag['href']
            # Common identifiers for meetings in Granicus
            clip_id_match = re.search(r'[?&](?:clip_id|event_id|meeting_id)=(\d+)', href, re.IGNORECASE)
            if clip_id_match:
                meeting_id_source = clip_id_match.group(1)
                break
        meeting_data['meeting_id_source'] = meeting_id_source

        
        # Agenda (often in cell 2 or by text 'Agenda')
        if len(cells) > 2: # Cell index 2
            agenda_cell_content = cells[2]
            agenda_link_tag = agenda_cell_content.find('a', href=True, text=re.compile(r'Agenda', re.I))
            if not agenda_link_tag: # If no text match, assume link in cell 2 is agenda if it's a link
                agenda_link_tag = agenda_cell_content.find('a', href=True)
            if agenda_link_tag:
                meeting_data['agenda_url'] = agenda_link_tag['href']
        
        # Minutes (often in cell 3 or by text 'Minutes')
        if len(cells) > 3: # Cell index 3
            minutes_cell_content = cells[3]
            minutes_link_tag = minutes_cell_content.find('a', href=True, text=re.compile(r'Minutes', re.I))
            if not minutes_link_tag: # If no text match, assume link in cell 3 is minutes if it's a link
                minutes_link_tag = minutes_cell_content.find('a', href=True)
            if minutes_link_tag:
                meeting_data['minutes_url'] = minutes_link_tag['href']
        
        # Video (search all links in row for common video patterns)
        for link_tag in all_links_in_row:
            href = link_tag['href']
            link_text = link_tag.get_text(strip=True)
            # Common patterns for video links
            if 'ViewEvent.php' in href or 'MediaPlayer.php' in href or \
               re.search(r'Video|Watch|Media|View Event', link_text, re.I) or \
               (link_tag.find('img') and link_tag.find('img').get('alt', '').lower() in ['video', 'play video']):
                meeting_data['video_url'] = href
                break # Take the first likely video link
        
        # Packet (search all links for 'Packet')
        for link_tag in all_links_in_row:
            if re.search(r'Packet|Agenda Packet', link_tag.get_text(strip=True), re.I):
                meeting_data['packet_url'] = link_tag['href']
                break
        
        # Try to extract time from name or date cell text if not found by _parse_date_time implicitly
        # This is a fallback, _parse_date_time in base class already tries this.
        combined_text_for_time = meeting_data.get('name', '') + " " + meeting_data.get('date', '')
        time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)', combined_text_for_time)
        if time_match and not meeting_data.get('time'): # Only set if not already found by _parse_date_time
            meeting_data['time'] = time_match.group(1)
        
        return meeting_data

