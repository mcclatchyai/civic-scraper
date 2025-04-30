# This script serves as a test harness for the GranicusSite scraper
#
# It demonstrates how to use the scraper for both Granicus RSS feeds
# and standard Granicus HTML archive pages.
#
# The script performs the following steps:
# 1. Initializes a GranicusSite scraper instance for a specific URL (RSS or HTML).
# 2. Calls the scrape() method to retrieve meeting assets (agendas, minutes, etc.).
# 3. Serializes the collected Asset objects into JSON format.
# 4. Prints the JSON output to the console.
# 5. Saves the JSON output to a corresponding file (e.g., granicus_agendas_rss.json).
#
# This allows us to quickly verify the scraper's functionality against
# different Granicus site structures and output formats.

import sys
import os
from datetime import datetime, date, time
import json


# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from civic_scraper.platforms.granicus.site import Site as GranicusSite

# Granicus RSS feed URLs (choose one):
# - Agendas feed
# granicus_url = "https://coralsprings.granicus.com/ViewPublisher.php?view_id=3"
# granicus_url = "https://sacramento.granicus.com/ViewPublisherRSS.php?view_id=22&mode=agendas"
# - Minutes feed (uncomment to use minutes)
# granicus_url = "https://sacramento.granicus.com/ViewPublisherRSS.php?view_id=22&mode=minutes"
# granicus_url = "https://marysvilleca.granicus.com/ViewPublisherRSS.php?view_id=1&mode=agendas"

def serialize_asset(asset):
    d = asset.__dict__.copy()
    if isinstance(d.get('meeting_date'), date):
        d['meeting_date'] = d['meeting_date'].isoformat()
    if isinstance(d.get('meeting_time'), time):
        d['meeting_time'] = d['meeting_time'].strftime('%H:%M:%S')
    return d

# --- Test RSS Feed (Sacramento) ---
# granicus_rss_url = "https://sacramento.granicus.com/ViewPublisherRSS.php?view_id=22&mode=agendas"
# granicus_rss_url = "https://liveoakca.granicus.com/ViewPublisherRSS.php?view_id=1&mode=agendas"
granicus_rss_url = "https://mooresvillenc.granicus.com/ViewPublisherRSS.php?view_id=1&mode=agendas"
# granicus_rss_url = "https://lincoln.granicus.com/ViewPublisherRSS.php?view_id=2&wmode=transparent&mode=agendas"
print(f"\n--- Scraping RSS: {granicus_rss_url} ---")
# Place will be extracted automatically, state needs to be provided
scraper_rss = GranicusSite(granicus_rss_url, state_or_province="CA")
assets_rss = scraper_rss.scrape()

# Convert the AssetCollection to a list of JSON-serializable dicts
output_data_rss = [serialize_asset(asset) for asset in assets_rss]

# Print JSON to stdout
json_str_rss = json.dumps(output_data_rss, indent=4)
print(json_str_rss)
# Save JSON output to a file
output_file_rss = os.path.join(".\\tests\\granicus_test_output", "granicus_agendas_rss.json")
with open(output_file_rss, 'w', encoding='utf-8') as f:
    f.write(json_str_rss)
print(f"Saved RSS output to {output_file_rss}")


# --- Test HTML Page (Coral Springs) ---
granicus_html_url = "https://coralsprings.granicus.com/ViewPublisher.php?view_id=3"
print(f"\n--- Scraping HTML: {granicus_html_url} ---")
# Place will be extracted automatically, state needs to be provided (guessing FL)
scraper_html = GranicusSite(granicus_html_url, state_or_province="FL") # Provide state if known
assets_html = scraper_html.scrape()

# Convert the AssetCollection to a list of JSON-serializable dicts
output_data_html = [serialize_asset(asset) for asset in assets_html]

# Print JSON to stdout
json_str_html = json.dumps(output_data_html, indent=4)
print(json_str_html)
# Save JSON output to a file
output_file_html = os.path.join(".\\tests\\granicus_test_output", "granicus_agendas_html.json")
with open(output_file_html, 'w', encoding='utf-8') as f:
    f.write(json_str_html)
print(f"Saved HTML output to {output_file_html}")


# Optional: You can also test with download option (might only work well for RSS)
# assets_with_download = scraper_rss.scrape(download=True, file_size=10)
# output_data_with_download = [asset.__dict__ for asset in assets_with_download]
# print("\nMeetings with downloaded documents:")
# print(json.dumps(output_data_with_download, indent=4))