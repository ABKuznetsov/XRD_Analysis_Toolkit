"""CPU-only native cache preparation in an owned interpreter process."""
import json
import sys
from xrd_finder.services.local_phase_cache import LocalPhaseCache


def main():
    request = json.load(sys.stdin)
    cache = LocalPhaseCache(request['root'])
    result = []
    low,high = request.get('two_theta_range') or (5.,120.)
    for source, entry_id in request['keys']:
        ready = cache.ensure_reference_range(source, entry_id, wavelength=request['wavelength'],two_theta_min=low,two_theta_max=high)
        result.append([source, entry_id, ready])
    json.dump(result, sys.stdout)


if __name__ == '__main__':
    main()
