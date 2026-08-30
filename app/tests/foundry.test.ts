import { describe, expect, it } from 'vitest';

import { FoundryFailure, FoundryRefusal, REFUSED, foundryArgs } from '../electron/foundry.js';

describe('foundryArgs', () => {
  it('puts the parser-level flags in front of the subcommand', () => {
    // argparse stops accepting parser-level optionals once a subparser has been
    // chosen, so ordering here is behaviour, not style.
    expect(foundryArgs({ varRoot: '/v', task: 't', session: 's' }, 'task-show')).toEqual([
      '--var',
      '/v',
      '--task',
      't',
      '--session',
      's',
      'task-show',
    ]);
  });

  it('omits a binding it was not given rather than passing an empty one', () => {
    // An empty `--task ''` is not the same call: the CLI's resolution chain
    // would see an explicit task and stop, instead of falling through to the
    // addressed window's own back-pointer.
    expect(foundryArgs({ varRoot: '/v' }, 'task-list')).toEqual(['--var', '/v', 'task-list']);
  });

  it('keeps the subcommand arguments after the subcommand', () => {
    expect(foundryArgs({ varRoot: '/v', task: 't' }, 'deliverable-text', ['--sha', 'ab'])).toEqual([
      '--var',
      '/v',
      '--task',
      't',
      'deliverable-text',
      '--sha',
      'ab',
    ]);
  });

  it('refuses a call with nowhere to run', () => {
    expect(() => foundryArgs({ varRoot: '' }, 'task-list')).toThrow(/varRoot/);
  });
});

describe('the two failures are separable', () => {
  it('keeps a domain refusal apart from a broken install', () => {
    // Exit 3 is "this window is not locked", which a screen renders. Anything
    // else is a bug or a missing binary, which it reports. String-matching
    // stderr to tell them apart is what this avoids.
    expect(new FoundryRefusal('no task', REFUSED).refused).toBe(true);
    expect(new FoundryFailure('ENOENT', null).refused).toBe(false);
    expect(REFUSED).toBe(3);
  });
});
