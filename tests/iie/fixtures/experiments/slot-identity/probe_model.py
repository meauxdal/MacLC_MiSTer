#!/usr/bin/env python3
"""Model the ROM helper's word arithmetic, without bus errors or guest code."""


def probe(initial, word_step):
    index = initial
    d1 = (initial + 1) & 0xffff
    d2 = 0
    index = (index + word_step) & 0xffff
    first_equal = d1 == index
    if first_equal:
        index = (index + 3 * word_step) & 0xffff
        d2 = index
    d1 = (d1 + 3) & 0xffff
    return {'first_equal': first_equal, 'final_equal': d1 == d2,
            'd1': d1, 'd2': d2, 'word_reads': 4 if first_equal else 1}


def evaluate():
    counts = {}
    for step in (0, 1, 2):
        accepted = [index for index in range(65536) if probe(index, step)['final_equal']]
        counts[str(step)] = {'accepted': len(accepted),
                             'sole_accepted_index': accepted[0] if len(accepted) == 1 else None}
    assert counts == {'0': {'accepted': 1, 'sole_accepted_index': 0xfffc},
                      '1': {'accepted': 65536, 'sole_accepted_index': None},
                      '2': {'accepted': 1, 'sole_accepted_index': 0xfffc}}
    return {'scope': 'fixed word-read increment, observational index reads, no bus errors',
            'initial_indices_per_step': 65536, 'counts': counts,
            'observed_cardless_case': probe(0, 0),
            'constant_index_counterexample': probe(0xfffc, 0)}
