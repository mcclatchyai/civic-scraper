"""
Platform implementations for civic-scraper.
This module provides backward compatibility imports for all supported platforms.
"""

# Import Site classes from each platform module, maintaining backward compatibility
try:
    from .civic_clerk.site import Site as CivicClerkSite
except ImportError:
    # CivicClerk platform may not be fully implemented
    pass

from .civic_plus.site import Site as CivicPlusSite
from .granicus.site import Site as GranicusSite
from .legistar.site import Site as LegistarSite
from .boarddocs.site import Site as BoardDocsSite

try:
    from .primegov.site import  PrimeGovSite
except ImportError:
    # PrimeGov platform may not be fully implemented
    pass