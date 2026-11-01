#!/usr/bin/env python3
"""Run one original sampled diagnostic case against the deferred-reset closure."""
import argparse
from prepare import HERE, SAMPLED, once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fast', type=int, choices=(0, 1), default=0)
    parser.add_argument('--fork', type=int, choices=(0, 1), default=0)
    args = parser.parse_args()
    source = SAMPLED / 'run.py'
    text = once(source.read_text(), 'for fast in (0, 1):', f'for fast in ({args.fast},):')
    text = once(text, 'for fork in (0, 1):', f'for fork in ({args.fork},):')
    text = once(text, 'for phase in (2, 7):', 'for phase in (2,):')
    text = once(text, "HERE / 'results.json'", f"HERE / 'regression-{args.fast}-{args.fork}.json'")
    # Import resolution binds the inherited runner to this candidate's generator.
    scope = {'__name__': 'diagnostic_regression', '__file__': str(source)}
    exec(compile(text, str(source), 'exec'), scope)
    inherited_prepare = scope['prepare']

    def prepare():
        closure, manifest, inputs = inherited_prepare()
        return closure, manifest, inputs + [HERE / 'regression.py']

    scope['prepare'] = prepare
    scope['main']()


if __name__ == '__main__':
    main()
