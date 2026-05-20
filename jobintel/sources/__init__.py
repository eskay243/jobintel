from jobintel import config
from jobintel.sources.adzuna import fetch_adzuna_all
from jobintel.sources.arbeitnow import fetch_arbeitnow
from jobintel.sources.jobicy import fetch_jobicy
from jobintel.sources.remoteok import fetch_remoteok
from jobintel.sources.remotive import fetch_remotive
from jobintel.sources.themuse import fetch_themuse


def all_fetchers():
    fetchers = [fetch_remotive, fetch_arbeitnow]
    if config.ADZUNA_ENABLED:
        fetchers.append(fetch_adzuna_all)
    if config.THEMUSE_ENABLED:
        fetchers.append(fetch_themuse)
    if config.REMOTEOK_ENABLED:
        fetchers.append(fetch_remoteok)
    fetchers.append(fetch_jobicy)  # always on — free, no key required
    return fetchers
