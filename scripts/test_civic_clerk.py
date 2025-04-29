import sys
import os
from datetime import datetime
import json

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from civic_scraper.platforms.civic_clerk.site import CivicClerkSite

# Test with a modern CivicClerk site - choose one that's public-facing and should have meetings
# Try both a modern portal and the site that was failing before
sites = [
    {"url": "https://jacksonmi.civicclerk.com", "place": "jackson", "state": "mi"},
    {"url": "https://alpharettaga.civicclerk.com", "place": "alpharetta", "state": "ga"},
    {"url": "https://ranchocordovaca.portal.civicclerk.com", "place": "rancho cordova", "state": "ca"}
]

# Try each site until we get successful results
for site_info in sites:
    try:
        civic_clerk_url = site_info["url"]
        scraper = CivicClerkSite(
            civic_clerk_url, 
            place=site_info["place"], 
            state_or_province=site_info["state"]
        )
        
        print(f"\n===== Testing site: {civic_clerk_url} =====")
        
        # Scrape meetings without downloading documents
        print(f"Scraping meetings from {civic_clerk_url}")
        assets = scraper.scrape(download=False)
        
        # Convert the AssetCollection to a list of dictionaries for JSON output
        output_data = [
            {
                "asset_name": asset.asset_name,
                "committee_name": asset.committee_name,
                "meeting_date": str(asset.meeting_date),
                "meeting_id": asset.meeting_id,
                "url": asset.url
            } 
            for asset in assets
        ]
        
        if output_data:
            print(f"Found {len(output_data)} assets!")
            print(json.dumps(output_data[:3], indent=4))  # Show first 3 assets
            
            # If we found assets, no need to try other sites
            break
        else:
            print("No assets found for this site. Trying another site...")
            
    except Exception as e:
        print(f"Error testing site {site_info['url']}: {str(e)}")
        import traceback
        traceback.print_exc()
        print("Trying another site...")
        continue

# If we tried all sites and none worked
else:
    print("\n⚠️ Could not find any meetings from any of the test sites.")
    print("The CivicClerk site structure might have changed again.")
    print("Check the error messages above for more details.")