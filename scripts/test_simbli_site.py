import json
import logging
from datetime import datetime
from civic_scraper.platforms.simbli.site import SimbliSite
from civic_scraper.base.cache import Cache
from civic_scraper.base.asset import AssetCollection

# Configure logging to see scraper detection details
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Test URLs for Simbli scraper
TEST_URLS = {
    "gcss": {               # we don't get output (0 assets) from this site, but it has a json output file created
        "url": "https://simbli.eboardsolutions.com/SB_Meetings/SB_MeetingListing.aspx?S=36031066",
        "state": "ga"
    },
    "site1": {              # we dont get output (0 assets) from this site, but it has a json output file created
        "url": "https://simbli.eboardsolutions.com/SB_Meetings/SB_MeetingListing.aspx?S=36031513",
        "place": "site1",
        "state": "xx"
    },
    "site2": {              # we dont get any output (0 assets) from this site, but it has a json output file created
        "url": "https://simbli.eboardsolutions.com/SB_Meetings/SB_MeetingListing.aspx?S=36030877",
        "place": "site2",
        "state": "xx"
    },
    "site3": {              # we get output from this site, and also has a json output file created
        "url": "https://simbli.eboardsolutions.com/SB_Meetings/SB_MeetingListing.aspx?S=4032",
        "place": "site3",
        "state": "xx"
    },
    "site4": {              # we didn't get output (0 assets) from this site, but it has a json output file created
        "url": "https://simbli.eboardsolutions.com/SB_Meetings/SB_MeetingListing.aspx?S=36031062",
        "place": "site4",
        "state": "xx"
    }
}

# Select which test to run
SELECTED_TEST = "site1"  # Options: gcss, site1, site2, site3, site4

# Get the selected test configuration
if SELECTED_TEST not in TEST_URLS:
    raise ValueError(f"Invalid test selection: {SELECTED_TEST}. Available options: {list(TEST_URLS.keys())}")

test_config = TEST_URLS[SELECTED_TEST]
site_url = test_config["url"]
place = test_config.get("place")  # Use .get() to handle optional 'place'
state = test_config["state"]

# Execute single site test
print("="*60)
print("TESTING SIMBLI SCRAPER")
print("="*60)
print(f"Test: {SELECTED_TEST.upper()}")
print(f"Site URL: {site_url}")
if place:
    print(f"Place: {place}, {state}")
else:
    print(f"Place: To be auto-detected, State: {state}")
print("-"*60)

# SimbliSite does not take committee_names
# If place is None, the scraper will attempt to extract it.
site = SimbliSite(site_url, cache=Cache('/tmp/cache'), place=place, state_or_province=state)

print("Starting scrape...")
# SimbliSite scrape method doesn't take start_date, so calling without it.
assets: AssetCollection = site.scrape()
print("-"*60)

# Save assets to JSON
# Use site.place as it may have been auto-detected
output_place = site.place if site.place else "unknown_place"
output_filename = f"{output_place.lower().replace(' ', '_')}_{state.lower()}_{SELECTED_TEST}_assets_{datetime.now().strftime('%Y-%m-%d')}.json"
assets_list = [asset.__dict__ for asset in assets]
with open(output_filename, 'w') as f:
    json.dump(assets_list, f, indent=2, default=str)

# Examine the results
print(f"SCRAPING COMPLETE - Found {len(assets)} total assets")
print(f"Place detected/used: {site.place}")
print("="*60)

# Group assets by committee to check for cross-contamination
assets_by_committee = {}
for asset in assets:
    committee = asset.committee_name
    if committee not in assets_by_committee:
        assets_by_committee[committee] = []
    assets_by_committee[committee].append(asset)

print("ASSETS BY COMMITTEE:")
for committee, committee_assets in assets_by_committee.items():
    print(f"\n{committee}: {len(committee_assets)} assets")
    for asset in committee_assets[:3]:  # Show first 3 assets per committee
        print(f"  - {asset.asset_name} ({asset.meeting_date})")
    if len(committee_assets) > 3:
        print(f"  ... and {len(committee_assets) - 3} more")

print("\n" + "="*60)
print("DETAILED ASSET INFORMATION:")
print("="*60)

print(f"SUMMARY: Found {len(assets)} total assets across {len(assets_by_committee)} committees")