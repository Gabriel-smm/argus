"""The Argus Judge: classified signals + a site profile -> blue / white / red with a reason."""

from argus_judge.jamming import Assessment, assess_noise_floor
from argus_judge.locate import LocationError, attach_locations, read_track
from argus_judge.profile import CLASSES, ProfileError, Site, load_site, parse_site
from argus_judge.report import Report, build_report, summary_text, to_dict, to_geojson
from argus_judge.rules import Verdict, judge_row

__all__ = [
    "Assessment", "CLASSES", "LocationError", "ProfileError", "Report", "Site", "Verdict",
    "assess_noise_floor", "attach_locations", "build_report", "judge_row", "load_site",
    "parse_site", "read_track", "summary_text", "to_dict", "to_geojson",
]
