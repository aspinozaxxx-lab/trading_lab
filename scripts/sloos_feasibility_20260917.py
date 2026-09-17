"""Nine bounded official SLOOS sample GETs; no numeric features or market data."""

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from market_lab import futures_v97_hurricane_supply as transport
from market_lab import futures_v101_manufacturing_demand as prior

ROOT = Path('/srv/trading_lab_data/source_evidence/sloos_feasibility_20260917_v1/capture')
ORIGIN = 'https://www.federalreserve.gov'
SAMPLES = ['201710', '202510']


def links(raw):
    return sorted({urljoin(ORIGIN, u) for u in
                   re.findall(r'href=["\']([^"\']+)["\']', raw.decode('utf-8-sig'))})


def unique(items, pattern):
    result = [u for u in items if urlparse(u).netloc == 'www.federalreserve.gov'
              and urlparse(u).scheme == 'https'
              and re.fullmatch(pattern, urlparse(u).path) and not urlparse(u).query]
    prior.base.require(len(result) == 1, 'ambiguous official sample link')
    return result[0]


def main():
    b = prior.base
    b.require(os.name == 'posix' and os.getuid() == 999, 'server user only')
    ROOT.mkdir(exist_ok=False)
    b.write_json(ROOT/'started.json', {
        'started_at_utc': datetime.now(UTC).isoformat(),
        'script_sha256': b.sha(Path(__file__)),
        'transport_sha256': b.sha(Path(transport.__file__)),
        'samples': SAMPLES, 'maximum_requests': 9, 'maximum_response_bytes': 3000000,
        'source_only': True, 'numeric_features_read': False,
        'economic_admission': False, 'no_retry_or_redirect': True,
        'attribution': 'Board of Governors of the Federal Reserve System, SLOOS; '
        'private research only, original notices retained, no endorsement.',
        'prior_exposure': 'Two2025 narrative HTML releases and October2025Q1A/Q1B '
        'numeric bank counts incidentally displayed by web; not an unseen corpus. '
        'No2026 market outcomes, credentials, paid/private bank-level data.'})
    status, failure, requests, selected = 'COMPLETE_FEASIBILITY_ONLY', None, 0, {}
    try:
        index = None
        for name, path in [('index.html','/data/sloos.htm'),
                           ('terms.html','/disclaimer.htm'),
                           ('announcements.html','/feeds/sloos.html')]:
            requests += 1
            raw = transport.fetch(ORIGIN+path, ROOT/name, 3000000, 1.0)
            if name == 'index.html':
                index = links(raw)
        for sample in SAMPLES:
            url = unique(index, rf'/data/sloos/sloos-{sample}\.htm')
            requests += 1
            raw = transport.fetch(url, ROOT/(sample+'.html'), 3000000, 1.0)
            items = links(raw)
            table = unique(items, rf'/data/sloos/sloos-{sample}-table-1\.htm')
            cover = unique(items, rf'/data/documents/sloos-{sample}(?:-fullreport)?\.pdf')
            selected[sample] = {'narrative': url, 'table': table, 'cover': cover}
            for name, target in [(sample+'-table.html',table), (sample+'.pdf',cover)]:
                requests += 1
                transport.fetch(target, ROOT/name, 3000000, 1.0)
            print(sample, 'captured', flush=True)
        b.write_json(ROOT/'links.json',selected)
    except Exception as error:
        status, failure = 'FAILED_SOURCE_NO_RETRY', str(error)
    b.write_json(ROOT/'manifest.json', {
        'status': status, 'failure': failure, 'requests_attempted': requests,
        'completed_at_utc': datetime.now(UTC).isoformat(),
        'source_only': True, 'economic_admission': False,
        'files': {p.name: b.sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()}})
    print(status, b.sha(ROOT/'manifest.json'), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == '__main__':
    main()
