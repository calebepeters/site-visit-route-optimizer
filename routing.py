"""
routing.py — Two-phase multi-day site visit scheduler.

Phase 1: k-means geographic clustering orders sites into a geographically
         coherent visit sequence.
Phase 2: The technician walks that sequence using nearest-neighbor; day
         boundaries are cut whenever the 10-hour budget is exhausted —
         mid-cluster if needed. The next day resumes from wherever the
         technician ended, regardless of cluster membership.

All time values are in **seconds** throughout this module, matching the OSRM
Table API output. No conversion is performed on incoming matrices.
"""
from __future__ import annotations

import math

from sklearn.cluster import KMeans

# Constants — all in seconds
AVG_TRAVEL_SEC = 900    # assumed average drive time between sites for day estimation (15 min)
SITE_VISIT_SEC = 2700   # on-site service time per visit (45 min)
DAY_BUDGET_SEC = 36000  # 10-hour work day

# Derived constant: estimated sites that fit in one day
_SITES_PER_DAY = math.floor(DAY_BUDGET_SEC / (SITE_VISIT_SEC + AVG_TRAVEL_SEC))  # = 10


def _nearest_neighbor_order(
    global_indices: list[int],
    start_global: int,
    matrix_seconds: list[list[float]],
) -> list[int]:
    """
    Nearest-neighbor traversal over *global_indices*, starting from *start_global*.

    Parameters
    ----------
    global_indices  : global node indices (into matrix_seconds) for the sites to visit.
    start_global    : global index of the starting position (airport or previous last site).
    matrix_seconds  : full NxN travel-time matrix in seconds.

    Returns
    -------
    Ordered list of global indices (same elements as global_indices, reordered).
    """
    remaining = list(global_indices)
    ordered = []
    current = start_global

    while remaining:
        nearest = min(remaining, key=lambda g: matrix_seconds[current][g])
        ordered.append(nearest)
        remaining.remove(nearest)
        current = nearest

    return ordered


def cluster_sites(
    sites: list[dict],
    travel_matrix_seconds: list[list[float]],
) -> list[list[int]]:
    """
    Group sites into geographically coherent clusters using k-means on lat/lon.

    Clusters define *visit order*, not fixed day assignments — day boundaries
    are determined later by the time budget in solve().

    Parameters
    ----------
    sites                 : list of site dicts (length N). Each has 'Latitude', 'Longitude'.
    travel_matrix_seconds : (N+1)×(N+1) matrix in seconds; index 0 = airport, 1..N = sites.

    Returns
    -------
    List of clusters. Each cluster is a list of global indices (1-based into the matrix).
    """
    n_sites = len(sites)
    if n_sites == 0:
        return []

    k = math.ceil(n_sites / _SITES_PER_DAY)
    k = max(k, 1)

    all_globals = list(range(1, n_sites + 1))

    if k == 1:
        return [all_globals]

    coords = [
        [float(sites[g - 1]["Latitude"]), float(sites[g - 1]["Longitude"])]
        for g in all_globals
    ]
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(coords)

    raw_clusters: dict[int, list[int]] = {}
    for g, lbl in zip(all_globals, labels):
        raw_clusters.setdefault(int(lbl), []).append(g)

    return list(raw_clusters.values())


def order_day(
    day_global_indices: list[int],
    start_global: int,
    travel_matrix_seconds: list[list[float]],
) -> list[int]:
    """
    Determine visit order for a set of sites using nearest-neighbor traversal.

    Parameters
    ----------
    day_global_indices    : global indices of sites to visit.
    start_global          : global index of the starting position (airport or last site).
    travel_matrix_seconds : full NxN travel-time matrix in seconds.

    Returns
    -------
    Ordered list of global indices for today's visits.
    """
    return _nearest_neighbor_order(day_global_indices, start_global, travel_matrix_seconds)


def solve(
    sites: list[dict],
    travel_matrix_seconds: list[list[float]],
    airport: dict,
) -> list[dict] | None:
    """
    Solve the multi-day site visit schedule.

    Clusters define geographic visit order. Day boundaries are cut when the
    10-hour budget is exhausted — the next day resumes from the last site
    visited, regardless of which cluster it belonged to.

    Parameters
    ----------
    sites                 : list of site dicts (original fields). Length N.
    travel_matrix_seconds : (N+1)×(N+1) matrix in seconds; index 0 = airport, 1..N = sites.
    airport               : airport dict (used for labelling only).

    Returns
    -------
    List of site dicts with 'Day' and 'Visit_Order' added (sorted by Day, Visit_Order),
    or None if no sites could be scheduled.
    """
    n_sites = len(sites)
    if n_sites == 0:
        return []

    print(f"  [routing] {n_sites} sites to schedule.")

    # Phase 1: geographic clustering — determines visit order, not day assignment
    clusters = cluster_sites(sites, travel_matrix_seconds)
    print(f"  [routing] {len(clusters)} geographic cluster(s).")

    # Order clusters to form a loop: start from airport, visit all clusters,
    # and end as close to the airport as possible.
    #
    # For small k (≤ 8): try every permutation and pick the one minimising
    #   airport→cluster[0] + cluster[0]→cluster[1] + … + cluster[-1]→airport
    # For larger k: greedy nearest-centroid with a return-to-airport lookahead.
    #
    # Travel cost between two groups = average pairwise travel time (centroid proxy).
    def _avg_travel(from_globals: list[int], to_globals: list[int]) -> float:
        total = sum(travel_matrix_seconds[f][t] for f in from_globals for t in to_globals)
        return total / (len(from_globals) * len(to_globals))

    airport_node = [0]

    def _loop_cost(order: list[list[int]]) -> float:
        cost = _avg_travel(airport_node, order[0])
        for i in range(len(order) - 1):
            cost += _avg_travel(order[i], order[i + 1])
        cost += _avg_travel(order[-1], airport_node)  # closing leg back to airport
        return cost

    if len(clusters) <= 8:
        from itertools import permutations
        clusters = min(permutations(clusters), key=_loop_cost)
        clusters = list(clusters)
    else:
        # Greedy with mild return-to-airport lookahead (weight = 0.3)
        LOOKAHEAD = 0.3
        remaining = list(clusters)
        ordered_clusters: list[list[int]] = []
        prev = airport_node
        while remaining:
            best = min(
                remaining,
                key=lambda c: _avg_travel(prev, c) + LOOKAHEAD * _avg_travel(c, airport_node),
            )
            ordered_clusters.append(best)
            remaining.remove(best)
            prev = best
        clusters = ordered_clusters

    # Phase 2: walk clusters in order, nearest-neighbor within each cluster,
    # cutting day boundaries by time budget (not by cluster membership).
    day = 1
    visit_order = 1
    day_elapsed = 0.0   # seconds used so far today
    current_pos = 0     # global index; 0 = airport at start of Day 1
    results: list[dict] = []

    for cluster in clusters:
        # Order this cluster's sites by nearest-neighbor from our current position
        remaining = list(cluster)
        while remaining:
            nearest = min(remaining, key=lambda g: travel_matrix_seconds[current_pos][g])
            travel = travel_matrix_seconds[current_pos][nearest]

            # Would adding this site blow the daily budget?
            if day_elapsed > 0 and day_elapsed + travel + SITE_VISIT_SEC > DAY_BUDGET_SEC:
                # End current day here; next day starts from current_pos (last site)
                print(f"  [routing] Day {day}: {visit_order - 1} site(s).")
                day += 1
                visit_order = 1
                day_elapsed = 0.0
                # Recalculate travel from the same current_pos (unchanged)
                travel = travel_matrix_seconds[current_pos][nearest]

            day_elapsed += travel + SITE_VISIT_SEC
            row = dict(sites[nearest - 1])
            row["Day"] = day
            row["Visit_Order"] = visit_order
            results.append(row)

            current_pos = nearest
            visit_order += 1
            remaining.remove(nearest)

    if results:
        print(f"  [routing] Day {day}: {visit_order - 1} site(s).")

    if not results:
        return None

    results.sort(key=lambda r: (r["Day"], r["Visit_Order"]))
    return results
