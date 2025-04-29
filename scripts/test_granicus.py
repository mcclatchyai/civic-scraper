import sys
import os
from datetime import datetime
import json

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from civic_scraper.platforms.granicus.site import Site as GranicusSite

# Example Granicus RSS feed URL
# granicus_url = "https://coralsprings.granicus.com/ViewPublisher.php?view_id=3" #place="coralsprings", state_or_province="fl"
granicus_url = "https://sacramento.granicus.com/viewpublisher.php?view_id=21"
scraper = GranicusSite(granicus_url, place="sacramento", state_or_province="CA")

# Scrape meetings using the scrape function
assets = scraper.scrape()

# Convert the AssetCollection to a list of dictionaries for JSON output
output_data = [asset.__dict__ for asset in assets]
print(json.dumps(output_data, indent=4))

# Optional: You can also test with download option
# assets_with_download = scraper.scrape(download=True, file_size=10)
# output_data_with_download = [asset.__dict__ for asset in assets_with_download]
# print("\nMeetings with downloaded documents:")
# print(json.dumps(output_data_with_download, indent=4))